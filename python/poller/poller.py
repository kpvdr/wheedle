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

import poller.errors as _errors
import poller.gh_api as _gh_api



class Poller:
    """ Parent class for pollers that polls a GitHub repository for events or artifacts """

    def __init__(self, repo_data, poller_data):
        self._repo_data = repo_data
        self._poller_data = poller_data
        self._repo = _gh_api.GhRepository.create_repository(repo_data)
        self._log = _logging.getLogger(self.__class__.__name__)
        if self._repo.is_disabled():
            raise _errors.DisabledRepoError(self._repo_data.full_name())
        self._read_data()

    def start(self, polling_interval, error_polling_interval=None, sch=None):
        """ Start poller """
        if self.poll() and error_polling_interval is not None:
            next_polling_interval = error_polling_interval
        else:
            next_polling_interval = polling_interval
        if sch is not None:
            self._log.info('Waiting for next poll in %d secs...', next_polling_interval)
            sch.enter(next_polling_interval, 1, self.start, (polling_interval,
                                                             error_polling_interval,
                                                             sch, ))

    @_abc.abstractmethod
    def poll(self):
        """ Perform poll task  """

    @_abc.abstractmethod
    def _read_data(self):
        """ Read persistent data from data file """

    @_abc.abstractmethod
    def _write_data(self):
        """ Write persistent data to data file """
