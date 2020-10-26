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
Configuration and configuration file for the instances of ArtifactPoller and CommitPoller.
"""

import configparser as _cp

import fortworth as _fortworth
import wheedle.errors as _errors



class Configuration:
    """ Class holding configuration for app """

    def __init__(self, config_file_name, data_dir):
        self._config_file_name = config_file_name
        self._config = _cp.ConfigParser()
        try:
            self._read_config_file(config_file_name)
            self._validate()
        except _cp.ParsingError as err:
            print('Config file error: {}'.format(err))
            _fortworth.exit(1)
        except _errors.PollerError as err:
            print(err)
            _fortworth.exit(1)
        self._data_dir = data_dir if data_dir is not None else self._config['Local']['data_dir']
        auth_token_file = _fortworth.join(self._data_dir,
                                          self._config['GitHub']['gh_api_token_file_name'])
        self._auth = (self._config['GitHub']['api_auth_uid'], self._read_token(auth_token_file))

    def __contains__(self, val):
        return val in self._config

    def __getitem__(self, key):
        return self._config.__getitem__(key)

    def auth(self):
        """ Return GitHub authorization token """
        return self._auth

    def config_file_name(self):
        """ Return configuration file name """
        return self._config_file_name

    def data_dir(self):
        """ Return data directory """
        return self._data_dir

    def has_commit_poller(self, name):
        """ Return True if a commit poller is configured for section name """
        return 'source_repo_owner' in self._config[name]

    def poller_names(self):
        """ Return list of pollers """
        return [i for i in self._config.sections() if i not in ['Local', 'GitHub', 'Logging',
                                                                'DEFAULT']]

    def _check_all_in_list(self, config_section, test_list, target_list, descr):
        if not all(elt in target_list for elt in test_list):
            raise _errors.ConfigFileError(self._config_file_name, config_section, \
                'Required {} missing: {}'.format(descr,
                                                 [i for i in test_list if i not in target_list]))

    def _check_artifact_poller(self, key):
        self._check_keys(['bodega_url', 'build_artifact_name_list', 'build_repo_name',
                          'build_repo_owner', 'error_polling_interval_secs',
                          'last_build_hash_artifact_name', 'polling_interval_secs', 'source_branch',
                          'stagger_tag', 'stagger_url'], key)

    def _check_commit_poller(self, key):
        self._check_keys(['source_repo_owner', 'source_repo_name'], key)

    def _check_keys(self, key_list, section=None):
        target_list = []
        if section is None:
            target_list = self._config.sections()
        else:
            for key in self[section]:
                target_list.append(key)
        descr = 'section(s)' if section is None else 'key(s)'
        self._check_all_in_list(section, key_list, target_list, descr)

    def _check_pollers(self):
        poller_keys = [i for i in self._config.sections() if i not in ['Local', 'GitHub', 'Logging',
                                                                       'DEFAULT']]
        for poller_key in poller_keys:
            self._check_artifact_poller(poller_key)
            if 'source_repo_owner' in self._config[poller_key] or \
                'source_repo_name' in self._config[poller_key]:
                self._check_commit_poller(poller_key)

    def _read_config_file(self, config_file_name):
        try:
            self._config.read(config_file_name)
        except _cp.Error as err:
            raise _errors.ConfigFileError(self._config_file_name, None, err)

    @staticmethod
    def _read_token(token_file):
        """ Read token file and return token as string """
        try:
            return _fortworth.read(token_file).strip()
        except FileNotFoundError:
            raise _errors.TokenNotFoundError(token_file)

    def _validate(self):
        self._check_keys(['Local', 'GitHub', 'Logging'])
        self._check_keys(['data_dir'], 'Local')
        self._check_keys(['api_auth_uid', 'gh_api_token_file_name', 'service_url'], 'GitHub')
        self._check_keys(['default_log_level'], 'Logging')
        self._check_pollers()
