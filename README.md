# Wheedle

*wheedle* (v): to influence or entice by soft words or flattery

## Introduction
This project independently polls a pair of GitHub repositories, one for for new commits in order to
trigger a GitHub Action on the second, and the second for new GitHub Actions artifacts.

This application will find use primarily in CI/CD projects where some or all of the package
builds are made on GitHub Actions projects created for the purpose of building and testing
one or more packages. As it is inadvisable to leave credentials for the GitHub build project to
notify a private or secure system, this project can be run from a secure location to poll for
the availability of artifacts on a regular basis, and download them when found.

This project contains two pollers:

#### 1. Commit Poller
This poller will check for commits in any GitHub repository. It is typically used to monitor a
repository that contains the source code for which a second GitHub repository exists to build
packages for the source project and test them. As there may be no direct connection between these
GitHub repositories, it may be difficult to trigger a build action on the build repository from
commits made on the source repository.

The commit poller will check for new commits since the last successful build was made by
comparing the commit hashes in the Git commit log. If a new commit is detected since the last
successful build, a build action is triggered on the build repository's actions.

#### 2. Artifact Poller
This poller will check for new GitHub Actions artifacts which may become available. The poller is
run at a regular interval, and keeps track of artifacts it has already seen so as to avoid
downloading duplicate artifacts.

If a new artifact is found, it is downloaded into a temporary location, and then pushed into the
Bodega artifact server. Tagged metadata is then sent to the Stagger artifact tagging and
notification service.

