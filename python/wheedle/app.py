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

import configparser as _cp
import logging as _logging
import multiprocessing as _mp
#import time as _time

import fortworth as _fortworth
import wheedle.artifact_poller as _apoller
import wheedle.commit_poller as _cpoller
import wheedle.errors as _errors
#import wheedle.gh_api as _gh_api


# # === GITHUB ===
# # This section describes the GitHub REST API environment, and the specific GitHub repositories
# # used by this application.
#
# # GitHub API service URL for all GH API requests
# GITHUB_SERVICE_URL = 'https://api.github.com'
#
# # --- GitHub builder repository ---
# # This GitHub repository uses GH Actions to build the project, then makes them available as
# # workflow artifacts. These are polled for and downloaded by the artifact_poller.
# # BUILD_REPO_OWNER = 'rh-messaging'
# BUILD_REPO_OWNER = 'kpvdr' # Temporary, until issue with rh-messaging repo is resolved
# BUILD_REPO_NAME = 'rh-qpid-proton-dist-win'
#
# # --- GitHub source repository ---
# # This is the GitHub repository from which the source code comes. The GH Actions workflow of
# # the GH builder repository above clones this repository and builds it. It is this repository
# # that must be scanned for pushed commits which will trigger a build of the builder Actions
# # workflow.
# SOURCE_REPO_OWNER = 'apache'
# SOURCE_REPO_NAME = 'qpid-proton'
# SOURCE_REPO_BRANCH = 'master'
#
# # GitHub API authentication, consisting of a user id and a token. The token is saved in a files
# # GH_API_TOKEN_FILE_NAME located in the DATA_DIR directory.
# GH_API_AUTH_UID = 'kpvdr'
# GH_API_TOKEN_FILE_NAME = 'token' # Located in DATA_DIR
#
#
# # === INTERVALS ===
# # Convenience constants, all in seconds
# MINUTES = 60
# HOURS = 60 * MINUTES
#
#
# # === LOCAL ===
# # Local process settings
#
# # Local data directory in which data files are stored. This directory is created if it does not
# # exist, and is located in the project home directory.
# DATA_DIR = 'data'
#
# # Delay between starting the artifact poller and the commit poller. This gives the artifact
# # poller time to download the commit id of the last build which the commit poller reads
# # in order to determine if a build is required. If no file is downloaded by this time, then
# # the commit poller will assume no previous builds are present, and will trigger a build
# # unconditionally.
# COMMIT_POLLER_START_DELAY = 3 * MINUTES
#
#
# # === ARTIFACT POLLER ===
# # Information for the artifact_poller process.
#
# # Time between poles for artifacts, in seconds.
# ARTIFACT_POLLING_INTERVAL_SECS = 5 * MINUTES
#
# # Time between poles for artifacts when the Bodega and/or Stagger instances cannot be found at the
# # URLs BODEGA_URL and STAGGER_URL respectivly. This gives a shorter retry time if this should
# # occur.
# ERROR_POLLING_INTERVAL_SECS = 1 * MINUTES
#
# # Artifact name from GitHub builder repository workflow which contains the last build git hash.
# LAST_BUILD_CID_ARTIFACT_NAME = 'commit_hash'
#
# # List of artifact names from GitHub builder repository workflow which must be downloaded and
# # pushed to Bodega and Stagger.
# BUILD_ARTIFACT_NAME_LIST = ['rh-qpid-proton-dist-win', 'python-*-pkgs']
#
# # Name of local JSON file which redords the artifact ids that have been processed in the local
# # DATA_DIR directory. If the poller stopped and started again, this file is read to initialize the
# # list and prevent previously processed artifacts which may still be present from being processed
# # again.
# ARTIFACT_POLLER_DATA_FILE_NAME = 'artifact_id.json'
#
# # Tag used by Stagger when submitting artifacts
# TAG = 'untested'
#
# # URL for the Bodega artifact storage service required by the artifact poller.
# BODEGA_URL = 'http://localhost:8081'
#
# # URL for the Stagger artifact messaging and reporting service required by the artifact poller.
# STAGGER_URL = 'http://localhost:8080'
#
#
# # === COMMIT POLLER ===
# # Information for the commit poller process.
#
# # Time between polls for source repository commits, in seconds.
# COMMIT_POLLING_INTERVAL_SECS = 5 * MINUTES
#
# # Name of local JSON file which records the last trigger of the GH builder repository.
# COMMIT_DATA_FILE_NAME = 'last_trigger.json'
#
#
# # === LOGGING ===
#
# # Default logging level
# DEFAULT_LOG_LEVEL = _logging.INFO
#
# _logging.basicConfig(level=DEFAULT_LOG_LEVEL,
#                      format='%(asctime)s  %(name)s - %(levelname)s: %(message)s',
#                      datefmt='%Y-%m-%d %H:%M:%S %Z')


