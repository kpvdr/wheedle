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
Poller for GitHub projects that contain actions and artifacts. This module polls a GitHub project
checking for new artifacts. If found, the poller updates Stagger and sends the artifacts to Bodega.

The artifact ids are saved in a local file data/artifact_id.json.
"""

import fnmatch as _fnmatch
import json as _json
import logging as _logging
import os as _os
import sched as _sched
import shutil as _shutil
import time as _time
import zipfile as _zipfile

import requests as _requests

import fortworth as _fortworth
import wheedle.errors as _errors
import wheedle.gh_api as _gh_api
import wheedle.poller as _poller



LOG = _logging.getLogger('ArtifactPoller')



def remove(path):
    """ Remove a file or directory recursively """
    if not _fortworth.exists(path):
        return
    if _fortworth.is_dir(path):
        _shutil.rmtree(path, ignore_errors=True)
    else:
        _os.remove(path)



# pylint: disable=too-many-arguments
# pylint: disable=too-few-public-methods
# pylint: disable=too-many-instance-attributes
# class ArtifactPollerData:
#     """ Collection of attributes for the artifact poller """
#
#     def __init__(self, source_branch, build_artifact_name_list, bodega_url, stagger_url, tag,
#                  polling_interval, error_polling_interval, data_dir, data_file_name,
#                  last_build_cid_artifact_name):
#         self.source_branch = source_branch
#         self.artifact_name_list = build_artifact_name_list + [last_build_cid_artifact_name]
#         self.bodega_url = bodega_url
#         self.stagger_url = stagger_url
#         self.tag = tag
#         self.polling_interval = polling_interval
#         self.error_polling_interval = error_polling_interval
#         self.data_dir = data_dir
#         self.data_file_name = data_file_name
#         self.last_build_cid_artifact_name = last_build_cid_artifact_name



class ArtifactPoller(_poller.Poller):
    """ Poller which polls for GitHub actions artifacts at a regular interval """

    def __init__(self, config, name):
        self._prev_artifact_ids = {} # JSON artifact list from previous poll
        self._next_artifact_ids = {} # JSON artifact list for next poll
        super().__init__(config, name)

    def poll(self):
        """ Perform poll task. Return True if required services are not running, False otherwise """
        # Check if Bodega and Stagger are running
        try:
            self._check_services_running()
        except _errors.ErrorList as err:
            for err_item in err:
                self._log.warning(err_item)
            return True
        self._log.info(self._repo.to_str())

        # Obtain workflow list for this repository
        workflow_list = self._repo.workflow_list()
        if len(workflow_list) > 0:
            self._log.info('  %s', workflow_list.to_str())
            self._process_workflow_list(workflow_list)

        # Save persistent data from this poll
        self._write_data()
        return False

    def _check_services_running(self):
        """ Check bodega and stagger are running """
        error_list = []

        try:
            build_data = _fortworth.BuildData(self._repo_name(),
                                              self._source_branch(), 0, None)
            _fortworth.bodega_build_exists(build_data, self._bodega_url())
        except _requests.exceptions.ConnectionError:
            error_list.append(_errors.ServiceConnectionError('Bodega', self._bodega_url()))

        try:
            _fortworth.stagger_get_data(self._stagger_url())
        except _requests.exceptions.ConnectionError:
            error_list.append(_errors.ServiceConnectionError('Stagger', self._stagger_url()))
        if len(error_list) > 0:
            raise _errors.ErrorList(error_list)

    def _download_artifact(self, artifact, bodega_artifact_list, bodega_temp_dir):
        try:
            downloaded_filename = artifact.download(bodega_temp_dir,
                                                    self._config.auth())
            if downloaded_filename == self._last_build_hash_file_name():
                self._process_commit_hash(bodega_temp_dir)
            bodega_artifact_list.append((artifact, downloaded_filename))
        except _requests.exceptions.ConnectionError:
            self._log.warning( \
                '    %s - ERROR: Bodega not running or invalid Bodega URL %s',
                artifact.to_str(), format(self._bodega_url()))
        except _errors.PollerError as err:
            self._log.warning('    %s - %s', artifact.to_str(), err)
        else:
            self._log.info('    %s - ok', artifact.to_str())

    def _is_in_bodega(self, wf_item):
        """ Check if a workflow item's run number is in bodega """
        build_data = _fortworth.BuildData(self._repo.name(), self._source_branch(),
                                          wf_item.run_number(), None)
        return _fortworth.bodega_build_exists(build_data, self._bodega_url())

    def _is_needed_artifact(self, artifact_name):
        """ Check if an artifact is in the list of needed artifacts """
        if artifact_name == self._last_build_hash_file_name():
            return True
        artifact_list = _fortworth.read_json(self._build_artifact_name_list())
        for needed_artifact in artifact_list:
            if _fnmatch.fnmatch(artifact_name, needed_artifact):
                return True
        return False

    def _process_artifacts(self, wf_item):
        """ Filter, download needed artifacts, push them to Bodega, and tag in Stagger """
        run_number_str = str(wf_item.run_number()) # JSON uses only strings as keys
        first_in = True
        bodega_artifact_list = []
        bodega_temp_dir = _fortworth.make_temp_dir(suffix='-{}'.format(run_number_str))
        for artifact in wf_item:
            if first_in:
                self._log.info('    %s', _gh_api.GhArtifactItem.hdr())
                first_in = False
            if self._is_needed_artifact(artifact.name()) and not artifact.expired():
                if run_number_str not in self._prev_artifact_ids or \
                    artifact.id() not in self._prev_artifact_ids[run_number_str]:
                    self._download_artifact(artifact, bodega_artifact_list, bodega_temp_dir)
                else:
                    self._log.info('    %s - previously downloaded', artifact.to_str())
                if run_number_str not in self._next_artifact_ids:
                    self._next_artifact_ids[run_number_str] = [artifact.id()]
                elif artifact.id() not in self._next_artifact_ids[run_number_str]:
                    self._next_artifact_ids[run_number_str].append(artifact.id())
            else:
                self._log.info('    %s - ignored or expired', artifact.to_str())
        if len(bodega_artifact_list) > 0:
            bodega_artifact_path = self._push_to_bodega(wf_item, bodega_temp_dir)
            self._push_to_stagger(wf_item, bodega_artifact_list, bodega_artifact_path)
        remove(bodega_temp_dir)

    def _process_commit_hash(self, bodega_temp_dir):
        """ Extract zipped commit-id json file into data dir """
        zip_file_name = _fortworth.join(bodega_temp_dir,
                                        self._last_build_hash_file_name() + '.zip')
        with _zipfile.ZipFile(zip_file_name, 'r') as zip_obj:
            zip_obj.extractall(path=self._config.data_dir())

    def _process_workflow_list(self, workflow_list):
        """ Find artifacts in each workflow that is not already in Bodega """
        for wf_item in workflow_list:
            if wf_item.has_artifacts():
                try:
                    if not self._is_in_bodega(wf_item):
                        self._log.info('    %s', wf_item.to_str())
                        self._process_artifacts(wf_item)
                    else:
                        self._log.info('    %s - ingored, already in Bodega', wf_item.to_str())
                        # Transfer previously seen artifacts to next list
                        run_number_str = str(wf_item.run_number())
                        if run_number_str in self._prev_artifact_ids:
                            self._next_artifact_ids[run_number_str] = \
                                self._prev_artifact_ids[run_number_str]
                except _requests.exceptions.ConnectionError:
                    self._log.warning('    %s - Bodega not running or invalid Bodega URL %s',
                                      wf_item.to_str(), self._bodega_url())
            else:
                self._log.info('    %s', wf_item.to_str())

    def _push_to_bodega(self, wf_item, bodega_temp_dir):
        """ Push an artifact to Bodega """
        build_data = _fortworth.BuildData(self._repo_name(), self._source_branch(),
                                          wf_item.run_number(), wf_item.html_url())
        try:
            _fortworth.bodega_put_build(bodega_temp_dir, build_data,
                                        service_url=self._bodega_url())
            return _fortworth.join(self._bodega_url(), build_data.repo, build_data.branch,
                                   str(build_data.id))
        except _requests.exceptions.ConnectionError:
            self._log.error('Bodega not running or invalid Bodega URL %s',
                            self._config['Local']['stagger_url'])


    def _push_to_stagger(self, workflow_metadata, bodega_artifact_list, bodega_artifact_path):
        """ Tag an artifact in Stagger """
        stagger_artifact_list = {}
        for artifact, bodega_file_name in bodega_artifact_list:
            stagger_artifact_list[artifact.name()] = {
                'type': 'file',
                'update_time': _gh_api.str_time_to_milli_ts(artifact.created_at()),
                'url': _fortworth.join(bodega_artifact_path, bodega_file_name + '.zip'),
                }
        tag_data = {'update_time': _gh_api.str_time_to_milli_ts(workflow_metadata.updated_at()),
                    'build_id': workflow_metadata.run_number(),
                    'build_url': workflow_metadata.html_url(),
                    'commit_hash': None,
                    'commit_url': None,
                    'artifacts': stagger_artifact_list,
                   }
        try:
            _fortworth.stagger_put_tag(self._repo_name(), self._source_branch(),
                                       self._stagger_tag(), tag_data,
                                       service_url=self._config['Local']['stagger_url'])
        except _requests.exceptions.ConnectionError:
            self._log.error('Stagger not running or invalid Bodega URL %s',
                            self._config['Local']['stagger_url'])

    def _read_data(self):
        """ Read the persistent data for this poller """
        if _fortworth.exists(self._data_file_name()):
            try:
                self._prev_artifact_ids = _fortworth.read_json(self._data_file_name())
            except  _json.decoder.JSONDecodeError as err:
                raise _errors.JsonDecodeError(self._data_file_name(), err)

    def _write_data(self):
        """ Write the persistent data for this poller """
        _fortworth.write_json(self._data_file_name(), self._next_artifact_ids)
        self._prev_artifact_ids = self._next_artifact_ids
        self._next_artifact_ids = {}

    # Configuration convenience methods

    def _bodega_url(self):
        return self._poller_config()['bodega_url']

    def _build_artifact_name_list(self):
        return self._poller_config()['build_artifact_name_list']

    def _last_build_hash_file_name(self):
        return self._poller_config()['last_build_hash_file_name']

    def _repo_name(self):
        return self._poller_config()['repo_name']

    def _stagger_tag(self):
        return self._poller_config()['stagger_tag']

    def _stagger_url(self):
        return self._poller_config()['stagger_url']

    @staticmethod
    def run(config, name):
        """ Convenience method to run the ArtifactPoller on a scheduler """
        LOG.info('Starting artifact poller...')
        try:
            sch = _sched.scheduler(_time.time, _time.sleep)
            artifact_poller = ArtifactPoller(config, name)
            sch.enter(0, 1, artifact_poller.start, (sch, ))
            sch.run()
        except (_errors.PollerError, _json.decoder.JSONDecodeError) as err:
            LOG.error(err)
        except KeyboardInterrupt:
            pass
