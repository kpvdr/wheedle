#!/usr/bin/python3
"""
Poller for GitHub projects that contain actions and artifacts. This module polls a GitHub
project checking for new artifacts. If found, the poller updates Stagger and sends the
artifacts to Bodega.
"""

import os.path
import sched
import sys
import time
#import threading
import requests as _requests
import fortworth as _fortworth


class PollerError(RuntimeError):
    """ Parent class for all poller errors """

class StatusError(PollerError):
    """ Error when a GET request returns anything other than 200 (ok) """
    def __init__(self, response):
        super().__init__('StatusError: GET %s returned status %d (%s)' % (
            response.url[0: response.url.find('?')],
            response.status_code, response.reason))
        self.response = response

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

def _check_status(response):
    if response.status_code != 200:
        raise StatusError(response)

def _check_content_type(response, content_type):
    if content_type not in response.headers['content-type']:
        raise ContentTypeError(response)

def _repo_request(request_url, auth=None, params=None):
    resp = _requests.get(GITHUB_URL + request_url, auth=auth, params=params)
    _check_status(resp)
    _check_content_type(resp, 'application/json')
    return resp.json()


class GitHubRepo:
    """ GitHub repository metadata as retrieved from GH REST API """
    def __init__(self, repo_full_name, auth):
        self.repo_metadata = _repo_request('repos/%s' % repo_full_name,
                                           auth=auth,
                                           params={'accept': 'application/vnd.github.v3+json',
                                                   'per_page': 50})
    def is_disabled(self):
        """ Return True if repository is disabled, False otherwise """
        return self.repo_metadata['disabled']
    def get_full_name(self):
        """ Return the full name of the repository """
        return self.repo_metadata['full_name']
    def get_description(self):
        """ Return the repository desctription """
        return self.repo_metadata['description']
    def get_url(self):
        """ Return the repository URL """
        return self.repo_metadata['url']
    def get_metadata(self, key):
        """ Convenience method to return the metadata for a given key """
        return self.repo_metadata[key]

class GitHubCommits:
    """ GitHub last commit data """
    def __init__(self, repo_full_name, auth, sha_file_name):
        last_sha = None
        params = {}
        if os.path.exists(sha_file_name):
            with open(sha_file_name) as sha_file:
                last_sha = sha_file.read()
        else:
            print('DEBUG: File %s does not exist' % sha_file_name)
        if last_sha is None: # No last commit, use last 10 commits
            params['per_page'] = 10
        else:
            params['sha'] = last_sha
        print('DEBUG: params=%s' % params)
        self.commit_list = _repo_request('repos/%s/commits' % repo_full_name,
                                         auth=auth,
                                         params=params)
        # print('DEBUG: commit_list=%s' % self.commit_list)
        if self.get_num_commits() > 0:
            print('DEBUG: writing %s' % sha_file_name)
            sha_file = open(sha_file_name, 'w')
            sha_file.write(self.get_last_commit()['sha'])
            sha_file.close()
    def get_num_commits(self):
        """ Get number of commits """
        return len(self.commit_list)
    def get_last_commit(self):
        """ Get last commit """
        return self.commit_list[0]

class GitHubActionsArtifacts:
    """ GitHub action artifacts, as retrieved from GH REST API """
    def __init__(self, repo_full_name, auth):
        self.artifact_metadata = _repo_request('repos/%s/actions/artifacts' % repo_full_name,
                                               auth=auth,
                                               params={'accept': 'application/vnd.github.v3+json',
                                                       'per_page': 50})
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

POLLING_INTERVAL_SECS = 60

GITHUB_URL = 'https://api.github.com/'
REPO_NAME = 'rh-qpid-proton-dist-win'
REPO_FULL_NAME = 'kpvdr/' + REPO_NAME
SOURCE_REPO_FULL_NAME = 'apache/qpid-proton'
BRANCH = 'master'
UID = 'kpvdr'
TOKEN = '93ae33b7c53ac76850e21c04a037fb56ffa980c8'

