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

import datetime as _datetime
import fnmatch as _fnmatch
import logging as _logging
import os as _os
import sched as _sched
import shutil as _shutil
import time as _time
import requests as _requests
import fortworth as _fortworth



class PollerError(RuntimeError):
    """ Parent class for all poller errors """



class ArtifactIdNotFound(PollerError):
    """ Error when artifact id cannot be found """

    def __init__(self, artifact_id):
        super().__init__('ArtifactIdNotFound: Id %d not found in list of available artifacts' %
                         artifact_id)


class ServiceConnectionError(PollerError):
    """ Error when the connection to a service fails """

    def __init__(self, service_name, service_url):
        super().__init__('ServiceConnectionError: {0} not running or invalid {0} URL {1}'.format( \
            service_name, service_url))



class ContentTypeError(PollerError):
    """ Error when the returned information is not of type application/json """

    def __init__(self, response):
        super().__init__('ContentTypeError: GET {} returned unexpected content-type {}'.format( \
            response.url[0: response.url.find('?')],
            response.headers['content-type']))
        self.response = response



class DisabledRepoError(PollerError):
    """ Error when the GH project is disabled """

    def __init__(self, repo_full_name):
        super().__init__('DisabledRepoError: Repository {} is disabled'.format(repo_full_name))


class ErrorList(PollerError):
    """ Allows multiple exception objects to be raised together """

    def __init__(self, error_list):
        self._error_list = error_list
        err_msg = ''
        if len(error_list) > 0:
            first = True
            for err in error_list:
                if not first:
                    err_msg += '\n'
                err_msg += str(err)
                first = False
        else:
            err_msg = '[]'
        super().__init__(err_msg)

    def __iter__(self):
        return self._error_list.__iter__()


class HttpError(PollerError):
    """ Error when a HTTP GET request returns anything other than 200 (ok) """

    def __init__(self, response):
        super().__init__('HttpError: GET {} returned status {} ({})'.format( \
            response.url[0: response.url.find('?')],
            response.status_code,
            response.reason))
        self.response = response



class TokenNotFoundError(PollerError):
    """ Error if GitHub token not found """

    def __init__(self, token_file_name):
        super().__init__('TokenNotFoundError: GitHub token file not found at {}'.format( \
            token_file_name))



def check_ok(response):
    """ Check HTTP response is ok (200) """
    if response.status_code != 200:
        raise HttpError(response)



def gh_api_request(url, auth=None, params=None, content_type='json'):
    """ Send HTTP request to GitHub """
    resp = _requests.get(url, auth=auth, params=params)
    check_ok(resp)
    if content_type not in resp.headers['content-type']:
        raise ContentTypeError(resp)
    return resp.json()



def remove(path):
    """ Remove a file or directory recursively """
    _LOG.debug("Removing '%s'", path)
    if not _fortworth.exists(path):
        return
    if _fortworth.is_dir(path):
        _shutil.rmtree(path, ignore_errors=True)
    else:
        _os.remove(path)



def str_time_to_unix_ts(str_time):
    """ Convert timestamp in ISO 8601 to unix timestamp """
    return _time.mktime(_datetime.datetime.strptime(str_time, '%Y-%m-%dT%H:%M:%S%z').timetuple())



class MetadataMap:
    """ Parent class for mapped metadata """

    def __init__(self, metadata):
        self._metadata = metadata

    def get(self, key=None):
        """ Convenience method to return the metadata for a given key """
        if key is None:
            return self._metadata
        return self._metadata[key]

    def get_as_json(self, key=None):
        """ Convenience method to return stringified metadata """
        if key is None:
            return _fortworth.emit_json(self._metadata)
        return _fortworth.emit_json(self._metadata[key])



class GhRepository(MetadataMap):
    """ GitHub repository metadata as retrieved from GitHub REST API """

    def __init__(self, service_url, repo_owner, repo_name, user_id, token_file_name):
        self._service_url = service_url
        self._repo_owner = repo_owner
        self._repo_name = repo_name
        self._user_id = user_id
        self._token_file_name = token_file_name
        self._token = GhRepository._get_github_token(token_file_name)
        super().__init__( \
            gh_api_request('{}/repos/{}/{}'.format(service_url, repo_owner, repo_name),
                           auth=self.auth(),
                           params={'accept': 'application/vnd.github.v3+json',
                                   'per_page': 50}))
        if self.is_disabled():
            raise DisabledRepoError(self.full_name())

    def auth(self):
        """ Get repo authorization as a tuple (uid, token) """
        return (self._user_id, self._token)

    def full_name(self):
        """ Get repo full name """
        return '%s/%s' % (self._repo_owner, self._repo_name)

    def is_disabled(self):
        """ Return True if repository is disabled, False otherwise """
        return self._metadata['disabled']

    def name(self):
        """ Get repo name """
        return self._repo_name

    def owner(self):
        """ Get repo owner """
        return self._repo_owner

    def service_url(self):
        """ Get repo service URL """
        return self._service_url

    def workflow_list(self):
        """ Get workflow list """
        return GhWorkflowList(self)

    @staticmethod
    def _get_github_token(token_file_name):
        token = None
        if _fortworth.exists(token_file_name):
            with open(token_file_name) as token_file:
                token = token_file.read()[:-1] # strip trailing /n
        if token is None:
            raise TokenNotFoundError(token_file_name)
        return token



