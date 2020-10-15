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

FROM fedora

# Required packages
RUN dnf install -y git make python3-requests

WORKDIR /build
RUN git clone https://github.com/kpvdr/wheedle.git
WORKDIR wheedle
RUN mkdir data
COPY data/token data
ENV TOKEN_FILE=/build/wheedle/data/token
RUN make clean uninstall install INSTALL_DIR=/app
WORKDIR /app
ENV PYTHONPATH=/app/wheedle
CMD ["python3",  "-m", "wheedle.app"]
