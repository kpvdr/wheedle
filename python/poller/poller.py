#!/usr/bin/python3
"""
Poller for GitHub projects that contain actions and artifacts. This module polls a GitHub project
checking for new artifacts. If found, the poller updates Stagger and sends the artifacts to Bodega.

The poller requires a GitHub user id and access token to log in. The user id is set in UID, and the
token must be saved as text (without a trailing '\n') in a file {DATA_DIR}/token.

Poller must be pointed at a GitHub project (BUILD_REPO_OWNER and BUILD_REPO_NAME) containing
Actions and which produce artifacts.

The artifact ids are saved in a local file data/artifact_id.json.
"""

# pylint: disable=too-many-arguments
# pylint: disable=too-few-public-methods
# pylint: disable=too-many-instance-attributes

import abc as _abc
import fnmatch as _fnmatch
import logging as _logging
import multiprocessing as _mp
import os as _os
import sched as _sched
import shutil as _shutil
import time as _time
import zipfile as _zipfile

import requests as _requests

import fortworth as _fortworth

import poller.errors as _errors
import poller.gh_api as _gh_api



def read_token(token_file):
    """ Read token file and return token as string """
    try:
        return _fortworth.read(token_file).strip()
    except FileNotFoundError:
        raise _errors.TokenNotFoundError(token_file)



def remove(path):
    """ Remove a file or directory recursively """
    _LOG.debug("Removing '%s'", path)
    if not _fortworth.exists(path):
        return
    if _fortworth.is_dir(path):
        _shutil.rmtree(path, ignore_errors=True)
    else:
        _os.remove(path)



class Poller:
    """ Parent class for pollers that polls a GitHub repository for events or artifacts """
    def __init__(self, repo_data, poller_data):
        self._repo_data = repo_data
        self._poller_data = poller_data
        self._repo = _gh_api.GhRepository.create_repository(repo_data)
        if self._repo.is_disabled():
            raise _errors.DisabledRepoError(self._repo_data.full_name())
        self._read_data()
    def start(self, polling_interval, sch=None):
        """ Start poller """
        next_polling_interval = ERROR_POLLING_INTERVAL_SECS if self.poll() else polling_interval
        if sch is not None:
            _LOG.info('Waiting for next poll in %d secs...', next_polling_interval)
            sch.enter(next_polling_interval, 1, self.start, (polling_interval, sch, ))
    @_abc.abstractmethod
    def poll(self):
        """ Perform poll task """
    @_abc.abstractmethod
    def _read_data(self):
        """ Read data from data file into self._data """
    @_abc.abstractmethod
    def _write_data(self):
        """ Write data from self._data to data file """



class ArtifactPollerData:
    """ Collection of attributes for the artifact poller """
    def __init__(self, source_branch, build_artifact_name_list, bodega_url, stagger_url, tag,
                 polling_interval, error_polling_interval, data_dir, data_file_name,
                 last_build_cid_artifact_name):
        self.source_branch = source_branch
        self.artifact_name_list = build_artifact_name_list + [last_build_cid_artifact_name]
        self.bodega_url = bodega_url
        self.stagger_url = stagger_url
        self.tag = tag
        self.polling_interval = polling_interval
        self.error_polling_interval = error_polling_interval
        self.data_dir = data_dir
        self.data_file_name = data_file_name
        self.last_build_cid_artifact_name = last_build_cid_artifact_name