class GhWorkflowItem(MetadataMap):
    """ GitHub workflow item """

    def __init__(self, build_repo, wf_item):
        super().__init__(wf_item)
        self._build_repo = build_repo
        self._artifact_list = GhArtifactList(build_repo, self._metadata['artifacts_url'])

    def artifact_list(self):
        """ Return a GhArtifactList object for this workflow item """
        return self._artifact_list

    def commit_id(self):
        """ Get head commit id """
        return self._metadata['head_commit']['id']

    def commit_msg(self):
        """ Get head commit message """
        return self._metadata['head_commit']['message']

    def conclusion(self):
        """ Get workflow conclusion, can be one of 'success', 'failure', 'neutral', 'cancelled',
            'skipped', 'timed_out', or 'action_required'. """
        return self._metadata['conclusion']

    def has_artifacts(self):
        """ Return True if workflow has completed sucessfully and has artifacts """
        return self.status() == 'completed' and \
            self.conclusion() == 'success' and \
            len(self._artifact_list) > 0

    def html_url(self):
        """ Get HTML URL for this workflow """
        return self._metadata['html_url']

    def run_number(self):
        """ Get build number """
        return self._metadata['run_number']

    def status(self):
        """ Get workflow status, can be one of 'queued', 'in_progress', or 'completed' """
        return self._metadata['status']

    def updated_at(self):
        """ Get string timestamp of last update """
        return self._metadata['updated_at']

    def __iter__(self):
        return self._artifact_list.__iter__()

    def __lt__(self, other):
        return str_time_to_unix_ts(self.updated_at()) < str_time_to_unix_ts(other.updated_at())

    def __repr__(self):
        num_artifacts = len(self._artifact_list)
        if num_artifacts == 0:
            suffix = 's'
        elif num_artifacts == 1:
            suffix = ':'
        else:
            suffix = 's:'
        return 'Run #{} updated {}: {}:{} containing {} artifact{}'.format( \
            self.run_number(), self.updated_at(), self.status(), self.conclusion(),
            len(self._artifact_list), suffix)



class GhWorkflowList(MetadataMap):
    """ List of GitHub workflows, as retrieved from GitHub REST API """

    def __init__(self, repo):
        super().__init__(gh_api_request( \
            '{}/repos/{}/{}/actions/runs'.format(repo.service_url(), repo.owner(), repo.name()),
            auth=repo.auth(),
            params={'accept': 'application/vnd.github.v3+json',
                    'per_page': 50}))
        self._wf_item_list = []
        for wf_item in self._metadata['workflow_runs']:
            self._wf_item_list.append(GhWorkflowItem(repo, wf_item))

    def wf_list(self):
        """ Get list of workflow items """
        return sorted(self._wf_item_list)

    def __iter__(self):
        return self._wf_item_list.sort().__iter__()

    def __len__(self):
        return len(self._wf_item_list)



class GhArtifactItem(MetadataMap):
    """ Single artifact metadata """

    def created_at(self):
        """ Return artifact created date/time in ISO 8601 format """
        return self._metadata['created_at']

    def download(self, data_dir, auth):
        """ Download artifact to data_dir """
        with _requests.get(self._download_url(), stream=True, auth=auth) as req:
            check_ok(req)
            artifact_file_name = _fortworth.join(data_dir, self.name() + '.zip')
            with open(artifact_file_name, 'wb') as artifact_file:
                for chunk in req.iter_content(chunk_size=MAX_DOWNLOAD_CHUNK_SIZE):
                    artifact_file.write(chunk)
            return artifact_file_name
        return None

    def _download_url(self):
        return self._metadata['archive_download_url']

    def expired(self):
        """ Return True if artifact has expired, False if not """
        return self._metadata['expired']

    @staticmethod
    def hdr():
        """ Return a header to match the output of __repr__() """
        return '{:>10}  {:>12}  {:>22}  {:<25}'.format('id', 'size', 'created', 'name')

    def id(self):
        """ Return artifact id """
        return self._metadata['id']

    def name(self):
        """ Return artifact name """
        return self._metadata['name']

    def size_in_bytes(self):
        """ Return artifact size in bytes """
        return self._metadata['size_in_bytes']

    def url(self):
        """ Return GitHub artifact url """
        return self._metadata['url']

    def __lt__(self, other):
        return str_time_to_unix_ts(self.created_at()) < str_time_to_unix_ts(other.created_at())

    def __repr__(self):
        return '{:>10}  {:>12}  {:>22}  {:<25}'.format(self.id(), self.size_in_bytes(),
                                                       self.created_at(), self.name())



