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

import fortworth as _fortworth
import wheedle.artifact_poller as _apoller
import wheedle.commit_poller as _cpoller
import wheedle.configuration as _config
import wheedle.errors as _errors



# pylint: disable=too-few-public-methods
class Application:
    """ Poller application """

    def __init__(self, home, data_dir=None, config_file=None):
        self._home = home
        self._log = _logging.getLogger(self.__class__.__name__)
        self._process_list = []
        config_file = config_file if config_file is not None else _fortworth.join(home,
                                                                                  'wheedle.conf')
        self._config = _config.Configuration(config_file, data_dir)
        try:
            _logging.basicConfig(level=self._config['Logging']['default_log_level'],
                                 format='%(asctime)s  %(name)s - %(levelname)s: %(message)s',
                                 datefmt='%Y-%m-%d %H:%M:%S %Z')
        except ValueError as err:
            raise _errors.ConfigFileError(self._config.config_file_name(), 'Logging', err)
        self._log.info('Data directory: %s', self._config.data_dir())

    def run(self):
        """ Run the application. This starts each of the configured artifact and commit pollers """
        try:
            self._start_pollers(self._config.poller_names())

            # Wait for processes to terminate
            for process in self._process_list:
                process.join()
        except _errors.PollerError as err:
            self._log.error(err)
            _fortworth.exit(1)
        except KeyboardInterrupt:
            print(' KeyboardInterrupt')
        self._log.info('exit')

    def _start_pollers(self, poller_name_list):
        for poller_name in poller_name_list:
            ap_event = None
            if self._config.has_commit_poller(poller_name):
                ap_event = _mp.Event()
                self._start_commit_poller(poller_name, ap_event)
            self._start_artifact_poller(poller_name, ap_event)

    def _start_artifact_poller(self, name, ap_event):
        """ Start the named artifact poller """
        artifact_poller_process = _mp.Process(target=_apoller.ArtifactPoller.run,
                                              args=(self._config, name, ap_event),
                                              name=name + '-AP')
        artifact_poller_process.start()
        self._process_list.append(artifact_poller_process)

    def _start_commit_poller(self, name, ap_event):
        """ Start the named commit poller """
        commit_poller_process = _mp.Process(target=_cpoller.CommitPoller.run,
                                            args=(self._config, name, ap_event),
                                            name=name + '-CP')
        commit_poller_process.start()
        self._process_list.append(commit_poller_process)




if __name__ == '__main__':
    try:
        APP = Application(_fortworth.current_dir())
        APP.run()
    except _errors.PollerError as err:
        print(err)
        _fortworth.exit(1)