## Requirements
- A **GitHub Personal Token** which will be used for GitHub API calls to the repositories. See
[Creating a personal access token](https://docs.github.com/en/free-pro-team@latest/github/authenticating-to-github/creating-a-personal-access-token)
for instructions on how to do this. Copy the token into a file named `token` which will be located
in the `DATA_DIR` directory. You can rename this, but make sure to change the configuration
(see [Configuration](#configuration) below) to reflect the new name.

## Dependencies
- **Requests** (https://requests.readthedocs.io/en/master/) - This is packaged on some distros (such as
  Fedora) but must be installed using `pip install --user requests` on those where this is not the
  case.
- **Podman** (https://podman.io/) - Packaged on most distros. This is needed if building or using
  containers
- **Python 3**

## Building and installing
```
git clone https://github.com/kpvdr/wheedle.git
make install
```

## Configuration
Configuration is by a text configuration file (by default `wheedle.conf`), and is formatted as
follows:
```
[section1]
key1 = value1
key2 = value2

[section2]
# Comment
key3 : value1
key4 : multi-line value2 is indented
    on the following lines
...
```
See [Supported INI File Structure](https://docs.python.org/3/library/configparser.html#supported-ini-file-structure)
in the Python 3 documentation for complete details.

In the following tables, there are references to two GitHub repositories:
 - **Source repository:** The repository containing the source code, and which the *commit poller*
   polls for new commits;
 - **Build repository:** The repository which is triggered by the *commit poller*, and which builds
   and tests packages from the source code in the Source Repository. The *artifact poller* will
   check this repository's actions for new artifacts and process them in Bodega and Stagger.

### Configuration File Sections
The following sections are defined by wheedle:
| Section Name | Required | Description |
| --- | :---: | --- |
| `Local` | Y | Local server configuration |
| `GitHub` | Y | GitHub configuration |
| `Logging` | Y | Logging configuration |
| `DEFAULT` | | Optional section which sets default values for all following poller sections. If not set here, then some of these must be set in the individual poller sections which follow. Values set here can also be overridden in the following poller sections. **NOTE:** This section MUST appear above the poller sections. |
| `[<poller-name>]` | Section which describes a poller. Any section name not used above is valid. Each poller must have a unique name. The poller type is set by the `class` key which must be in each poller. |

### `Local` Section
| Key Name | Required | Description |
| --- | :---: | --- |
| `Local` | | Y | Local server configuration |
| `data_dir` | Y | Name of data directory relative to the home directory. Default: `data` |

### `GitHub` Section
| Key Name | Required | Description |
| --- | :---: | --- |
| `api_auth_uid` | Y | Authorization ID associated with the token. See [Requirements](requirements) above. |
| `gh_api_token_file_name`| Y | Name of file containing token in the data directory. See [Requirements](requirements) above. |
| `service_url` | Y | Service URL for the GitHub API. |

### `Logging` Section
| Key Name | Required | Description |
| --- | :---: | --- |
| `default_log_level` | Y | Logging level, one of `CRITICAL`, `ERROR`, `WARNING`, `INFO`, `DEBUG`, `NOTSSET`. Default: `INFO`. See [Logging Levels](https://docs.python.org/3/library/logging.html#logging-levels) in the Python 3 documentation. |

### `DEFAULT` Section
Optional section which sets default values for all following poller sections which describe specific pollers. If not set here, then some of these must be set in the individual poller sections which follow. Values set here can also be overridden in the following poller sections. Typically included values which apply to both ArtifactPollers and CommitPollers are `polling_interval_secs`, `error_polling_interval_secs` and `source_branch`. See below for descriptions of these keys.

### Poller Section
Section which describes a poller. Any section name not described above is valid. Each poller must have a unique name. The poller type is set by the `class` key which must be in each poller.
| Key Name | Required | Description |
| --- | :---: | --- |
| `class` | Y | Poller class or type, and MUST be one of `CommitPoller` to describe a commit poller, or `ArtifactPoller` to describe an artifact poller. Any other values are invalid. |
| `repo_owner` | Y | Git repository owner for the source repository (for commit pollers) or the build repository (for artifact pollers) |
| `repo_name` | Y | Git repository name for the source repository (for commit pollers) or the build repository (for artifact pollers) |
| `start_delay_secs` | | If present, the delay in starting the poller in seconds. This can be used to allow the commit poller to wait until the artifact poller has downloaded the last commit hash artifact before checking for new commits. This delay only occurs when wheedle is started. |
| `data_file_name` | | The name of the JSON file in the data directory which contains persistent data for this poller. When each poller is started, this file will be read to obtain its persistent state. Each time an update to the state occurs, this file will be saved. |
| `polling_interval_secs` | Y | Polling interval in seconds. The period which each poller waits before polling again. This value is typically included in the `DEFAULT` section if several pollers share the same polling interval. |
| `error_polling_interval_secs` | Y | Polling interval in seconds when a service error exists. This is typically the unavailability of services such as Stagger and Bodega for Artifact pollers. As long as these services are not available, this polling interval is used until service is restored. This allows for an error condition to be corrected without having to wait hours before another poll takes place. This value is typically included in the `DEFAULT` section if several pollers share the same error polling interval. |
| `source_branch` | Y | Default Git source branch. This is used for tagging and commit polling. This value is typically included in the `DEFAULT` section if several pollers use the same source branch. |

### Artifact Pollers
The following keys are for artifact pollers only:
| Key Name | Required | Description |
| --- | :---: | --- |
| `build_artifact_name_list` | Y | JSON list of artifacts which will be downloaded from GitHub. Wildcard `*` is valid. Those artifacts not matching this list will be ignored. |
| `last_build_hash_file_name` | Y | Name of artifact containing the last commit hash. This is in addition to the files listed in `build_artifact_name_list` above. |
| `stagger_tag` | Y | The tag which will be used to tag this artifact in Stagger. Usually `untested` or `tested`. |
| `bodega_url` | Y | URL of the Bodega file archive service. Must be reachable on the network from the wheedle server. |
| `stagger_url` | Y | URL of the Stagger file tagging service. Must be reachable on the network from the wheedle server. |
| `build_download_limit` | | Optional limit on the number of workflows to download. The artifact poller will identify the last 50 workflows and will download all those containing artifacts in chronological order (which is usually by order of the run number). However, this can result in an excessive number of artifact downloads for older workflows. If this limit is set, then the poller will identify this number of successful workflows, and will start downloading from that workflow. |

### Commit Pollers
The following keys are for commit pollers only:
| Key Name | Required | Description |
| --- | :---: | --- |
| `trigger_artifact_poller` | Y | The name of the corresponding artifact poller that will be triggered when a new commit is detected. |

## Installing, Running and Stopping
#### Running in local environment
Install is performed when first running, and is located at `${HOME}/.local/opt/wheedle`.
```
make run
```
However, install can be performed separately by running `make install` first. An alternative install
location may be specified by adding `INSTALL_DIR=/another/path` after each make statement, ie:
```
make run INSTALL_DIR=/my/new/path
```
To stop, use `ctrl+C` or send a `TERM` signal.

#### Running in a Docker container
The container uses the latest version of Fedora.

1. First build a container image with `make build-image`. This may take a minute or so to complete.
1. Once built, the container can be run and stopped as often as needed with `make run-image` and
   `make stop-image` respectively.
1. An image can be deleted with `make delete-image`. This must be done before a new image can be
   built.

#### Personal Access Token
**NOTE:** A Personal Access Token file should exist named `token` and which should be pointed to in
an environment variable `${TOKEN_FILE}` prior to running `make install` or `make run` (see
[Requirements](#requirements) above). If this variable does not exist, or the token file is not
present, then it will *NOT* be copied to the installation location (there will be a warning), and an
attempt to run the application will produce a `TokenNotFoundError`. The token will need to be
copied manually to `${HOME}/.local/opt/wheedle/data` (or `${INSTALL_DIR}/data` if you specified a
different install directory) before the application can run.

## Persistent Data
Persistent data which is re-loaded each time the application is started, is saved in `DATA_DIR`
(`${HOME}/.local/opt/wheedle` by default).

Persistent data may be cleared by deleting the JSON files (`*.json`) in `DATA_DIR`, or by running
`make clean`. **WARNING:** Do not delete the Personal Access Token file `token` which is also
located in this directory. The application will not run without this file.

## Persistence Files
Name | Type | Description
-----|------|------------
artifact_id.json | JSON | A list of artifact ids previously seen indexed by run number.
commit_hash.json | JSON | The commit hash of the last build. This is uploaded as an artifact.

## Troubleshooting
Error | Possible cause
------|---------------
`ConfigFileError` | An error in the configuration file. See [Configuration](#configuration) above.
`GhConnectionRefusedError` | The URL for GitHub APIs is invalid. Check the value in the configuration file for `[GitHub].service_url`.
`HttpError` | For 401 (Unauthorized), the GitHub authorization is invalid. Check the values in the configuration file for `[GitHub].api_auth_uid` and `[GitHub].gh_api_token_file_name`, and make sure the token stored in the named file is correct. For 404 (Not Found), the name of the repository owner and/or repository are invalid. Check the values in the configuration file for `[<PollerNmae>].repo_owner` and `[<PollerNmae>].repo_name`.
`ServiceConnectionError` | Either or both the Stagger and Bodega services could not be reached from the pollers. Check the `BODEGA_URL` and `STAGGER_URL` settings, and make sure that these are running and are accessible on the network from the poller machine.
`TokenNotFoundError` | The GitHub token file was not found. Check `[GitHub].gh_api_token_file_name` in the configuration file. See [Requirements](#requirements) above for information on GitHub access tokens.
