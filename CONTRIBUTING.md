# Contributing

Every change starts with an issue. Open one, or comment on an existing one, before you write code.

## Contents

- [Layout](#layout)
- [Build and test](#build-and-test)
- [Making a change](#making-a-change)

## Layout

| Path | Contents |
| --- | --- |
| [`src/sleep_control/`](src/sleep_control) | The app. State, IPC and the command line are plain Python; Qt and D-Bus live in `app.py` and `backend.py` |
| [`data/`](data) | Desktop entry, AppStream metainfo and icons |
| [`docs/`](docs) | The release test plan and the README screenshot |
| [`packaging/flatpak/`](packaging/flatpak) | The Flatpak manifest and the launcher script |
| [`tests/`](tests) | Tests, the test runner and the coverage gate |
| [`tools/`](tools) | Build, test and lint scripts |

## Build and test

Set up the test and lint tools once. [`tools/setup-dev.sh`](tools/setup-dev.sh) creates `.venv` with the versions pinned in [`requirements-dev.txt`](requirements-dev.txt) (PyQt6, coverage.py, Ruff, Pyright and ShellCheck):

```sh
tools/setup-dev.sh
```

The tests run the real app. They start it and the command line as separate processes with a runtime folder of their own, so they never talk to a copy you have installed, and they check blocks in PowerDevil's list. Nothing is mocked. Each test module says which machine it needs in `HOST`, and a module that needs a program beyond the host's own lists it in `NEEDS`. `test_instance_race` and `test_desktop_race` stop an instance right after it takes the lock, so they `NEEDS` `strace`. `test_runner_bus` needs `busctl`, `test_portal_files` needs `prlimit` and `dbus-update-activation-environment`, and `test_e2e_script` needs `unshare` and `ostree`. When a program is missing, `tools/test.sh` skips those modules, says which and why, and still runs the rest:

| Host | Needs | Modules |
| --- | --- | --- |
| `any` | Linux with `dbus-run-session`, `dbus-daemon` and `prlimit`; CI runs these | `test_cli`, `test_instance`, `test_instance_race`, `test_runner`, `test_runner_bus`, `test_coverage_gate`, `test_version`, `test_packaging`, `test_check_release` |
| `kde-session` | A logged-in KDE Plasma session on Wayland: the desktop portal, PowerDevil, the tray and logind, plus `dbus-monitor`, `dbus-send`, `xdg-dbus-proxy` and `kwin_wayland` (`test_desktop` runs it on a virtual screen) | `test_state`, `test_window`, `test_session_app`, `test_stalls`, `test_desktop`, `test_desktop_race`, `test_portal_files` |
| `flatpak` | Flatpak with the SDK, runtime and PyQt6 BaseApp named in the manifest, and the Flatpak portal | `test_flatpak`, `test_e2e_script` |

```sh
tools/test.sh                  # everything this machine can run
tools/test.sh tests.test_cli   # just these modules
tools/test.sh --list           # which modules would run here, and why the others wouldn't
tools/test.sh --all            # everything, and fail if a host is missing
tools/test.sh --coverage       # everything, then the coverage gate
```

Naming a module whose host is missing fails the run instead of skipping it. xdg-desktop-portal keeps a file descriptor for every process that asked it for a block, and a session run leaves about 8 behind. With fewer than 64 left, the runner reports the portal as missing and prints the command that restarts it.

The `flatpak` tests don't build or install anything: [`tests/sandbox.py`](tests/sandbox.py) makes a build folder with `flatpak build-init` and runs the launcher and the code from this checkout in it with `flatpak build`, under an app ID of its own.

The session tests take a block for a few seconds at a time and may pop up the window and a notification. They never suspend: before a test sends Suspend it takes its own logind block lock and checks that logind reports the machine as inhibited, so logind refuses the call.

`--coverage` needs 100% branch coverage of `src/sleep_control`, the app processes included. A line that no test can reach, like the line after a successful suspend, goes into [`tests/unreachable.tsv`](tests/unreachable.tsv) with the reason and the proof. The gate fails if a listed line runs after all.

The release test plan, with the end-to-end script that runs against the installed Flatpak, is in [docs/TESTING.md](docs/TESTING.md).

[`tools/lint.sh`](tools/lint.sh) runs Ruff on `src` and `tests`, Pyright in strict mode on the Python code (see [`pyrightconfig.json`](pyrightconfig.json)) and ShellCheck on the shell scripts. `tools/lint.sh`, `tools/test.sh` and `tools/build.sh` use `.venv` when it exists. Set `PYTHON` to use another interpreter.

[`tools/build.sh`](tools/build.sh) builds the Flatpak. It needs Flatpak Builder, the KDE SDK and the PyQt6 BaseApp:

```sh
flatpak install --user flathub org.flatpak.Builder org.kde.Sdk//6.11 com.riverbankcomputing.PyQt.BaseApp//6.11
tools/build.sh
```

The script checks that the newest release in the metainfo matches the version, runs the tests, and writes `dist/sleep-control-<version>.flatpak` with its `.sha256`. It keeps a copy of both under `prereleases/` or `releases/`, which git ignores like `dist/`. `tools/build.sh --dry-run` only checks the version and the metainfo and prints what it would build. CI runs `tools/build.sh --ci`, which builds in a container and leaves the tests to their own job. The first build takes a few minutes. Install the result with `flatpak install --user` to try it.

## Making a change

Commit messages reference the issue, for example `Fixes #12` or `Refs #12`. A problem you find along the way gets its own issue.

Every change comes with tests. User-visible changes add a line to [CHANGELOG.md](CHANGELOG.md); if users won't notice the change, put the `no changelog` label on the pull request instead. [.github/REVIEWING.md](.github/REVIEWING.md) lists what a change has to meet before it merges.

Report security problems privately, as described in [SECURITY.md](SECURITY.md), not in an issue.

[![Back to top](https://img.shields.io/badge/Back%20to%20top-222?style=plastic&logo=github)](#contributing)
