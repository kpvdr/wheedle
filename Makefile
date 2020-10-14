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

.EXPORT_ALL_VARIABLES:
INSTALL_DIR := ${HOME}/.local/opt/wheedle
_TOKEN_FILE := ${TOKEN_FILE}

.PHONY: clean
clean:
	@scripts/clean.sh

,PHONY: install
install:
	@scripts/install.sh

.PHONY: run
run: install
	cd ${INSTALL_DIR}; python3 -m wheedle.app

.PHONY: uninstall
uninstall:
	@scripts/uninstall.sh

.PHONY: help
help:
	@echo "    clean     - Remove persistent data"
	@echo "    install   - Install application to ${INSTALL_DIR}"
	@echo "    run       - Run application"
	@echo "    uninstall - Uninstall application from ${INSTALL_DIR}"
	@echo "    help      - Display this help"
