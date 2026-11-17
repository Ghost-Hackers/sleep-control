# Changelog

All notable changes to Sleep Control are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Sleep Control as a Flatpak app, `io.github.ghost_hackers.sleep-control`, built on the KDE 6.11 runtime with PyQt6.
- Tray icon that shows whether sleep is blocked, with Allow sleep, Keep awake, Sleep now, Show window and Quit in its menu.
- A small window with the same buttons. It opens from the app launcher, which helps on desktops without a tray.
- Terminal commands: `flatpak run io.github.ghost_hackers.sleep-control on`, `off`, `now`, `status` and `--version`. They talk to the running app and start it for `on`.
- Keep awake blocks idle sleep and suspend through the desktop's Inhibit portal. The block ends when you allow sleep or quit the app, and also when the app is stopped or crashes.
- One copy runs per session. Starting it again opens the window of the copy that is already running.
- Keep awake and Allow sleep as quick actions on the app launcher.

[Unreleased]: https://github.com/Ghost-Hackers/sleep-control/commits/master

[![Back to top](https://img.shields.io/badge/Back%20to%20top-222?style=plastic&logo=github)](#changelog)