STAGGER_URL = 'http://localhost:8080'
BODEGA_URL = 'http://localhost:8081'
SCHED = sched.scheduler(time.time, time.sleep)

class GitHubPoller:
    """ GitHub poller which polls for GitHub actions artifacts at a regular interval """
    def start(self, sch=None):
        """ Start poller """
        try:
            repo_metadata = GitHubRepo(REPO_FULL_NAME, auth=(UID, TOKEN))
            #print(repo_metadata.repo_metadata)
            if repo_metadata.is_disabled():
                raise DisabledRepoError(REPO_FULL_NAME)
            commits = GitHubCommits(SOURCE_REPO_FULL_NAME,
                                    auth=(UID, TOKEN),
                                    sha_file_name='data/last_sha')
            print('Num commits: %d' % commits.get_num_commits())
            print('Last_commit: %s' % commits.get_last_commit()['sha'])
            artifacts = GitHubActionsArtifacts(REPO_FULL_NAME, auth=(UID, TOKEN))
            # print(artifacts.get_artifact_list())
            for artifact_name, artifact_metadata_list in artifacts.get_artifact_map().items():
                # print('%25s (%d):' % (artifact_name, len(artifact_metadata_list)))
                for artifact_metadata in artifact_metadata_list:
                    artifact_metadata['artifact_id'] = artifact_metadata.pop('id') # Replace key 'id' as this overwrites id used in stagger
                    # GitHubPoller._handle_artifact(artifact_metadata, commits, 'untested')
                    GitHubPoller._print_artifact_metadata(0, artifact_metadata)
                    print()
        except PollerError as exc:
            print(exc)
            sys.exit(1)
        else:
            print('ok')
        if sch is not None:
            SCHED.enter(POLLING_INTERVAL_SECS, 1, self.start, (sch, ))
    @staticmethod
    def _print_artifact_metadata(indent, artifact_metadata):
        artifact_metadata_keys = ['artifact_id', 'node_id', 'name', 'size_in_bytes', 'url',
                                  'archive_download_url', 'expired', 'created_at',
                                  'updated_at', 'expires_at']
        format_str = '%%%ds: %%s' % len(max(artifact_metadata_keys, key=len))
        for key in artifact_metadata_keys:
            print(indent*' ' + format_str % (key, artifact_metadata[key]))
    @staticmethod
    def _gh_actions_make_tag_data(artifact_metadata, commits):
        last_commit = commits.get_last_commit()
        data = {
            'build_id': artifact_metadata['artifact_id'],
            'build_url': artifact_metadata['url'],
            'commit_id': last_commit['sha'],
            'commit_url': last_commit['html_url'],
            #'artifacts': {artifact_metadata['artifact_id']: {}}, #artifact_metadata},
        }
        return data
    @staticmethod
    def _handle_artifact(artifact_metadata, commits, tag):
        build_data = _fortworth.BuildData(REPO_NAME, BRANCH, artifact_metadata['artifact_id'],
                                          artifact_metadata['url'])
        print('DEBUG: build_data=%s' % build_data)
        # if not _fortworth.bodega_build_exists(build_data, BODEGA_URL):
        #     _fortworth.bodega_put_build(join('build', 'dist'), build_data, BODEGA_URL)
        # print('bodega_put_build(build_dir="%s" build_data="%s" service_url="%s")' %
        #       ('build', 'dist', BODEGA_URL))
        # tag_data = GitHubPoller._gh_actions_make_tag_data(artifact_metadata, commits)
        # print('stagger_put_tag(repo="%s", branch="%s", tag="%s", tag_data="%s", service_url="%s")' %
        #       (REPO_NAME, BRANCH, tag, tag_data, STAGGER_URL))
        # _fortworth.stagger_put_tag(REPO_NAME, BRANCH, tag, tag_data, STAGGER_URL)


if __name__ == '__main__':
    POLLER = GitHubPoller()
    try:
        SCHED.enter(0, 1, POLLER.start, (SCHED, ))
        SCHED.run()
    except KeyboardInterrupt:
        print(' KeyboardInterrupt')
