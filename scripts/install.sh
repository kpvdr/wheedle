#! /bin/bash

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

if [[ ! -e ${INSTALL_DIR}/wheedle/app.py ]]; then
  mkdir -p ${INSTALL_DIR}/bin
  cp bin/wheedle ${INSTALL_DIR}/bin/
  mkdir -p ${INSTALL_DIR}/data
  cp data/wheedle.conf ${INSTALL_DIR}/data
  mkdir -p ${INSTALL_DIR}/python/wheedle
  cp python/*.py ${INSTALL_DIR}/python/
	cp python/wheedle/*.py ${INSTALL_DIR}/python/wheedle/
  if [[ -n ${_TOKEN_FILE} ]]; then
    if [[ -f ${_TOKEN_FILE} ]]; then
      cp ${_TOKEN_FILE} ${INSTALL_DIR}/data/
    else
      echo "WARNING: ${_TOKEN_FILE} does not exist or is not a file, token not copied to ${INSTALL_DIR}/data."
    fi
  else
    echo "WARNING: \${TOKEN_FILE} not set, token not copied to ${INSTALL_DIR}/data."
  fi
	echo "Installed to ${INSTALL_DIR}"
fi
