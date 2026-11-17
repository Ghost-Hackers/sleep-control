# Contributing

Thanks for helping with Sleep Control. Every change starts with an issue, so open one (or comment on an existing one) before you write code. That keeps us from duplicating work and gives the commit something to point at.

## Contents

- [Layout](#layout)
- [Development tools](#development-tools)
- [Making a change](#making-a-change)

## Layout

| Path | Contents |
| --- | --- |
| [`src/sleep_control/`](src/sleep_control) | The app package |
| [`tests/`](tests) | Tests |
| [`tools/`](tools) | Setup, test and lint scripts |
| [`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE) | Bug report and feature request forms |

## Development tools

Set up the tools once. [`tools/setup-dev.sh`](tools/setup-dev.sh) creates `.venv` with the versions pinned in [`requirements-dev.txt`](requirements-dev.txt) (PyQt6, Ruff, Pyright and ShellCheck):

```sh
tools/setup-dev.sh
```

[`tools/test.sh`](tools/test.sh) runs the tests and [`tools/lint.sh`](tools/lint.sh) runs Ruff on `src` and `tests`, Pyright in strict mode on the Python code (see [`pyrightconfig.json`](pyrightconfig.json)) and ShellCheck on the shell scripts. Both use `.venv` when it exists; set `PYTHON` to use a different interpreter.

## Making a change

Commit messages reference the issue, for example `Fixes #12` or `Refs #12`. A problem you find along the way gets its own issue, and every change comes with tests.

Report security problems privately, as described in [SECURITY.md](SECURITY.md), not in an issue.

[![Back to top](https://img.shields.io/badge/Back%20to%20top-222?style=plastic&logo=github)](#contributing)
