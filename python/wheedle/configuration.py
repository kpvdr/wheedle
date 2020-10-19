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
import logging as _logging

import fortworth as _fortworth
import wheedle.errors as _errors



class Configuration:
    """ Class holding configuration for app """

    def __init__(self, config_file, data_dir):
        self._config_file = config_file
        self._config = _cp.ConfigParser()
        self._config.read(config_file)
        self._data_dir = data_dir if data_dir is not None else self._config['Local']['data_dir']
        try:
            self._validate()
        except _errors.PollerError as err:
            print(err)
            _fortworth.exit(1)
        auth_token_file = _fortworth.join(self._data_dir,
                                          self._config['GitHub']['gh_api_token_file_name'])
        self._auth = (self._config['GitHub']['api_auth_uid'], self._read_token(auth_token_file))

    def __getitem__(self, key):
        return self._config.__getitem__(key)

    def artifact_poller_names(self):
        """ Return list of artifact pollers """
        return self._poller_names('ArtifactPoller')

    def auth(self):
        """ Return GitHub authorization token """
        return self._auth

    def commit_poller_names(self):
        """ Return list of commit pollers """
        return self._poller_names('CommitPoller')

    def config_file(self):
        """ Return configuration file name """
        return self._config_file

    def data_dir(self):
        """ Return data directory """
        return self._data_dir

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

    def repo_full_name(self, name):
        """ Convenience method to return repository full name (owner/name) """
        return _fortworth.join(self[name]['repo_owner'], self[name]['repo_name'])

    def _check_all_in_list(self, test_list, target_list, descr):
        if not all(elt in target_list for elt in test_list):
            raise _errors.ConfigFileError(self._config_file, 'Required {} missing: {}'.format( \
                                          descr, [i for i in test_list if i not in target_list]))

    def _check_artifact_poller(self, key):
        self._check_keys(['class', 'repo_owner', 'repo_name', 'build_artifact_name_list',
                          'data_file_name', 'last_build_hash_file_name', 'stagger_tag',
                          'bodega_url', 'stagger_url'], key)

    def _check_commit_poller(self, key):
        self._check_keys(['class', 'repo_owner', 'repo_name', 'start_delay_secs', 'data_file_name',
                          'trigger_artifact_poller'], key)

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

    def _poller_names(self, clazz):
        names = []
        poller_keys = [i for i in self._config.sections() if i not in ['Local', 'GitHub', 'Logging',
                                                                       'DEFAULT']]
        for name in poller_keys:
            if self[name]['class'] == clazz:
                names.append(name)
        return names

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
        self._check_keys(['polling_interval_secs', 'error_polling_interval_secs', 'source_branch'],
                         'DEFAULT')
        self._check_pollers()
