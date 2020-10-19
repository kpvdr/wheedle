#!/usr/bin/python3
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
Common classes used by the various pollers.
"""

import abc as _abc
import logging as _logging

import fortworth as _fortworth
import wheedle.errors as _errors
import wheedle.gh_api as _gh_api



class Poller:
    """ Parent class for pollers that polls a GitHub repository for events or artifacts """

    def __init__(self, config, name):
        self._config = config
        self._name = name
        self._repo = _gh_api.GhRepository.create_repository(config, name)
        self._log = _logging.getLogger('{}.{}'.format(self.__class__.__name__, name))
        if self._repo.is_disabled():
            raise _errors.DisabledRepoError(self._config.full_name())
        self._read_data()

    def start(self, sch=None):
        """ Start poller """
        next_polling_interval = self._polling_interval_secs(self.poll())
        if sch is not None:
            self._log.info('Waiting for next poll in %d secs...', next_polling_interval)
            sch.enter(next_polling_interval, 1, self.start, (sch, ))

    # Some common configuration value convenience methods

    def _data_file_name(self):
        return _fortworth.join(self._config.data_dir(), self._poller_config()['data_file_name'])

    def _poller_config(self):
        """ Config for this poller """
        return self._config[self._name]

    def _polling_interval_secs(self, error_flag):
        if error_flag:
            return int(self._poller_config()['error_polling_interval_secs'])
        return int(self._poller_config()['polling_interval_secs'])

    def _source_branch(self):
        return self._poller_config()['source_branch']

    @_abc.abstractmethod
    def poll(self):
        """ Perform poll task  """

    @_abc.abstractmethod
    def _read_data(self):
        """ Read persistent data from data file """

    @_abc.abstractmethod
    def _write_data(self):
        """ Write persistent data to data file """
