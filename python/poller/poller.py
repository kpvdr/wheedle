#!/usr/bin/python3
"""
Poller for GitHub projects that contain actions and artifacts. This module polls a GitHub
project checking for new artifacts. If found, the poller updates Stagger and sends the
artifacts to Bodega.
"""

import json
import os.path
import sched
import sys
import time

import requests as _requests


class PollerError(RuntimeError):
    """ Parent class for all poller errors """


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


class GitHubRestCall:
    """ Parent class for all GitHub REST API calls """

    @staticmethod
    def _check_ok(response):
        if response.status_code != 200:
            raise StatusError(response)


class GitHubRepo(GitHubRestCall):
    """ GitHub repository metadata as retrieved from GitHub REST API """

    def __init__(self, gh_service_url, gh_repo_name, auth=None):
        self._repo_metadata = self._repo_request(gh_service_url,
                                                 'repos/%s' % gh_repo_name,
                                                 auth=auth,
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

    @staticmethod
    def _repo_request(gh_service_url, request_url, auth=None, params=None):
        resp = _requests.get(gh_service_url + request_url, auth=auth, params=params)
        GitHubRepo._check_ok(resp)
        GitHubRepo._check_content_type(resp, 'application/json')
        return resp.json()

    @staticmethod
    def _check_content_type(response, content_type):
        if content_type not in response.headers['content-type']:
            raise ContentTypeError(response)


class PollerApp:
    """ Poller which polls for GitHub actions artifacts at a regular interval """

    def __init__(self, gh_service_url, gh_repo_name, uid, token_file_name, poll_interval_secs):
        self._gh_service_url = gh_service_url
        self._gh_repo_name = gh_repo_name
        self._auth = (uid, PollerApp._get_github_token(token_file_name))
        self._poll_interval_secs = poll_interval_secs
        print('DEBUG: auth=%s' % (self._auth,))

    def start(self, sch=None):
        """ Start poller """
        try:
            self._poll_for_artifacts()
        except PollerError as exc:
            print(exc)
            sys.exit(1)
        if sch is not None:
            sch.enter(self._poll_interval_secs, 1, self.start, (sch, ))

    def _poll_for_artifacts(self):
        print('_poll_for_artifacts():')
        repo_metadata = GitHubRepo(self._gh_service_url, self._gh_repo_name, auth=self._auth)
        print(repo_metadata.get_metadata_as_str())
        if repo_metadata.is_disabled():
            raise DisabledRepoError(repo_metadata.get_full_name())

    @staticmethod
    def _get_github_token(token_file_name):
        token = None
        if os.path.exists(token_file_name):
            with open(token_file_name) as token_file:
                token = token_file.read()[:-1] # strip trailing /n
        if token is None:
            raise TokenNotFoundError(token_file_name)
        return token


GITHUB_SERVICE_URL = 'https://api.github.com/'
REPO_OWNER = 'kpvdr'
REPO_NAME = 'rh-qpid-proton-dist-win'
UID = 'kpvdr'
DATA_DIR = 'data'
TOKEN_FILE = 'token'
POLLING_INTERVAL_SECS = 30

if __name__ == '__main__':
    SCHED = sched.scheduler(time.time, time.sleep)
    POLLER = PollerApp(GITHUB_SERVICE_URL,
                       REPO_OWNER + '/' + REPO_NAME,
                       UID,
                       os.path.join(DATA_DIR, TOKEN_FILE),
                       POLLING_INTERVAL_SECS)
    try:
        SCHED.enter(0, 1, POLLER.start, (SCHED, ))
        SCHED.run()
    except KeyboardInterrupt:
        print(' KeyboardInterrupt')
    print('done')
