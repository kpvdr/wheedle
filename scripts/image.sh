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

function image_exists {
  podman images ${IMAGE_NAME} | grep ${IMAGE_NAME} > /dev/null
  return $?
}

function container_exists {
  podman ps -a | grep ${IMAGE_NAME} > /dev/null
  return $?
}

function container_id {
  local cid=`podman ps -a | grep ${IMAGE_NAME} | awk '{print $1;}'`
  echo "${cid}"
}

function build {
  if ! image_exists; then
    echo "Building image for \"${IMAGE_NAME}\"..."
    podman build -qt ${IMAGE_NAME} .
  else
    echo "Image \"${IMAGE_NAME}\" already exists, first delete"
  fi
}

function delete {
  if image_exists; then
    if ! container_exists; then
      podman rmi ${IMAGE_NAME}
      echo "Image \"${IMAGE_NAME}\" deleted"
    else
      local cid=$(container_id)
      echo "Image \"${IMAGE_NAME}\" running in container $cid, stop before deleting"
    fi
  else
    echo "No image \"${IMAGE_NAME}\" found"
  fi
}

function run {
  if image_exists; then
    if ! container_exists; then
      echo "Starting container with \"${IMAGE_NAME}\""
      podman run --rm --network host ${IMAGE_NAME} &
    else
      local cid=$(container_id)
      echo "Container ${cid} with \"${IMAGE_NAME}\" already running"
    fi
  else
    echo "No image \"${IMAGE_NAME}\" found, first build"
  fi
}

function stop {
  if container_exists; then
    local cid=$(container_id)
    echo "Stopping ${cid}..."
    podman stop ${cid}
  else
    echo "No running container with \"${IMAGE_NAME}\" found"
  fi
}

case "$1" in
  build)
    build
    ;;
  delete)
    delete
    ;;
  run)
    run
    ;;
  stop)
    stop
    ;;
  *)
    echo "Unknown option $1"
    exit 1
esac