class ArtifactPoller(Poller):
    """ Poller which polls for GitHub actions artifacts at a regular interval """
    def poll(self):
        """ Perform poll task """
        try:
            self._check_services_running()
        except _errors.ErrorList as err:
            for err_item in err:
                _LOG.warning(err_item)
            return True
        _LOG.info(self._repo.to_str())
        workflow_list = self._repo.workflow_list()
        if len(workflow_list) > 0:
            _LOG.info('  %s', workflow_list.to_str())
            for wf_item in workflow_list:
                if wf_item.has_artifacts():
                    try:
                        if self._is_in_bodega(wf_item):
                            _LOG.info('    %s', wf_item.to_str())
                            self._process_artifacts(wf_item)
                        else:
                            _LOG.info('    %s - ingored, already in Bodega', wf_item.to_str())
                    except _requests.exceptions.ConnectionError:
                        _LOG.warning('    %s - Bodega not running or invalid Bodega URL %s',
                                     wf_item.to_str(), self._poller_data.bodega_url)
                else:
                    _LOG.info('    %s', wf_item.to_str())
        return False
    def _check_services_running(self):
        error_list = []
        try:
            build_data = _fortworth.BuildData(self._repo_data.name,
                                              self._poller_data.source_branch, 0, None)
            _fortworth.bodega_build_exists(build_data, self._poller_data.bodega_url)
        except _requests.exceptions.ConnectionError:
            error_list.append(_errors.ServiceConnectionError('Bodega',
                                                             self._poller_data.bodega_url))
        try:
            _fortworth.stagger_get_data(self._poller_data.stagger_url)
        except _requests.exceptions.ConnectionError:
            error_list.append(_errors.ServiceConnectionError('Stagger',
                                                             self._poller_data.stagger_url))
        if len(error_list) > 0:
            raise _errors.ErrorList(error_list)
    def _is_in_bodega(self, wf_item):
        build_data = _fortworth.BuildData(self._repo.name(), self._poller_data.source_branch,
                                          wf_item.run_number(), None)
        return not _fortworth.bodega_build_exists(build_data, self._poller_data.bodega_url)
    def _is_needed_artifact(self, artifact_name):
        for needed_artifact in self._poller_data.artifact_name_list:
            if _fnmatch.fnmatch(artifact_name, needed_artifact):
                return True
        return False
    def _process_artifacts(self, wf_item):
        first_in = True
        bodega_artifact_list = []
        bodega_temp_dir = _fortworth.make_temp_dir(suffix='-{}'.format(wf_item.run_number()))
        for artifact in wf_item:
            if first_in:
                _LOG.info('    %s', _gh_api.GhArtifactItem.hdr())
                first_in = False
            if self._is_needed_artifact(artifact.name()) and not artifact.expired():
                if not artifact.id() in self._data:
                    try:
                        downloaded_filename = artifact.download(bodega_temp_dir,
                                                                self._repo_data.auth)
                        if downloaded_filename == self._poller_data.last_build_cid_artifact_name:
                            self._process_commit_hash(bodega_temp_dir)
                        bodega_artifact_list.append((artifact, downloaded_filename))
                    except _requests.exceptions.ConnectionError:
                        _LOG.warning('    %s - ERROR: Bodega not running or invalid Bodega URL %s',
                                     artifact.to_str(), format(self._poller_data.bodega_url))
                    except Exception as err:
                        _LOG.warning('    %s - %s', artifact.to_str(), err)
                    else:
                        _LOG.info('    %s - ok', artifact.to_str())
                        self._data.add(artifact.id())
                else:
                    _LOG.info('    %s - previously downloaded', artifact.to_str())
            else:
                _LOG.info('    %s - ignored or expired', artifact.to_str())
        if len(bodega_artifact_list) > 0:
            try:
                bodega_artifact_path = self._push_to_bodega(wf_item, bodega_temp_dir)
                self._push_to_stagger(wf_item, bodega_artifact_list, bodega_artifact_path)
            except _requests.exceptions.ConnectionError:
                _LOG.error('Stagger not running or invalid Bodega URL %s',
                           self._poller_data.stagger_url)
        remove(bodega_temp_dir)
        self._write_data()
    def _process_commit_hash(self, bodega_temp_dir):
        """ Extract zipped commit-id json file into data dir """
        zip_file_name = _fortworth.join(bodega_temp_dir,
                                        self._poller_data.last_build_cid_artifact_name + '.zip')
        with _zipfile.ZipFile(zip_file_name, 'r') as zip_obj:
            zip_obj.extractall(path=self._poller_data.data_dir)
    def _push_to_bodega(self, wf_item, bodega_temp_dir):
        build_data = _fortworth.BuildData(self._repo_data.name, self._poller_data.source_branch,
                                          wf_item.run_number(), wf_item.html_url())
        _fortworth.bodega_put_build(bodega_temp_dir, build_data,
                                    service_url=self._poller_data.bodega_url)
        return _fortworth.join(self._poller_data.bodega_url, build_data.repo, build_data.branch,
                               str(build_data.id))
    def _push_to_stagger(self, workflow_metadata, bodega_artifact_list, bodega_artifact_path):
        stagger_artifact_list = {}
        for artifact, bodega_file_name in bodega_artifact_list:
            stagger_artifact_list[artifact.name()] = {
                'type': 'file',
                'update_time': _gh_api.str_time_to_milli_ts(artifact.created_at()),
                'url': _fortworth.join(bodega_artifact_path, bodega_file_name + '.zip'),
                }
        tag_data = {'update_time': _gh_api.str_time_to_milli_ts(workflow_metadata.updated_at()),
                    'build_id': workflow_metadata.run_number(),
                    'build_url': workflow_metadata.html_url(),
                    'commit_hash': None,
                    'commit_url': None,
                    'artifacts': stagger_artifact_list,
                   }
        _fortworth.stagger_put_tag(self._repo_data.name, self._poller_data.source_branch,
                                   self._poller_data.tag, tag_data,
                                   service_url=self._poller_data.stagger_url)
    def _read_data(self):
        data_file_name = _fortworth.join(self._poller_data.data_dir,
                                         self._poller_data.data_file_name)
        if _fortworth.exists(data_file_name):
            self._data = set(_fortworth.read_json(data_file_name))
        else:
            self._data = set()
    def _write_data(self):
        data_file_name = _fortworth.join(self._poller_data.data_dir,
                                         self._poller_data.data_file_name)
        _fortworth.write_json(data_file_name, list(self._data))
    @staticmethod
    def run(repo_data, poller_data):
        """ Convenience method to run the ArtifactPoller on a scheduler """
        try:
            sch = _sched.scheduler(_time.time, _time.sleep)
            artifact_poller = ArtifactPoller(repo_data, poller_data)
            sch.enter(0, 1, artifact_poller.start, (poller_data.polling_interval, sch, ))
            sch.run()
        except (_errors.PollerError) as err:
            print(err)
        except KeyboardInterrupt:
            pass