class GhArtifactList(MetadataMap):
    """ List of GitHub artifacts associated with a workflow """

    def __init__(self, repo, artifacts_url):
        super().__init__(gh_api_request(artifacts_url,
                                        auth=repo.auth(),
                                        params={'accept': 'application/vnd.github.v3+json',
                                                'per_page': 50}))
        self._artifact_item_list = []
        for artifact in self._metadata['artifacts']:
            self._artifact_item_list.append(GhArtifactItem(artifact))

    def artifact_item_list(self):
        """ Get list of workflow items """
        return self._artifact_item_list

    def __iter__(self):
        return self._artifact_item_list.__iter__()

    def __len__(self):
        return len(self._artifact_item_list)



class PollerApp:
    """ Poller which polls for GitHub actions artifacts at a regular interval """

    def __init__(self, build_repo, data_dir, poll_interval_secs, artifact_name_list, source_branch,
                 tag, bodega_url, stagger_url):
        self._build_repo = build_repo
        self._data_dir = data_dir
        self._poll_interval_secs = poll_interval_secs
        self._artifact_name_list = artifact_name_list
        self._source_branch = source_branch
        self._tag = tag
        self._bodega_url = bodega_url
        self._stagger_url = stagger_url
        self._artifact_id_log_file_name = 'artifact_id.json'
        self._artifact_id_list = set()
        self._iterations = 0
        self._read_build_id_log()

    def iterations(self):
        """ Return number of poll iterations """
        return self._iterations

    def start(self, sch=None):
        """ Start poller """
        _logging.basicConfig(level=_logging.INFO)
        self._iterations += 1
        try:
            self._check_services_running()
            self._poll_for_artifacts()
        except ErrorList as err:
            for err_item in err:
                _LOG.warning(err_item)
        except PollerError as err:
            _LOG.error(err)
            _fortworth.exit(1)
        if sch is not None:
            _LOG.info('Waiting for next poll in %d secs...', self._poll_interval_secs)
            sch.enter(self._poll_interval_secs, 1, self.start, (sch, ))

    def _check_services_running(self):
        error_list = []
        try:
            build_data = _fortworth.BuildData(self._build_repo.name(), self._source_branch, 0, None)
            _fortworth.bodega_build_exists(build_data, self._bodega_url)
        except _requests.exceptions.ConnectionError:
            error_list.append(ServiceConnectionError('Bodega', self._bodega_url))
        try:
            _fortworth.stagger_get_data(self._stagger_url)
        except _requests.exceptions.ConnectionError:
            error_list.append(ServiceConnectionError('Stagger', self._stagger_url))
        if len(error_list) > 0:
            raise ErrorList(error_list)

    def _is_in_bodega(self, wf_item):
        build_data = _fortworth.BuildData(self._build_repo.name(), self._source_branch,
                                          wf_item.run_number(), None)
        return not _fortworth.bodega_build_exists(build_data, self._bodega_url)

    def _is_needed_artifact(self, artifact_name):
        for needed_artifact in self._artifact_name_list:
            if _fnmatch.fnmatch(artifact_name, needed_artifact):
                return True
        return False

    def _poll_for_artifacts(self):
        _LOG.info('Iteration %d: Found repository %s:', self._iterations, self._build_repo.name())
        workflow_list = self._build_repo.workflow_list()
        if len(workflow_list) > 0:
            _LOG.info('  Found %d workflow item(s):', len(workflow_list))
            for wf_item in workflow_list.wf_list():
                if wf_item.has_artifacts():
                    try:
                        if self._is_in_bodega(wf_item):
                            _LOG.info('    %s', wf_item)
                            self._process_artifacts(wf_item)
                        else:
                            _LOG.info('    %s - ingored, already in Bodega', wf_item)
                    except _requests.exceptions.ConnectionError:
                        _LOG.warning('    %s - ERROR: Bodega not running or invalid Bodega URL %s',
                                     wf_item, format(self._bodega_url))
                else:
                    _LOG.info('    %s', wf_item)
        _LOG.info('Iteration %d: Artifact search on repository %s complete', self._iterations,
                  self._build_repo.name())

    def _process_artifacts(self, wf_item):
        first_in = True
        bodega_artifact_list = []
        bodega_temp_dir = _fortworth.make_temp_dir(suffix='-{}'.format(wf_item.run_number()))
        for artifact in wf_item:
            if first_in:
                _LOG.info('    %s', GhArtifactItem.hdr())
                first_in = False
            if self._is_needed_artifact(artifact.name()) and not artifact.expired():
                if not artifact.id() in self._artifact_id_list:
                    try:
                        bodega_artifact_url = artifact.download(bodega_temp_dir,
                                                                self._build_repo.auth())
                        if bodega_artifact_url is not None:
                            bodega_artifact_list.append((artifact, bodega_artifact_url))
                    except _requests.exceptions.ConnectionError:
                        _LOG.warning('    %s - ERROR: Bodega not running or invalid Bodega URL %s',
                                     artifact, format(self._bodega_url))
                    except Exception as exc:
                        _LOG.warning('    %s - %s', artifact, exc)
                    else:
                        _LOG.info('    %s - ok', artifact)
                        self._artifact_id_list.add(artifact.id())
                else:
                    _LOG.info('    %s - previously downloaded', artifact)
            else:
                _LOG.info('    %s - ignored or expired', artifact)
        if len(bodega_artifact_list) > 0:
            try:
                self._push_to_bodega(wf_item, bodega_temp_dir)
                self._push_to_stagger(wf_item, bodega_artifact_list)
            except _requests.exceptions.ConnectionError:
                _LOG.error('Stagger not running or invalid Bodega URL %s', self._stagger_url)
        remove(bodega_temp_dir)
        self._write_build_id_log()

    def _push_to_bodega(self, wf_item, bodega_temp_dir):
        build_data = _fortworth.BuildData(self._build_repo.name(), self._source_branch,
                                          wf_item.run_number(), wf_item.html_url())
        _fortworth.bodega_put_build(bodega_temp_dir, build_data, service_url=self._bodega_url)

    def _push_to_stagger(self, workflow_metadata, bodega_artifact_list):
        stagger_artifact_list = {}
        for artifact, bodega_url in bodega_artifact_list:
            stagger_artifact_list[artifact.name()] = {
                'type': 'file',
                'update_time': str_time_to_unix_ts(artifact.created_at()),
                'url': bodega_url,
                }
        tag_data = {'update_time': str_time_to_unix_ts(workflow_metadata.updated_at()),
                    'build_id': workflow_metadata.run_number(),
                    'build_url': workflow_metadata.html_url(),
                    'commit_id': None,
                    'commit_url': None,
                    'artifacts': stagger_artifact_list,
                   }
        _fortworth.stagger_put_tag(self._build_repo.name(), self._source_branch, self._tag,
                                   tag_data, service_url=self._stagger_url)

    def _read_build_id_log(self):
        full_build_id_log_path = _fortworth.join(self._data_dir, self._artifact_id_log_file_name)
        if _fortworth.exists(full_build_id_log_path):
            self._artifact_id_list = set(_fortworth.read_json(full_build_id_log_path))

    def _write_build_id_log(self):
        _fortworth.write_json(_fortworth.join(self._data_dir, self._artifact_id_log_file_name),
                              list(self._artifact_id_list))



