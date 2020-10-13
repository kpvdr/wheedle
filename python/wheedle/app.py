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
Main application
"""


import logging as _logging
import multiprocessing as _mp
import time as _time

import fortworth as _fortworth
import wheedle.artifact_poller as _apoller
import wheedle.commit_poller as _cpoller
import wheedle.errors as _errors
import wheedle.gh_api as _gh_api


# === GITHUB ===
# This section describes the GitHub REST API environment, and the specific GitHub repositories
# used by this application.

# GitHub API service URL for all GH API requests
GITHUB_SERVICE_URL = 'https://api.github.com'

# --- GitHub builder repository ---
# This GitHub repository uses GH Actions to build the project, then makes them available as
# workflow artifacts. These are polled for and downloaded by the artifact_poller.
# BUILD_REPO_OWNER = 'rh-messaging'
BUILD_REPO_OWNER = 'kpvdr' # Temporary, until issue with rh-messaging repo is resolved
BUILD_REPO_NAME = 'rh-qpid-proton-dist-win'

# --- GitHub source repository ---
# This is the GitHub repository from which the source code comes. The GH Actions workflow of
# the GH builder repository above clones this repository and builds it. It is this repository
# that must be scanned for pushed commits which will trigger a build of the builder Actions
# workflow.
SOURCE_REPO_OWNER = 'apache'
SOURCE_REPO_NAME = 'qpid-proton'
SOURCE_REPO_BRANCH = 'master'

# GitHub API authentication, consisting of a user id and a token. The token is saved in a files
# GH_API_TOKEN_FILE_NAME located in the DATA_DIR directory.
GH_API_AUTH_UID = 'kpvdr'
GH_API_TOKEN_FILE_NAME = 'token' # Located in DATA_DIR


# === INTERVALS ===
# Convenience constants, all in seconds
MINUTES = 60
HOURS = 60 * MINUTES


# === LOCAL ===
# Local process settings

# Local data directory in which data files are stored. This directory is created if it does not
# exist, and is located in the project home directory.
DATA_DIR = 'data'

# Delay between starting the artifact poller and the commit poller. This gives the artifact
# poller time to download the commit id of the last build which the commit poller reads
# in order to determine if a build is required. If no file is downloaded by this time, then
# the commit poller will assume no previous builds are present, and will trigger a build
# unconditionally.
COMMIT_POLLER_START_DELAY = 2 * MINUTES


# === ARTIFACT POLLER ===
# Information for the artifact_poller process.

# Time between poles for artifacts, in seconds.
ARTIFACT_POLLING_INTERVAL_SECS = 3 * MINUTES #4 * HOURS # seconds

# Time between poles for artifacts when the Bodega and/or Stagger instances cannot be found at the
# URLs BODEGA_URL and STAGGER_URL respectivly. This gives a shorter retry time if this should
# occur.
ERROR_POLLING_INTERVAL_SECS = 1 * MINUTES #10 * MINUTES # seconds

# Artifact name from GitHub builder repository workflow which contains the last build git hash.
LAST_BUILD_CID_ARTIFACT_NAME = 'commit_hash'

# List of artifact names from GitHub builder repository workflow which must be downloaded and
# pushed to Bodega and Stagger.
BUILD_ARTIFACT_NAME_LIST = ['rh-qpid-proton-dist-win', 'python-*-pkgs']

# Name of local JSON file which redords the artifact ids that have been processed in the local
# DATA_DIR directory. If the poller stopped and started again, this file is read to initialize the
# list and prevent previously processed artifacts which may still be present from being processed
# again.
ARTIFACT_POLLER_DATA_FILE_NAME = 'artifact_id.json'

# Tag used by Stagger when submitting artifacts
TAG = 'untested'

# URL for the Bodega artifact storage service required by the artifact poller.
BODEGA_URL = 'http://localhost:8081'

# URL for the Stagger artifact messaging and reporting service required by the artifact poller.
STAGGER_URL = 'http://localhost:8080'


# === COMMIT POLLER ===
# Information for the commit poller process.

# Time between polls for source repository commits, in seconds.
COMMIT_POLLING_INTERVAL_SECS = 3 * MINUTES #4 * HOURS # seconds

# Name of local JSON file which records the last trigger of the GH builder repository.
COMMIT_DATA_FILE_NAME = 'last_trigger.json'


# === LOGGING ===

# Default logging level
DEFAULT_LOG_LEVEL = _logging.INFO

_logging.basicConfig(level=DEFAULT_LOG_LEVEL,
                     format='%(asctime)s  %(name)s - %(levelname)s: %(message)s',
                     datefmt='%Y-%m-%d %H:%M:%S %Z')



# pylint: disable=too-few-public-methods
class Application:
    """ Poller application """

    def __init__(self, home, data_dir=None):
        self._home = home
        self._data_dir = data_dir if data_dir is not None else _fortworth.join(home, DATA_DIR)
        self._log = _logging.getLogger(self.__class__.__name__)
        self._log.info('Data directory: %s', self._data_dir)
        self._auth = None

    def run(self):
        """ Run the application. This starts one each of the builder and commit pollers """
        try:
            self._auth = (GH_API_AUTH_UID,
                          self._read_token(_fortworth.join(self._data_dir, GH_API_TOKEN_FILE_NAME)))

            # Start artifact poller process
            artifact_poller_process = self._start_artifact_poller()

            # Give a chance for the last commit file to upload before polling for commit changes
            # TODO: ugly - find a more elegant solution to this
            _time.sleep(COMMIT_POLLER_START_DELAY)

            # Start commit poller process only if the artifact poller is still running
            if not artifact_poller_process.is_alive():
                self._log.warning('Artifact poller exited, aborting start of commit poller')
            else:
                commit_poller_process = self._run_commit_poller()

                # Wait for processss to finish
                artifact_poller_process.join()
                commit_poller_process.join()
        except _errors.PollerError as err:
            self._log.error(err)
            _fortworth.exit(1)
        except KeyboardInterrupt:
            print(' KeyboardInterrupt')
        self._log.info('exit')

    @staticmethod
    def _read_token(token_file):
        """ Read token file and return token as string """
        try:
            return _fortworth.read(token_file).strip()
        except FileNotFoundError:
            raise _errors.TokenNotFoundError(token_file)

    def _start_artifact_poller(self):
        """ Start the artifact poller, return the process object """
        artifact_repo_data = _gh_api.GhRepositoryData(GITHUB_SERVICE_URL, BUILD_REPO_OWNER,
                                                      BUILD_REPO_NAME, self._auth)
        artifact_poller_data = _apoller.ArtifactPollerData(SOURCE_REPO_BRANCH,
                                                           BUILD_ARTIFACT_NAME_LIST,
                                                           BODEGA_URL, STAGGER_URL,
                                                           TAG,
                                                           ARTIFACT_POLLING_INTERVAL_SECS,
                                                           ERROR_POLLING_INTERVAL_SECS,
                                                           self._data_dir,
                                                           ARTIFACT_POLLER_DATA_FILE_NAME,
                                                           LAST_BUILD_CID_ARTIFACT_NAME)
        artifact_poller_process = _mp.Process(target=_apoller.ArtifactPoller.run,
                                              args=(artifact_repo_data, artifact_poller_data),
                                              name='ArtifactPollerProcess')
        artifact_poller_process.start()
        return artifact_poller_process

    def _run_commit_poller(self):
        """ Start the commit poller, return the process object """
        source_repo_data = _gh_api.GhRepositoryData(GITHUB_SERVICE_URL, SOURCE_REPO_OWNER,
                                                    SOURCE_REPO_NAME, self._auth)
        commit_poller_data = _cpoller.CommitPollerData(BUILD_REPO_OWNER,
                                                       BUILD_REPO_NAME,
                                                       SOURCE_REPO_BRANCH,
                                                       COMMIT_POLLING_INTERVAL_SECS,
                                                       self._data_dir,
                                                       COMMIT_DATA_FILE_NAME,
                                                       LAST_BUILD_CID_ARTIFACT_NAME)
        commit_poller_process = _mp.Process(target=_cpoller.CommitPoller.run,
                                            args=(source_repo_data, commit_poller_data),
                                            name='CommitPollerProcess')
        commit_poller_process.start()
        return commit_poller_process



if __name__ == '__main__':
    APP = Application(_fortworth.current_dir())
    APP.run()
