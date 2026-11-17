# Changelog

All notable changes to Sleep Control are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Tray icon that shows whether sleep is blocked, with Allow sleep, Keep awake, Sleep now, Show window and Quit in its menu.
- A small window with the same buttons. It opens from the app launcher, which helps on desktops without a tray.
- Terminal commands: `flatpak run io.github.ghost_hackers.sleep-control on`, `off`, `now`, `status` and `--version`. They talk to the running app and start it for `on`.
- Keep awake blocks idle sleep and suspend through the desktop's Inhibit portal. The block ends when you allow sleep or quit the app, and also when the app is stopped or crashes.
- One copy runs per session. Starting it again opens the window of the copy that is already running.

[Unreleased]: https://github.com/Ghost-Hackers/sleep-control/commits/master

[![Back to top](https://img.shields.io/badge/Back%20to%20top-222?style=plastic&logo=github)](#changelog)
