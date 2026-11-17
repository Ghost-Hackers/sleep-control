# Sleep Control

Sleep Control keeps a Linux PC awake while something long is running, like a download, a backup, a game update or a big build, and lets it sleep again when you say so. Without it you either dig through the power settings before every long job or come back to a machine that suspended halfway.

The app code is about to land in this repository. Until then there is nothing to install.

## Contents

- [What 0.1.0 will do](#what-010-will-do)
- [Where it is going](#where-it-is-going)
- [Status](#status)
- [Development tools](#development-tools)
- [License](#license)

## What 0.1.0 will do

The first release is deliberately small. Sleep Control will sit in the system tray, show whether sleep is blocked, and offer three actions: Keep awake, Allow sleep and Sleep now. A small window has the same buttons, which helps on desktops that have no tray. The same actions will work from the command line, so a script can keep the PC awake for the length of a job.

It will ship as a Flatpak, and each release will be published on GitHub.

## Where it is going

After 0.1.0 the plan is timers and conditions for keeping the PC awake, settings and start at login, update checks with notifications and optional auto-update, and schedules. Steam Deck Game Mode and every major Linux desktop follow, along with translations, and Flathub comes at 1.0. Each theme is a [milestone](https://github.com/Ghost-Hackers/sleep-control/milestones) with its open issues.

## Status

Sleep Control is in development and hasn't had a release yet. The features above arrive with 0.1.0.

## Development tools

The repository starts with the dev tooling. You need Python 3. Ruff, ShellCheck and PyQt6 come from pip.

```sh
tools/setup-dev.sh   # creates .venv with the tools pinned in requirements-dev.txt
tools/lint.sh        # Ruff for Python, ShellCheck for the shell scripts
tools/test.sh        # runs the tests
```

The scripts share [`tools/env.sh`](tools/env.sh), and the Ruff settings are in [`ruff.toml`](ruff.toml). Bugs and ideas go through the [issue forms](.github/ISSUE_TEMPLATE).

## License

Free to use and to share unchanged; changes need written permission. The full terms are in [LICENSE](LICENSE).

[![Back to top](https://img.shields.io/badge/Back%20to%20top-222?style=plastic&logo=github)](#sleep-control)
