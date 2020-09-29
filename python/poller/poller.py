#!/usr/bin/python3
"""
Poller for GitHub projects that contain actions and artifacts. This module polls a GitHub project
checking for new artifacts. If found, the poller updates Stagger and sends the artifacts to Bodega.

The poller requires a GitHub user id and access token to log in. The user id is set in UID, and the
token must be saved as text (without a trailing '\n') in a file {DATA_DIR}/token.

Poller must be pointed at a GitHub project (BUILD_REPO_OWNER and BUILD_REPO_NAME) containing
Actions and which produce artifacts.

The artifact ids are saved in a local file data/artifact_id.json.

Dependencies: GitHub projects:
* ssorj/bodega
* ssorj/stagger
"""

import abc as _abc
import fnmatch as _fnmatch
import logging as _logging
import multiprocessing as _mp
import os as _os
import sched as _sched
import shutil as _shutil
import time as _time

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
        self._data = set()
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
    def _read_data(self):
        if _fortworth.exists(self._poller_data.data_file):
            self._data = set(_fortworth.read_json(self._poller_data.data_file))
    def _write_data(self):
        _fortworth.write_json(self._poller_data.data_file, list(self._data))


# pylint: disable=too-many-arguments
# pylint: disable=too-few-public-methods
# pylint: disable=too-many-instance-attributes
class ArtifactPollerData:
    """ Collection of attributes for the artifact poller """
    def __init__(self, source_branch, artifact_name_list, bodega_url, stagger_url, tag,
                 polling_interval, error_polling_interval, data_file):
        self.source_branch = source_branch
        self.artifact_name_list = artifact_name_list
        self.bodega_url = bodega_url
        self.stagger_url = stagger_url
        self.tag = tag
        self.polling_interval = polling_interval
        self.error_polling_interval = error_polling_interval
        self.data_file = data_file


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
                        bodega_artifact_list.append((artifact,
                                                     artifact.download(bodega_temp_dir,
                                                                       self._repo_data.auth)))
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
                'update_time': _gh_api.str_time_to_unix_ts(artifact.created_at()),
                'url': _fortworth.join(bodega_artifact_path, bodega_file_name),
                }
        tag_data = {'update_time': _gh_api.str_time_to_unix_ts(workflow_metadata.updated_at()),
                    'build_id': workflow_metadata.run_number(),
                    'build_url': workflow_metadata.html_url(),
                    'commit_id': None,
                    'commit_url': None,
                    'artifacts': stagger_artifact_list,
                   }
        _fortworth.stagger_put_tag(self._repo_data.name, self._poller_data.source_branch,
                                   self._poller_data.tag, tag_data,
                                   service_url=self._poller_data.stagger_url)
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



# class CommitPoller(Poller):
#     """ Poller which polls for new commits in a GitHub repository at a regular interval """
#     def poll(self):
#         """ Perform poll task """
#         _LOG.info('CommitPoller.poll()')
#     @staticmethod
#     def run(repo_data, polling_interval, poller_data):
#         """ Convenience method to run the CommitPoller on a scheduler """
#         try:
#             sch = _sched.scheduler(_time.time, _time.sleep)
#             commit_poller = CommitPoller(repo_data, poller_data)
#             sch.enter(0, 1, commit_poller.start, (polling_interval, sch, ))
#             sch.run()
#         except KeyboardInterrupt:
#             pass



# GitHub API service URL for all GH API requests
GITHUB_SERVICE_URL = 'https://api.github.com'

# Builder GH repository, from which artifacts are collected
BUILD_REPO_OWNER = 'rh-messaging'
#BUILD_REPO_OWNER = 'kpvdr' # Temporary, until issue with rh-messaging repo is resolved
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
ARTIFACT_DATA_FILE = _fortworth.join(DATA_DIR, 'artifact_id.json')
ARTIFACT_POLLING_INTERVAL_SECS = 1 * 60
ERROR_POLLING_INTERVAL_SECS = 10 # Retry interval if Bodega/Stagger is down
ARTIFACT_NAME_LIST = ['rh-qpid-proton-dist-win', 'python-*-pkgs']
TAG = 'untested' # can be passed on cmd-line later as needed
BODEGA_URL = 'http://localhost:8081'
STAGGER_URL = 'http://localhost:8080'
ARTIFACT_POLLER_DATA = ArtifactPollerData(SOURCE_REPO_BRANCH, ARTIFACT_NAME_LIST, BODEGA_URL,
                                          STAGGER_URL, TAG, ARTIFACT_POLLING_INTERVAL_SECS,
                                          ERROR_POLLING_INTERVAL_SECS, ARTIFACT_DATA_FILE)

# Commit poller data
COMMIT_DATA_FILE = _fortworth.join(DATA_DIR, 'src_commits.json')
COMMIT_POLLING_INTERVAL_SECS = 1 * 60

# Logging
DEFAULT_LOG_LEVEL = _logging.INFO


if __name__ == '__main__':
    try:
        _LOG = _logging.getLogger("poller")
        _logging.basicConfig(level=DEFAULT_LOG_LEVEL)

        # Start artifact poller process
        GH_API_AUTH = (GH_API_AUTH_UID, read_token(_fortworth.join(DATA_DIR,
                                                                   GH_API_TOKEN_FILE_NAME)))
        ARTIFACT_REPO_DATA = _gh_api.GhRepositoryData(GITHUB_SERVICE_URL, BUILD_REPO_OWNER,
                                                      BUILD_REPO_NAME, GH_API_AUTH)
        ARTIFACT_POLLER_PROCESS = _mp.Process(target=ArtifactPoller.run,
                                              args=(ARTIFACT_REPO_DATA, ARTIFACT_POLLER_DATA),
                                              name='ArtifactPollerProcess')
        ARTIFACT_POLLER_PROCESS.start()

        # Start commit poller process
        # SOURCE_REPO_DATA = _gh_api.GhRepositoryData(GITHUB_SERVICE_URL, SOURCE_REPO_OWNER,
        #                                             SOURCE_REPO_NAME, GH_API_AUTH)
        # COMMIT_POLLER_PROCESS = _mp.Process(target=CommitPoller.run,
        #                                     args=(SOURCE_REPO_DATA, COMMIT_POLLING_INTERVAL_SECS),
        #                                     name='CommitPollerProcess')
        # COMMIT_POLLER_PROCESS.start()
    except _errors.PollerError as err:
        _LOG.error(err)
        _fortworth.exit(1)
    print('done')