GITHUB_SERVICE_URL = 'https://api.github.com'

# Builder GH repository
#BUILD_REPO_OWNER = 'rh-messaging'
BUILD_REPO_OWNER = 'kpvdr' # Temporary, until issue with rh-messaging repo is resolved
BUILD_REPO_NAME = 'rh-qpid-proton-dist-win'

# Source code GH repository
SOURCE_REPO_BRANCH = 'master'

UID = 'kpvdr'
DATA_DIR = 'data'
TAG = 'untested' # can be passed on cmd-line later as needed

TOKEN_FILE = 'token'
POLLING_INTERVAL_SECS = 1 * 60
ARTIFACT_NAME_LIST = ['rh-qpid-proton-dist-win', 'python-*-pkgs']
MAX_DOWNLOAD_CHUNK_SIZE = 65536

STAGGER_URL = 'http://localhost:8080'
BODEGA_URL = 'http://localhost:8081'

_LOG = _logging.getLogger("poller")

if __name__ == '__main__':
    try:
        BUILD_REPO = GhRepository(GITHUB_SERVICE_URL, BUILD_REPO_OWNER, BUILD_REPO_NAME, UID,
                                  _fortworth.join(DATA_DIR, TOKEN_FILE))
        SCHED = _sched.scheduler(_time.time, _time.sleep)
        POLLER = PollerApp(BUILD_REPO, DATA_DIR, POLLING_INTERVAL_SECS, ARTIFACT_NAME_LIST,
                           SOURCE_REPO_BRANCH, TAG, BODEGA_URL, STAGGER_URL)
        SCHED.enter(0, 1, POLLER.start, (SCHED, ))
        SCHED.run()
    except TokenNotFoundError as tnf:
        _LOG.critical(tnf)
        _fortworth.exit(1)
    except KeyboardInterrupt:
        _LOG.info(' KeyboardInterrupt')
    print('done')
