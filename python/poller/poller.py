#!/usr/bin/python3
"""
Poller for GitHub projects that contain actions and artifacts. This module polls a GitHub project
checking for new artifacts. If found, the poller updates Stagger and sends the artifacts to Bodega.

Dependencies: GitHub projects:
* ssorj/bodega
* ssorj/stagger
"""

import fnmatch
import json
import os.path
import sched
import sys
import time
import requests as _requests

import fortworth as _fortworth


class PollerError(RuntimeError):
    """ Parent class for all poller errors """


class ArtifactIdNotFound(PollerError):
    """ Error when artifact id cannot be found """

    def __init__(self, artifact_id):
        super().__init__('ArtifactIdNotFound: Id %d not found in list of available artifacts' %
                         artifact_id)


class ContentTypeError(PollerError):
    """ Error when the returned information is not of type application/json """

    def __init__(self, response):
        super().__init__('ContentTypeError: GET %s returned unexpected content-type %s' % (
            response.url[0: response.url.find('?')],
            response.headers['content-type']))
        self.response = response


class DisabledRepoError(PollerError):
    """ Error when the GH project is disabled """

    def __init__(self, repo_full_name):
        super().__init__('DisabledRepoError: Repository %s is disabled' % repo_full_name)


class StatusError(PollerError):
    """ Error when a GET request returns anything other than 200 (ok) """

    def __init__(self, response):
        super().__init__('StatusError: GET %s returned status %d (%s)' % (
            response.url[0: response.url.find('?')],
            response.status_code, response.reason))
        self.response = response


class TokenNotFoundError(PollerError):
    """ Error if GitHub token not found """

    def __init__(self, token_file_name):
        super().__init__('TokenNotFoundError: GitHub token file not found at %s' % token_file_name)


class GitHubRepo:
    """ URL and auth details for a GitHub repo """

    def __init__(self, service_url, repo_full_name, user_id, token_file_name, branch):
        self._service_url = service_url
        self._repo_full_name = repo_full_name
        self._user_id = user_id
        self._token_file_name = token_file_name
        self._token = GitHubRepo._get_github_token(token_file_name)
        self._branch = branch

    def get_service_url(self):
        """ Get repo service URL """
        return self._service_url

    def get_repo_full_name(self):
        """ Get repo full name """
        return self._repo_full_name

    def get_auth(self):
        """ Get repo authorization as a tuple (uid, token) """
        return (self._user_id, self._token)

    def get_branch(self):
        """ Get repo branch """
        return self._branch

    @staticmethod
    def _get_github_token(token_file_name):
        token = None
        if os.path.exists(token_file_name):
            with open(token_file_name) as token_file:
                token = token_file.read()[:-1] # strip trailing /n
        if token is None:
            raise TokenNotFoundError(token_file_name)
        return token


class GitHubApiCall:
    """ Parent class for all GitHub REST API calls """

    def __init__(self, gh_repo):
        self._gh_repo = gh_repo

    @staticmethod
    def _repo_request(gh_service_url, request_url, auth=None, params=None):
        resp = _requests.get(gh_service_url + request_url, auth=auth, params=params)
        GitHubApiCall._check_ok(resp)
        GitHubApiCall._check_content_type(resp, 'application/json')
        return resp.json()

    @staticmethod
    def _check_content_type(response, content_type):
        if content_type not in response.headers['content-type']:
            raise ContentTypeError(response)

    @staticmethod
    def _check_ok(response):
        if response.status_code != 200:
            raise StatusError(response)