class CommitPollerData:
    """ Collection of attributes for the artifact poller """
    def __init__(self, build_repo_owner, build_repo_name, source_branch, polling_interval, data_dir,
                 last_trigger_file_name, last_build_cid_artifact_name):
        self.build_repo_owner = build_repo_owner
        self.build_repo_name = build_repo_name
        self.source_branch = source_branch
        self.polling_interval = polling_interval
        self.data_dir = data_dir
        self.last_trigger_file_name = last_trigger_file_name
        self.last_build_cid_artifact_name = last_build_cid_artifact_name



class CommitPoller(Poller):
    """ Poller which polls for new commits in a GitHub repository at a regular interval """
    def __init__(self, repo_data, poller_data):
        super().__init__(repo_data, poller_data)
        self._last_build_commit_hash = None
    def poll(self):
        """ Read commits from source repository, compare with last commit id of build """
        commits_since_build_trigger = []
        # Read commit list one page at a time
        page = 0
        hash_found = False
        _LOG.info('Reading commits from %s...', self._repo.full_name())
        while True:
            commit_list_page = self._repo.commit_list(page=page)
            page += 1
            if len(commit_list_page) == 0:
                # Raise error if no commits (page == 0)
                if page == 0:
                    raise _errors.EmptyCommitListError(self._repo)
                # Stop if no commits and page > 0
                break
            self._read_last_commit_hash()
            # If no last build hash, assume all commits are part of this build
            if self._last_build_commit_hash is None:
                commits_since_build_trigger.extend(commit_list_page.commit_list())
            # Only commits since last build commit are part of this build
            else:
                for commit in commit_list_page:
                    if commit.hash() == self._last_build_commit_hash:
                        hash_found = True
                        break
                    commits_since_build_trigger.append(commit)
            # Stop if less than a full page is received, or at 5 pages
            if hash_found or len(commit_list_page) < 50 or page >= 5:
                break
        if len(commits_since_build_trigger) > 0:
            _LOG.info('%d commits since last build trigger:', len(commits_since_build_trigger))
            for commit in commits_since_build_trigger:
                _LOG.info('  %s', commit)
            self._trigger_build()
        else:
            _LOG.info('No commits since last build trigger')
    def _read_data(self):
        data_file_name = _fortworth.join(self._poller_data.data_dir,
                                         self._poller_data.last_trigger_file_name)
        if _fortworth.exists(data_file_name):
            self._data = _fortworth.read_json(data_file_name)
            _LOG.info('Last build trigger: %s for sha %s', '<date>', '<build-sha>')
        else:
            _LOG.info('No previous build trigger found')
    def _read_last_commit_hash(self):
        """ Read the commit hash of any previous build that might have been made """
        last_commit_file_name = _fortworth.join(self._poller_data.data_dir,
                                                self._poller_data.last_build_cid_artifact_name +
                                                '.json')
        if _fortworth.exists(last_commit_file_name):
            last_build_commit = _fortworth.read_json(last_commit_file_name)
            self._last_build_commit_hash = last_build_commit['commit-hash']
            _LOG.info('Last build hash: %s', self._last_build_commit_hash)
        else:
            self._last_build_commit_hash = None
            _LOG.info('No build hash found')
    def _trigger_build(self):
        _gh_api.gh_http_post_request( \
            '{}/repos/{}/{}/dispatches'.format(self._repo_data.service_url,
                                               self._poller_data.build_repo_owner,
                                               self._poller_data.build_repo_name),
            auth=self._repo_data.auth,
            params={'accept': 'application/vnd.github.v3+json'},
            json={'event_type': 'trigger-action'})
        _LOG.info('Build triggered on %s/%s', self._poller_data.build_repo_owner,
                  self._poller_data.build_repo_name)
    def _write_data(self):
        data_file_name = _fortworth.join(self._poller_data.data_dir,
                                         self._poller_data.last_trigger_file_name)
        _fortworth.write_json(data_file_name, self._data)
    @staticmethod
    def run(repo_data, poller_data):
        """ Convenience method to run the CommitPoller on a scheduler """
        try:
            sch = _sched.scheduler(_time.time, _time.sleep)
            commit_poller = CommitPoller(repo_data, poller_data)
            sch.enter(0, 1, commit_poller.start, (poller_data.polling_interval, sch, ))
            sch.run()
        except KeyboardInterrupt:
            pass



