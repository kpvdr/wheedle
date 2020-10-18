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

export IMAGE_NAME := wheedle
export INSTALL_DIR := ${HOME}/.local/opt/wheedle
export _TOKEN_FILE := ${TOKEN_FILE}

.PHONY: clean
clean:
	@scripts/clean.sh

,PHONY: install
install:
	@scripts/install.sh

.PHONY: run
run: install
	@cd ${INSTALL_DIR}; ./bin/wheedle

.PHONY: uninstall
uninstall:
	@scripts/uninstall.sh

.PHONY: build-image
build-image:
	@scripts/image.sh build

.PHONY: delete-image
delete-image:
	@scripts/image.sh delete

.PHONY: run-image
run-image:
	@scripts/image.sh run

.PHONY: stop-image
stop-image:
	@scripts/image.sh stop

.PHONY: help
help:
	@echo "Locally run:"
	@echo "    clean        - Remove persistent data"
	@echo "    install      - Install application to ${INSTALL_DIR}"
	@echo "    run          - Run application"
	@echo "    uninstall    - Uninstall application from ${INSTALL_DIR}"
	@echo ""
	@echo "Containers:"
	@echo "    build-image  - Build the image"
	@echo "    delete-image - Delete the image"
	@echo "    run-image    - Run the image in a container"
	@echo "    stop-image   - Stop the running container"
	@echo ""
	@echo "    help         - Display this help"