class Configuration:
    """ Class holding configuration for app """

    def __init__(self, config_file, data_dir):
        self._config_file = config_file
        self._data_dir = data_dir
        self._config = _cp.ConfigParser()
        self._config.read(config_file)
        try:
            self._validate()
        except _errors.PollerError as err:
            print(err)
            _fortworth.exit(1)
        self._auth = (self._config['GitHub']['api_auth_uid'],
                      self._read_token(self._config['GitHub']['gh_api_token_file_name']))

    def auth(self):
        """ Return GitHub authorization token """
        return self._auth

    def data_dir(self):
        """ Return data directory """
        return self._data_dir

    def repo_full_name(self, name):
        """ Convenience method to return repository full name (owner/name) """
        return _fortworth.join(self[name]['repo_owner'], self[name]['repo_name'])

    def _get_poller_names(self, clazz):
        names = []
        poller_keys = [i for i in self._config.sections() if i not in ['Local', 'GitHub', 'Logging',
                                                                       'DEFAULT']]
        for name in poller_keys:
            if self[name]['class'] == clazz:
                names.append(name)
        return names

    def _start_poller(self, name):
        poller_config = self[name]
        if poller_config['class'] == 'ArtifactPoller':
            return self._start_artifact_poller()
        if poller_config['class'] == 'CommitPoller':
            return self._start_config_poller()
        raise _errors.ConfigFileError(self._config_file,
                                      'Poller {} has unknown class "{}"'.format( \
                                      name, poller_config['class']))

    def _start_artifact_poller(self):
        """ Start the artifact poller, return the process object """
        artifact_poller_process = _mp.Process(target=_apoller.ArtifactPoller.run,
                                              args=(self._config),
                                              name='ArtifactPollerProcess')
        artifact_poller_process.start()
        return artifact_poller_process

    def _start_config_poller(self):
        commit_poller_process = _mp.Process(target=_cpoller.CommitPoller.run,
                                            args=(self._config),
                                            name='CommitPollerProcess')
        commit_poller_process.start()
        return commit_poller_process

    def get_artifact_poller_names(self):
        """ Return list of artifact pollers """
        return self._get_poller_names('ArtifactPoller')

    def get_artifact_poller_process_list(self):
        """ Return a list of artifact poller object objects in configuration """
        pollers = []
        for poller_name in self.get_artifact_poller_names():
            pollers .append(self._start_poller(poller_name))
        return pollers

    def get_commit_poller_names(self):
        """ Return list of commit pollers """
        return self._get_poller_names('CommitPoller')

    def get_commit_poller_process_list(self):
        """ Return a list of artifact poller objects in configuration """
        pollers = []
        for poller_name in self.get_commit_poller_names():
            pollers .append(self._start_poller(poller_name))
        return pollers

    def log_level(self):
        """ Return logging level """
        log_level_str = self['Logging']['default_log_level']
        if log_level_str == 'DEBUG':
            return _logging.DEBUG
        if log_level_str == 'INFO':
            return _logging.INFO
        if log_level_str == 'WARNING':
            return _logging.WARNING
        if log_level_str == 'ERROR':
            return _logging.ERROR
        if log_level_str == 'CRITICAL':
            return _logging.CRITICAL
        raise _errors.ConfigFileError(self._config_file, \
            'Invalid value {} for section "Logging" key "default_log_level"'.format(log_level_str))

    def _check_all_in_list(self, test_list, target_list, descr):
        if not all(elt in target_list for elt in test_list):
            raise _errors.ConfigFileError(self._config_file, 'Required {} missing: {}'.format( \
                                          descr, [i for i in test_list if i not in target_list]))

    def _check_artifact_poller(self, key):
        self._check_keys(['repo_owner', 'repo_name', 'polling_interval_secs',
                          'error_polling_interval_secs', 'last_build_cid_artifact_name',
                          'build_artifact_name_list', 'artifact_poller_data_file_name',
                          'stagger_tag'], key)

    def _check_commit_poller(self, key):
        self._check_keys(['repo_owner', 'repo_name', 'repo_branch', 'start_delay_secs',
                          'polling_interval_secs', 'commit_data_file_name'], key)

    def _check_keys(self, key_list, section=None):
        target_list = []
        if section is None:
            target_list = self._config.sections()
        else:
            for key in self[section]:
                target_list.append(key)
        descr = 'section(s)' if section is None else 'key(s) in section "{}"'.format(section)
        self._check_all_in_list(key_list, target_list, descr)

    def _check_pollers(self):
        poller_keys = [i for i in self._config.sections() if i not in ['Local', 'GitHub', 'Logging',
                                                                       'DEFAULT']]
        print('DEBUG: poller_keys={}'.format(poller_keys))
        for poller_key in poller_keys:
            if 'class' in self[poller_key]:
                poller_class = self[poller_key]['class']
                if poller_class == 'ArtifactPoller':
                    self._check_artifact_poller(poller_key)
                elif poller_class == 'CommitPoller':
                    self._check_commit_poller(poller_key)
                else:
                    raise _errors.ConfigFileError(self._config_file,
                                                  'Unknown poller class {}'.format(poller_class))
            else:
                raise _errors.ConfigFileError(self._config_file,
                                              'Section {} without class'.format(poller_key))

    def _validate(self):
        self._check_keys(['Local', 'GitHub', 'Logging'])
        self._check_keys(['data_dir', 'gh_api_token_file_name', 'bodega_url', 'stagger_url'],
                         'Local')
        self._check_keys(['service_url', 'api_auth_uid'], 'GitHub')
        self._check_keys(['default_log_level'], 'Logging')
        self._check_pollers()

    @staticmethod
    def _read_token(token_file):
        """ Read token file and return token as string """
        try:
            return _fortworth.read(token_file).strip()
        except FileNotFoundError:
            raise _errors.TokenNotFoundError(token_file)

    def __getitem__(self, key):
        return self._config.__getitem__(key)

