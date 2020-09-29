"""
Classes representing various GitHub API calls.
"""

import datetime as _datetime
import time as _time
import requests as _requests

import fortworth as _fortworth
import poller.errors as _errors


# Chunk size for HTTP transfer of files
MAX_DOWNLOAD_CHUNK_SIZE = 32768


def gh_http_get_request(url, auth=None, params=None, content_type='json'):
    """ Send HTTP GET request to GitHub """
    try:
        resp = _requests.get(url, auth=auth, params=params)
        resp.raise_for_status()
        if content_type not in resp.headers['content-type']:
            raise _errors.ContentTypeError(resp)
        return resp.json()
    except _requests.HTTPError:
        raise _errors.HttpError(resp)

def str_time_to_unix_ts(str_time):
    """ Convert timestamp in ISO 8601 to unix timestamp """
    return _time.mktime(_datetime.datetime.strptime(str_time, '%Y-%m-%dT%H:%M:%S%z').timetuple())



# pylint: disable=too-few-public-methods
class GhRepositoryData:
    """ Arguments neede to connect to a GitHub repository using an API """
    def __init__(self, service_url, repo_owner, repo_name, auth):
        self.service_url = service_url
        self.owner = repo_owner
        self.name = repo_name
        self.auth = auth
    def full_name(self):
        """ Get repository full name (owner/name) """
        return _fortworth.join(self.owner, self.name)



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



class GhArtifactItem(MetadataMap):
    """ Single artifact metadata """
    def created_at(self):
        """ Return artifact created date/time in ISO 8601 format """
        return self._metadata['created_at']
    def download(self, data_dir, auth):
        """ Download artifact to data_dir """
        with _requests.get(self._download_url(), stream=True, auth=auth) as req:
            req.raise_for_status()
            artifact_file_name = _fortworth.join(data_dir, self.name() + '.zip')
            with open(artifact_file_name, 'wb') as artifact_file:
                for chunk in req.iter_content(chunk_size=MAX_DOWNLOAD_CHUNK_SIZE):
                    artifact_file.write(chunk)
            return self.name() + '.zip'
        return None
    def _download_url(self):
        return self._metadata['archive_download_url']
    def expired(self):
        """ Return True if artifact has expired, False if not """
        return self._metadata['expired']
    @staticmethod
    def hdr():
        """ Return a header to match the output of to_str() """
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
    def to_str(self):
        """ Return a pretty string used in reporting """
        return '{:>10}  {:>12}  {:>22}  {:<25}'.format(self.id(), self.size_in_bytes(),
                                                       self.created_at(), self.name())
    def url(self):
        """ Return GitHub artifact url """
        return self._metadata['url']
    def __lt__(self, other):
        return str_time_to_unix_ts(self.created_at()) < str_time_to_unix_ts(other.created_at())
    def __repr__(self):
        return 'GhArtifactItem(id={} name={} created_at={} expired={})'.format( \
            self.id(), self.name(), self.created_at(), self.expired())



class GhArtifactList(MetadataMap):
    """ List of GitHub artifacts associated with a workflow """
    def __init__(self, metadata):
        super().__init__(metadata)
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



class GhRepository(MetadataMap):
    """ GitHub repository metadata as retrieved from GitHub REST API """
    def __init__(self, metadata, repo_data):
        super().__init__(metadata)
        self._repo_data = repo_data
    def auth(self):
        """ Get repo authorization as a tuple (uid, token) """
        return self._repo_data.auth
    def full_name(self):
        """ Get repo full name """
        return self._repo_data.full_name()
    def is_disabled(self):
        """ Return True if repository is disabled, False otherwise """
        return self._metadata['disabled']
    def name(self):
        """ Get repo name """
        return self._repo_data.name
    def owner(self):
        """ Get repo owner """
        return self._repo_data.owner
    def to_str(self):
        """ Return a pretty string used in reporting """
        return 'Found repository {}:'.format(self.name())
    def workflow_list(self):
        """ Get workflow list """
        return GhWorkflowList( \
            gh_http_get_request('{}/repos/{}/{}/actions/runs'.format( \
                self._repo_data.service_url, self._repo_data.owner, self._repo_data.name),
                                auth=self._repo_data.auth,
                                params={'accept': 'application/vnd.github.v3+json',
                                        'per_page': 50}),
            self._repo_data.auth)
    @staticmethod
    def create_repository(repo_data):
        """ Static convenience method to create a new instance of GhRepository """
        return GhRepository( \
            gh_http_get_request('{}/repos/{}/{}'.format(repo_data.service_url, repo_data.owner,
                                                        repo_data.name),
                                auth=repo_data.auth,
                                params={'accept': 'application/vnd.github.v3+json',
                                        'per_page': 50}),
            repo_data)
    def __repr__(self):
        return 'GhRepository(full_name={})'.format(self.full_name())



class GhWorkflowItem(MetadataMap):
    """ GitHub workflow item """
    def __init__(self, metadata, auth):
        super().__init__(metadata)
        self._artifact_list = GhArtifactList( \
            gh_http_get_request(self._metadata['artifacts_url'],
                                auth=auth,
                                params={'accept': 'application/vnd.github.v3+json',
                                        'per_page': 50}))
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
    def to_str(self):
        """ Return a pretty string used in reporting """
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
    def updated_at(self):
        """ Get string timestamp of last update """
        return self._metadata['updated_at']
    def __iter__(self):
        return sorted(self._artifact_list).__iter__()
    def __lt__(self, other):
        return str_time_to_unix_ts(self.updated_at()) < str_time_to_unix_ts(other.updated_at())
    def __repr__(self):
        return 'GhWorkflowItem(run_number={} dated {} status={} conclusion={})'.format( \
            self.run_number(), self.updated_at(), self.status(), self.conclusion())



class GhWorkflowList(MetadataMap):
    """ List of GitHub workflows, as retrieved from GitHub REST API """
    def __init__(self, metadata, auth):
        super().__init__(metadata)
        self._wf_item_list = []
        for wf_item in self._metadata['workflow_runs']:
            self._wf_item_list.append(GhWorkflowItem(wf_item, auth))
    def to_str(self):
        """ Return a pretty string used in reporting """
        return 'Found {} workflow item(s)'.format(len(self))
    def wf_list(self):
        """ Get sorted list of workflow items """
        return sorted(self._wf_item_list)
    def __iter__(self):
        return sorted(self._wf_item_list).__iter__()
    def __len__(self):
        return len(self._wf_item_list)
    def __repr__(self):
        return 'GhWorkflowList(num_workflows={})'.format(len(self._wf_item_list))