class GitHubRepoMetadata(GitHubApiCall):
    """ GitHub repository metadata as retrieved from GitHub REST API """

    def __init__(self, gh_repo):
        super().__init__(gh_repo)
        self._repo_metadata = self._repo_request(self._gh_repo.get_service_url(),
                                                 'repos/%s' % self._gh_repo.get_repo_full_name(),
                                                 auth=self._gh_repo.get_auth(),
                                                 params={'accept': 'application/vnd.github.v3+json',
                                                         'per_page': 50})

    def is_disabled(self):
        """ Return True if repository is disabled, False otherwise """
        return self._repo_metadata['disabled']

    def get_full_name(self):
        """ Return the full name of the repository """
        return self._repo_metadata['full_name']

    def get_description(self):
        """ Return the repository desctription """
        return self._repo_metadata['description']

    def get_url(self):
        """ Return the repository URL """
        return self._repo_metadata['url']

    def get_metadata(self, key=None):
        """ Convenience method to return the metadata for a given key """
        if key is None:
            return self._repo_metadata
        return self._repo_metadata[key]

    def get_metadata_as_str(self, key=None, sort_keys=True, indent=4):
        """ Convenience method to return stringified metadata """
        if key is None:
            return json.dumps(self._repo_metadata, sort_keys=sort_keys, indent=indent)
        return json.dumps(self._repo_metadata[key], sort_keys=sort_keys, indent=indent)


class GitHubArtifactMetadata(GitHubApiCall):
    """ GitHub action artifacts, as retrieved from GH REST API """

    def __init__(self, gh_repo):
        super().__init__(gh_repo)
        self.artifact_metadata = \
            self._repo_request(self._gh_repo.get_service_url(),
                               'repos/%s/actions/artifacts' % self._gh_repo.get_repo_full_name(),
                               auth=self._gh_repo.get_auth(),
                               params={'accept': 'application/vnd.github.v3+json', 'per_page': 50})

    def get_num_artifacts(self):
        """ Return the total number of artifacts avaliable """
        return self.artifact_metadata['total_count']

    def get_artifact_list(self, name=None):
        """ Return a list of artifact metadata in a list """
        if name is None:
            return self.artifact_metadata['artifacts']
        artifact_list = []
        for artifact in self.artifact_metadata['artifacts']:
            if artifact[name] == name:
                artifact_list.append(artifact)
        return artifact_list

    def get_artifact_map(self):
        """
        Return a map with the artifact name as the key, the values being a list of artifact metadata
        matching the name
        """
        artifact_map = {}
        for artifact in self.artifact_metadata['artifacts']:
            if artifact['name'] in artifact_map:
                artifact_map[artifact['name']].append(artifact)
            else:
                artifact_map[artifact['name']] = [artifact]
        return artifact_map


    def get_artifact_by_id(self, artifact_id, data_dir):
        """ Download artifact by its build id """
        for artifact in self.artifact_metadata['artifacts']:
            if artifact['id'] == artifact_id:
                return self._download_artifact(artifact, data_dir)
        raise ArtifactIdNotFound(artifact_id)

    def _download_artifact(self, artifact, data_dir):
        download_url = artifact['archive_download_url']
        with _requests.get(download_url, stream=True, auth=self._gh_repo.get_auth()) as req:
            self._check_ok(req)
            artifact_file_name = os.path.join(data_dir, artifact['name'] + '.zip')
            with open(artifact_file_name, 'wb') as artifact_file:
                for chunk in req.iter_content(chunk_size=65536):
                    artifact_file.write(chunk)
            return artifact_file_name
        return None