# pylint: disable=too-few-public-methods
class Application:
    """ Poller application """

    def __init__(self, home, data_dir=None, config_file=None):
        self._home = home
        self._data_dir = data_dir if data_dir is not None else _fortworth.join(home, 'data')
        self._log = _logging.getLogger(self.__class__.__name__)
        self._log.info('Data directory: %s', self._data_dir)
        config_file = config_file if config_file is not None else _fortworth.join(self._data_dir,
                                                                                  'wheedle.conf')
        self._config = Configuration(config_file, self._data_dir)
        _logging.basicConfig(level=self._config['Logging']['default_log_level'],
                             format='%(asctime)s  %(name)s - %(levelname)s: %(message)s',
                             datefmt='%Y-%m-%d %H:%M:%S %Z')

    def run(self):
        """ Run the application. This starts one each of the builder and commit pollers """
        try:
            process_list = self._config.get_artifact_poller_process_list()
            process_list.extend(self._config.get_commit_poller_process_list())

            # Wait for processes to terminate
            for process in process_list:
                process.join()
    #
    #         # Start artifact poller process
    #         artifact_poller_process = self._start_artifact_poller()
    #
    #         # Give a chance for the last commit file to upload before polling for commit changes
    #         # TODO: ugly - find a more elegant solution to this
    #         _time.sleep(COMMIT_POLLER_START_DELAY)
    #
    #         # Start commit poller process only if the artifact poller is still running
    #         if not artifact_poller_process.is_alive():
    #             self._log.warning('Artifact poller exited, aborting start of commit poller')
    #         else:
    #             commit_poller_process = self._run_commit_poller()
    #
    #             # Wait for processss to finish
    #             artifact_poller_process.join()
    #             commit_poller_process.join()
        except _errors.PollerError as err:
            self._log.error(err)
            _fortworth.exit(1)
        except KeyboardInterrupt:
            print(' KeyboardInterrupt')
        self._log.info('exit')

    # @staticmethod
    # def _read_token(token_file):
    #     """ Read token file and return token as string """
    #     try:
    #         return _fortworth.read(token_file).strip()
    #     except FileNotFoundError:
    #         raise _errors.TokenNotFoundError(token_file)

    # def _start_artifact_poller(self):
    #     """ Start the artifact poller, return the process object """
    #     artifact_repo_data = _gh_api.GhRepositoryData(GITHUB_SERVICE_URL, BUILD_REPO_OWNER,
    #                                                   BUILD_REPO_NAME, self._auth)
    #     artifact_poller_data = _apoller.ArtifactPollerData(SOURCE_REPO_BRANCH,
    #                                                        BUILD_ARTIFACT_NAME_LIST,
    #                                                        BODEGA_URL, STAGGER_URL,
    #                                                        TAG,
    #                                                        ARTIFACT_POLLING_INTERVAL_SECS,
    #                                                        ERROR_POLLING_INTERVAL_SECS,
    #                                                        self._data_dir,
    #                                                        ARTIFACT_POLLER_DATA_FILE_NAME,
    #                                                        LAST_BUILD_CID_ARTIFACT_NAME)
    #     artifact_poller_process = _mp.Process(target=_apoller.ArtifactPoller.run,
    #                                           args=(artifact_repo_data, artifact_poller_data),
    #                                           name='ArtifactPollerProcess')
    #     artifact_poller_process.start()
    #     return artifact_poller_process
    #
    # def _run_commit_poller(self):
    #     """ Start the commit poller, return the process object """
    #     source_repo_data = _gh_api.GhRepositoryData(GITHUB_SERVICE_URL, SOURCE_REPO_OWNER,
    #                                                 SOURCE_REPO_NAME, self._auth)
    #     commit_poller_data = _cpoller.CommitPollerData(BUILD_REPO_OWNER,
    #                                                    BUILD_REPO_NAME,
    #                                                    SOURCE_REPO_BRANCH,
    #                                                    COMMIT_POLLING_INTERVAL_SECS,
    #                                                    self._data_dir,
    #                                                    COMMIT_DATA_FILE_NAME,
    #                                                    LAST_BUILD_CID_ARTIFACT_NAME)
    #     commit_poller_process = _mp.Process(target=_cpoller.CommitPoller.run,
    #                                         args=(source_repo_data, commit_poller_data),
    #                                         name='CommitPollerProcess')
    #     commit_poller_process.start()
    #     return commit_poller_process



if __name__ == '__main__':
    APP = Application(_fortworth.current_dir())
    APP.run()
