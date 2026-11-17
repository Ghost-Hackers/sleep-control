# Reviewing

What a change to Sleep Control has to meet before it merges. A change that breaks one of these rules is a finding.

## Contents

- [App rules](#app-rules)
- [Tests](#tests)
- [Changes](#changes)

## App rules

- The app never leaves a sleep block behind. Quitting, a signal or a crash releases it.
- It never touches an inhibit it didn't create.
- Sleep now suspends only when the user asks for it.
- The control socket stays private to the user.
- Flatpak permissions stay at the least the app needs. A new entry in the [manifest](../packaging/flatpak/io.github.ghost_hackers.sleep-control.yml) needs a reason in the pull request and in the [README](../README.md#how-it-works).

## Tests

Each change comes with a test in [tests/](../tests), and the test drives the real thing: the app and the command line run as their own processes, D-Bus calls go to the session's portal and to logind, and blocks are checked in PowerDevil's list. Nothing is mocked or replaced for a test. A line no test can reach goes into [tests/unreachable.tsv](../tests/unreachable.tsv) with the reason and the proof, and `tools/test.sh --coverage` holds the rest at 100% branch coverage. A crash fix gets a regression test. Docs and workflow changes need none.

## Changes

- Every fix and feature has an issue, and its commit says `Fixes #n` or `Refs #n`.
- User-visible changes update [CHANGELOG.md](../CHANGELOG.md). Otherwise the pull request carries the `no changelog` label.
- A new version in [`__init__.py`](../src/sleep_control/__init__.py) comes with its release in the [metainfo](../data/io.github.ghost_hackers.sleep-control.metainfo.xml), and with its CHANGELOG section before it is tagged. Versions follow semver and are never reused.
- Python passes Ruff and Pyright in strict mode, and shell passes ShellCheck. [tools/lint.sh](../tools/lint.sh) runs all three.
- Workflows pin actions to a commit and ask for the least permissions they need.

[![Back to top](https://img.shields.io/badge/Back%20to%20top-222?style=plastic&logo=github)](#reviewing)