# GitHub API service URL for all GH API requests
GITHUB_SERVICE_URL = 'https://api.github.com'

# Builder GH repository, from which artifacts are collected
# BUILD_REPO_OWNER = 'rh-messaging'
BUILD_REPO_OWNER = 'kpvdr' # Temporary, until issue with rh-messaging repo is resolved
BUILD_REPO_NAME = 'rh-qpid-proton-dist-win'

# Source code GH repository, which is built to create artifacts
SOURCE_REPO_OWNER = 'apache'
SOURCE_REPO_NAME = 'qpid-proton'
SOURCE_REPO_BRANCH = 'master'

# Local data directory
DATA_DIR = 'data'

# GitHub API authentication
GH_API_AUTH_UID = 'kpvdr'
GH_API_TOKEN_FILE_NAME = 'token' # Located in DATA_DIR

# Artifact poller data
ARTIFACT_POLLING_INTERVAL_SECS = 30 * 60
ERROR_POLLING_INTERVAL_SECS = 2 * 60
LAST_BUILD_CID_ARTIFACT_NAME = 'commit_hash'
BUILD_ARTIFACT_NAME_LIST = ['rh-qpid-proton-dist-win', 'python-*-pkgs']
ARTIFACT_POLLER_DATA_FILE_NAME = 'artifact_id.json'
TAG = 'untested'
BODEGA_URL = 'http://localhost:8081'
STAGGER_URL = 'http://localhost:8080'
ARTIFACT_POLLER_DATA = ArtifactPollerData(SOURCE_REPO_BRANCH, BUILD_ARTIFACT_NAME_LIST, BODEGA_URL,
                                          STAGGER_URL, TAG, ARTIFACT_POLLING_INTERVAL_SECS,
                                          ERROR_POLLING_INTERVAL_SECS, DATA_DIR,
                                          ARTIFACT_POLLER_DATA_FILE_NAME,
                                          LAST_BUILD_CID_ARTIFACT_NAME)

# Commit poller data
COMMIT_POLLING_INTERVAL_SECS = 30 * 60
COMMIT_DATA_FILE_NAME = 'last_trigger.json'
COMMIT_POLLER_DATA = CommitPollerData(BUILD_REPO_OWNER, BUILD_REPO_NAME, SOURCE_REPO_BRANCH,
                                      COMMIT_POLLING_INTERVAL_SECS, DATA_DIR, COMMIT_DATA_FILE_NAME,
                                      LAST_BUILD_CID_ARTIFACT_NAME)

# Logging
DEFAULT_LOG_LEVEL = _logging.INFO


if __name__ == '__main__':
    try:
        _LOG = _logging.getLogger("poller")
        _logging.basicConfig(level=DEFAULT_LOG_LEVEL)
        GH_API_AUTH = (GH_API_AUTH_UID, read_token(_fortworth.join(DATA_DIR,
                                                                   GH_API_TOKEN_FILE_NAME)))

        # Start artifact poller process
        ARTIFACT_REPO_DATA = _gh_api.GhRepositoryData(GITHUB_SERVICE_URL, BUILD_REPO_OWNER,
                                                      BUILD_REPO_NAME, GH_API_AUTH)
        ARTIFACT_POLLER_PROCESS = _mp.Process(target=ArtifactPoller.run,
                                              args=(ARTIFACT_REPO_DATA, ARTIFACT_POLLER_DATA),
                                              name='ArtifactPollerProcess')
        ARTIFACT_POLLER_PROCESS.start()

        # Give a chance for the last commit file to upload before polling for commit changes
        _time.sleep(120) # 2 min

        # Start commit poller process
        SOURCE_REPO_DATA = _gh_api.GhRepositoryData(GITHUB_SERVICE_URL, SOURCE_REPO_OWNER,
                                                    SOURCE_REPO_NAME, GH_API_AUTH)
        COMMIT_POLLER_PROCESS = _mp.Process(target=CommitPoller.run,
                                            args=(SOURCE_REPO_DATA, COMMIT_POLLER_DATA),
                                            name='CommitPollerProcess')
        COMMIT_POLLER_PROCESS.start()

        # Wait for processss to finidh
        ARTIFACT_POLLER_PROCESS.join()
        COMMIT_POLLER_PROCESS.join()
    except _errors.PollerError as err:
        _LOG.error(err)
        _fortworth.exit(1)
    except KeyboardInterrupt:
        print(' KeyboardInterrupt')
    print('done')
