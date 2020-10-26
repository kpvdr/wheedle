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
- [**Requests**](https://requests.readthedocs.io/en/master/) - This is packaged on some distros (such as
  Fedora) but must be installed using `pip install --user requests` on those where this is not the
  case.
- [**Podman**](https://podman.io/) - Packaged on most distros. This is needed if building or using
  containers
- [**Python 3**](https://www.python.org/)

## Building and installing
```
git clone https://github.com/kpvdr/wheedle.git
make install
```

**NOTE:** A Personal Access Token file should exist named `token` and which should be pointed to in
an environment variable `${TOKEN_FILE}` prior to running `make install` or `make run` (see
[Requirements](#requirements) above). If this variable does not exist, or the token file is not
present, then it will *NOT* be copied to the installation location (there will be a warning), and an
attempt to run the application will produce a `TokenNotFoundError`. The token will need to be
copied manually to `${HOME}/.local/opt/wheedle/data` (or `${INSTALL_DIR}/data` if you specified a
different install directory) before the application can be run.

## Configuration
Configuration is by a text configuration file (by default `wheedle.conf` in the home directory),
and is formatted as an
[INI File](https://docs.python.org/3/library/configparser.html#supported-ini-file-structure).

In the following tables, there are references to two GitHub repositories:
 - **Source repository:** The repository containing the source code, and which the
   ***commit poller*** polls for new commits;
 - **Build repository:** The repository which builds the source code to produce ***artifacts***, and
   which the ***artifact poller*** polls for new artifacts. The Build Actions workflow in this
   repository is triggered by the *commit poller* when a new commit is detected.

### Configuration File Sections
The following sections are defined by wheedle:
| Section Name | Req'd | Description |
| --- | :---: | --- |
| `Local` | Y | Local server configuration |
| `GitHub` | Y | GitHub configuration |
| `Logging` | Y | Logging configuration |
| `DEFAULT` | | Optional section which sets default values for all following poller sections. If not set here, then some of these must be set in the individual poller sections which follow. Values set here can also be overridden in the following poller sections. **NOTE:** This section MUST appear above the poller sections. |
| `[<poller-name>]` | Y | Section which describes a poller. Any section name not used above is valid. Each poller must have a unique name. At least one poller section must be present. |

### `Local` Section
Describes settings local to the server.
| Key Name | Req'd | Description |
| --- | :---: | --- |
| `data_dir` | Y | Name of data directory relative to the install directory. |

### `GitHub` Section
Describes GitHub global settings and authorization token.
| Key Name | Req'd | Description |
| --- | :---: | --- |
| `api_auth_uid` | Y | Authorization ID associated with the token. See [Requirements](#requirements) above. |
| `gh_api_token_file_name`| Y | The name of the file in the data directory (see `[Local].data_dir` above) which contains the token. This is saved as a hex string with no whitespace. See [Requirements](#requirements) above. |
| `service_url` | Y | Service URL for the GitHub API. |

### `Logging` Section
This section sets logging preferences for Wheedle.
| Key Name | Req'd | Description |
| --- | :---: | --- |
| `default_log_level` | Y | Sets the logging level for output to cout. The possible values are: `CRITICAL`, `ERROR`, `WARNING`, `INFO`, `DEBUG`, `NOTSSET`. Default: `INFO`. See [Logging Levels](https://docs.python.org/3/library/logging.html#logging-levels) in the Python 3 documentation. |

### `DEFAULT` Section
Optional section which sets default values for all following poller sections which describe specific pollers. If not set here, then some of these must be set in the individual poller sections which follow. Values set here can also be overridden in the following poller sections.
**NOTE:** This section must be placed *above* the poller sections.

### Poller Section
Each section that follows names an Artifact Poller and, optionally, a Commit Poller as a pair. Any name not described above is valid, and each named poller (pair) must be unique. The keys in each of these sections will determine whether a Commit Poller will be run alongside the Artifact Poller:

#### Artifact Poller Keys
The following keys describe the characteristics of an Artifact Poller which polls for new build artifacts on a GitHub *build repository*:
| Key Name | Req'd | Description |
| --- | :---: | --- |
| build_repo_owner | Y | Owner of GitHub repository which builds the artifacts through GitHub Actions. |
| build_repo_name | Y | Name of GitHub repository which builds the artifacts through GitHub Actions. |
| bodega_url | Y | URL for the Bodega artifact storage service. |
| stagger_url | Y | URL for the Stagger artifact tagging service. |
| polling_interval_secs| Y | Polling interval for the poller in seconds. Value must be an integer. |
| error_polling_interval_secs | Y | Polling interval for the poller in seconds when there is a connection error to the Bodega / Stagger services. This allows for a much shorter time between attempts to connect than a standard polling interval (polling_interval_secs). Value must be an integer. |
| source_branch | Y | Git branch being built and polled for new commits. |
| stagger_tag | Y | Stagger tag used for tagging artifacts. |
| build_artifact_name_list | Y | String representing a JSON list of strings containing names of artifacts to be downloaded and processed if found. Wildcards are allowed. |
| last_build_hash_artifact_name | | Name of the last commit hash JSON file to be written and read from the data directory. By default, it is `commit-hash.<poller-name>.json`. |
| artifact_poller_data_file_name | | Name of the artifact poller persistence file in the data directory. By default, it is `artifact-poller.<poller-name>.json`. |
| build_download_limit | | Limits the number of previous successful and completed GitHub Actions workflows to download that have not been previously seen. This prevents a large number of older artifacts from being downloaded into Bodega which may not be useful. If not set, then all successful workflows which contain artifacts in the last 50 will be downloaded. |

#### Commit Poller Keys
The following optional keys, if present in a Poller Section, describe the characteristics of a Commit Poller that polls for new commits in a GitHub *source repository*. If one or more new commits are found, a build is triggered on the build repository polled by the Artifact Poller.
| Key Name | Req'd | Description |
| --- | :---: | --- |
| source_repo_owner | | Owner of GitHub repository which contains the source code checked out into the Build Repository and which are built to create artifacts. **NOTE:** If this is present, then so must source_repo_name (below) be, and a Commit Poller will be run. |
| source_repo_name | | Name of GitHub repository which contains the source code checked out into the Build Repository and which are built to create artifacts. **NOTE:** If this is present, then so must source_repo_owner (above) be, and a Commit Poller will be run. |
| trigger_dry_run | | Disable actual build trigger, but will log a trigger as a dry run. This is to conserve GitHub resources while testing / debugging. Valid values: `true`, `yes`, `1`, and are case-insensitive. Any value not in this list, or the lack of this key will be considered false/off, and actual GitHub Actions builds will be initiated. |
| commit_poller_data_file_name | | Name of the commit poller persistence file in the data directory. By default, it is `commit-poller.<poller-name>.json`. |

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
To stop, use `ctrl+C` or send a `TERM` signal to the process.

#### Running in a Docker container
The container uses the latest version of Fedora.

1. First build a container image with `make build-image`. This may take a minute or so to complete.
1. Once built, the container can be run and stopped as often as needed with `make run-image` and
   `make stop-image` respectively.
1. An image can be deleted with `make delete-image`. This must be done before a new image can be
   built. While a container is running, it is not possible to delete the image, so make sure it is
   first stopped.

## Persistent Data
Persistent data which is re-loaded each time the application is started, is saved in `DATA_DIR`
(`${HOME}/.local/opt/wheedle` by default). The data files are named
`artifact-poller.<poller-name>.json` and `commit-poller.<poller-name>.json` by default, but each
poller section in the configuration file can set a unique name for these files. In addition, the
last build commit hash is saved in a file named `last_build_hash.<poller-name>.json`.

Persistent data may be cleared by deleting the JSON files (`*.json`) in `DATA_DIR`, or by running
`make clean`. **WARNING:** Do not delete data directory or the Personal Access Token file `token`
which is located in this directory. The application will not run without this file.

## Troubleshooting

### Errors
Error | Possible cause
------|---------------
`ConfigFileError` | An error in the configuration file. See [Configuration](#configuration) above.
`GhConnectionRefusedError` | The URL for GitHub APIs is invalid. Check the value in the configuration file for `[GitHub].service_url`.
`HttpError` | For **401 (Unauthorized)**, the GitHub authorization is invalid. Check the values in the configuration file for `[GitHub].api_auth_uid` and `[GitHub].gh_api_token_file_name`, and make sure the token stored in the named file is correct. For **404 (Not Found)**, the name of the repository owner and/or repository are invalid. Check the values in the configuration file for `[<PollerNmae>].repo_owner` and `[<PollerNmae>].repo_name`.
`ServiceConnectionError` | Either or both the Stagger and Bodega services could not be reached from the pollers. Check the `BODEGA_URL` and `STAGGER_URL` settings, and make sure that these are running and are accessible on the network from the poller machine.
`TokenNotFoundError` | The GitHub token file was not found. Check `[GitHub].gh_api_token_file_name` in the configuration file. See [Requirements](#requirements) above for information on GitHub access tokens.

### Other Issues
 - **Build not triggered when commits found:** This can happen if the commit poller has been configured to use dry runs. Because GitHub resources are limited and expensive, it is possible to disable an actual trigger when testing a configuration or debugging. This is done by setting the key `trigger_dry_run` to 'true', 'yes' or '1' under a given commit poller. Check the logs where a commit is found. The commit list should be followed by the string:
```
INFO: Build triggered on "<artifact-poller-name>" (DRY RUN)
```
If the trigger is real (not a dry run), the the `(DRY RUN)` suffix is omitted. Check the configuration file, and either remove the `trigger_dry_run` key, or set its value to 'false'.
