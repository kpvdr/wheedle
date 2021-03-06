#
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
#

"""
Poller for new commits from a GitHub repository. This poller reads the first page of latest commits
from the source code repository and checks if there are any new commits since the last build.

The last build hash is saved in a file data/commit_hash.json by the artifact poller. If not found,
then the commit poller will assume no previous build exists, and will trigger a new build. If a
last commit hash is found, then the commits are compared to the hash to determine how many new
commits have taken place since the last build. If one or more new commits are identified, a
new build is triggered.
"""

import logging as _logging
import sched as _sched
import time as _time

import fortworth as _fortworth
import wheedle.errors as _errors
import wheedle.gh_api as _gh_api
import wheedle.poller as _poller



LOG = _logging.getLogger('CommitPoller')



class CommitPoller(_poller.Poller):
    """ Poller which polls for new commits in a GitHub repository at a regular interval """

    def __init__(self, config, name, ap_event):
        self._last_build_commit_hash = None
        self._data = {}
        super().__init__(config, name, ap_event, False)

    def poll(self):
        """ Read commits from source repository, compare with last commit id of build """
        if not self._ap_event.is_set():
            self._log.info('Waiting for Artifact Poller to complete initial run...')
            self._ap_event.wait()
            self._log.info('Artifact Poller initian run complete')

        # Read last commit hash file, it might have been updated since last poll
        self._read_last_commit_hash()

        # Read commit list one page at a time
        commits_since_build_trigger = []
        page = 0
        hash_found = False
        self._log.info('Reading commits from repository "%s"...', self._repo.full_name())
        while True:
            commit_list_page = self._repo.commit_list(page=page)
            page += 1
            if len(commit_list_page) == 0:
                # Raise error if no commits (page == 0)
                if page == 0:
                    raise _errors.EmptyCommitListError(self._repo)
                # Stop if no commits and page > 0
                break
            # Only commits since last build commit are part of this build
            # Search back from first commit (most recent) until matching hash is found
            if self._last_build_commit_hash is not None:
                for commit in commit_list_page:
                    if commit.hash() == self._last_build_commit_hash:
                        hash_found = True
                        break
                    commits_since_build_trigger.append(commit)
            # Stop if less than a full page is received, or at 5 pages
            if hash_found or len(commit_list_page) < 50 or page >= 5:
                break
        if self._last_build_commit_hash is None:
            self._log.info('No previous build commit hash found, forcing a build')
            self._trigger_build()
        elif len(commits_since_build_trigger) > 0:
            num_commits = len(commits_since_build_trigger)
            suffix = 's' if num_commits > 1 else ''
            self._log.info('%d commit%s since last build trigger:', num_commits, suffix)
            self._log.info('  %s', _gh_api.GhCommitList.hdr())
            for commit in commits_since_build_trigger:
                self._log.info('  %s', commit.to_str())
            self._trigger_build()
        else:
            self._log.info('No commits since last build')

        self._write_data()
        return False

    def _read_data(self):
        """ Read the persistent data for this poller """
        if _fortworth.exists(self._data_file_name()):
            self._data = _fortworth.read_json(self._data_file_name())
            #self._log.info('Last build trigger: %s for sha %s', '<date>', '<build-sha>')
        else:
            self._log.info('No previous build trigger(s) found - missing file "%s"',
                           self._data_file_name())

    def _read_last_commit_hash(self):
        """ Read the commit hash of any previous build that might have been made """
        last_commit_hash_file_name = self._last_build_hash_file_name()
        if _fortworth.exists(last_commit_hash_file_name):
            last_build_commit = _fortworth.read_json(last_commit_hash_file_name)
            self._last_build_commit_hash = last_build_commit['commit-hash']
            self._log.info('Last build hash: %s', self._last_build_commit_hash)
        else:
            self._last_build_commit_hash = None
            self._log.info('No last build hash found - missing file "%s"',
                           last_commit_hash_file_name)

    def _trigger_build(self):
        """ Trigger a GitHub action """
        if not self._dry_run():
            _gh_api.gh_http_post_request( \
                '{}/repos/{}/dispatches'.format(self._config['GitHub']['service_url'],
                                                self._build_repo_full_name()),
                auth=self._config.auth(),
                params={'accept': 'application/vnd.github.v3+json'},
                json={'event_type': 'trigger-action'})
            self._log.info('Build triggered on "%s"', self._build_repo_full_name())
        else:
            self._log.info('Build triggered on "%s" (DRY RUN)', self._build_repo_full_name())

    def _validate(self):
        pass

    def _write_data(self):
        """ Write the persistent data for this poller """
        _fortworth.write_json(self._data_file_name(), self._data)

    # Configuration convenience methods

    def _data_file_name(self):
        if 'commit_poller_data_file_name' in self._poller_config():
            return _fortworth.join(self._config.data_dir(),
                                   self._poller_config()['commit_poller_data_file_name'])
        return _fortworth.join(self._config.data_dir(), 'commit-poller.{}.json'.format(self._name))

    def _polling_interval_secs(self, _):
        try:
            return int(self._poller_config()['commit_poller_polling_interval_secs'])
        except ValueError:
            self._raise_config_error(('Invalid value "{}" for '
                                      '"commit_poller_polling_interval_secs"').format( \
                self._poller_config()['commit_poller_polling_interval_secs']))

    def _dry_run(self):
        if 'trigger_dry_run' in self._poller_config():
            return self._poller_config()['trigger_dry_run'].lower() in ['true', 'yes', '1']
        return False

    @staticmethod
    def run(config, name, ap_event):
        """ Convenience method to run the CommitPoller on a scheduler """
        LOG.info('Starting commit poller "%s"...', name)
        try:
            sch = _sched.scheduler(_time.time, _time.sleep)
            commit_poller = CommitPoller(config, name, ap_event)
            sch.enter(0, 1, commit_poller.start, (sch, ))
            sch.run()
        except (_errors.PollerError) as err:
            LOG.error(err)
            LOG.info('Poller "%s" exiting owing to previous error', name)
        except KeyboardInterrupt:
            pass