class PollerApp:
    """ Poller which polls for GitHub actions artifacts at a regular interval """

    def __init__(self, gh_repo, data_dir, poll_interval_secs, artifact_name_list):
        self._gh_repo = gh_repo
        self._data_dir = data_dir
        self._poll_interval_secs = poll_interval_secs
        self._artifact_name_list = artifact_name_list
        self._build_id_log_file_name = 'build_id.json'
        self._build_id_list = set()
        self._read_build_id_log()

    def start(self, sch=None):
        """ Start poller """
        try:
            self._poll_for_artifacts()
        except PollerError as err:
            print(err)
            sys.exit(1)
        if sch is not None:
            sch.enter(self._poll_interval_secs, 1, self.start, (sch, ))

    def _poll_for_artifacts(self):
        repo_metadata = GitHubRepoMetadata(self._gh_repo)
        if repo_metadata.is_disabled():
            raise DisabledRepoError(repo_metadata.get_full_name())
        artifact_metadata = GitHubArtifactMetadata(self._gh_repo)
        print('Found GitHub repo "%s" containing %d total artifacts:' %
              (repo_metadata.get_full_name(), artifact_metadata.get_num_artifacts()))
        first_in = True
        count = {'ignored': 0, 'processed': 0, 'previous': 0, 'failed': 0}
        for artifact in artifact_metadata.get_artifact_list():
            if self._is_needed_artifact(artifact['name']):
                artifact_id = artifact['id']
                if not artifact['expired'] and not artifact_id in self._build_id_list:
                    if first_in:
                        print('  %10s %12s %22s  %s' % ('id', 'size', 'created', 'name'))
                        first_in = False
                    print('  %10d %12d %22s  %s ' % (artifact['id'], artifact['size_in_bytes'],
                                                     artifact['created_at'], artifact['name']),
                          end='\n', flush=True)
                    # try:
                    #     self._handle_artifact(artifact_metadata, artifact)
                    # except Exception as exc:
                    #     print(' - %s' % exc)
                    #     count['failed'] += 1
                    # else:
                    #     print(' - ok')
                    #     self._build_id_list.add(artifact_id)
                    #     count['processed'] += 1
                    self._handle_artifact(artifact_metadata, artifact)
                    print(' - ok')
                    self._build_id_list.add(artifact_id)
                    count['processed'] += 1
                else:
                    count['previous'] += 1
            else:
                count['ignored'] += 1
        if count['processed'] > 0:
            print('%2d artifacts processed' % count['processed'])
        if count['failed'] > 0:
            print('%2d artifact downloads failed' % count['failed'])
        if count['previous'] > 0:
            print('%2d artifacts previously processed' % count['previous'])
        if count['ignored'] > 0:
            print('%2d artifacts ignored' % count['ignored'])
        self._write_build_id_log()

    def _handle_artifact(self, artifact_metadata, artifact):
        #artifact_file = artifact_metadata.get_artifact_by_id(artifact['id'], self._data_dir)
        build_data = _fortworth.BuildData(self._gh_repo.get_repo_full_name(),
                                          self._gh_repo.get_branch(),
                                          artifact['id'],
                                          artifact['url'])
        print('DEBUG: build_data=%s' % build_data)
        if not _fortworth.bodega_build_exists(build_data, BODEGA_URL):
            print('DEBUG: bodega_build_exists() returned False')
            _fortworth.bodega_put_build(os.path.join('data', '%s.zip' % artifact['name']), build_data, BODEGA_URL)

    def _is_needed_artifact(self, artifact_name):
        for needed_artifact in self._artifact_name_list:
            if fnmatch.fnmatch(artifact_name, needed_artifact):
                return True
        return False

    def _read_build_id_log(self):
        full_build_id_log_path = os.path.join(self._data_dir, self._build_id_log_file_name)
        if os.path.exists(full_build_id_log_path):
            with open(full_build_id_log_path) as fin:
                self._build_id_list = set(json.loads(fin.read()))

    def _write_build_id_log(self):
        with open(os.path.join(self._data_dir, self._build_id_log_file_name), 'w') as out:
            out.write(json.dumps(list(self._build_id_list)))


GITHUB_SERVICE_URL = 'https://api.github.com/'
REPO_OWNER = 'kpvdr'
REPO_NAME = 'rh-qpid-proton-dist-win'
BRANCH = 'master'
UID = 'kpvdr'
DATA_DIR = 'data'
TOKEN_FILE = 'token'
POLLING_INTERVAL_SECS = 30
ARTIFACT_NAME_LIST = ['rh-qpid-proton-dist-win', 'python-*-pkgs']

STAGGER_URL = 'http://localhost:8080'
BODEGA_URL = 'http://localhost:8081'

if __name__ == '__main__':
    try:
        REPO_FULL_NAME = '%s/%s' % (REPO_OWNER, REPO_NAME)
        REPO = GitHubRepo(GITHUB_SERVICE_URL, REPO_FULL_NAME, UID,
                          os.path.join(DATA_DIR, TOKEN_FILE), BRANCH)
        SCHED = sched.scheduler(time.time, time.sleep)
        POLLER = PollerApp(REPO, DATA_DIR, POLLING_INTERVAL_SECS, ARTIFACT_NAME_LIST)
        SCHED.enter(0, 1, POLLER.start, (SCHED, ))
        SCHED.run()
    except TokenNotFoundError as tnf:
        print(tnf)
        sys.exit(1)
    except KeyboardInterrupt:
        print(' KeyboardInterrupt')
    print('done')
