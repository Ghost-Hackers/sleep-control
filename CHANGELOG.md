# Changelog

All notable changes to Sleep Control are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## Contents

- [Unreleased](#unreleased)
- [0.1.0-beta.1](#010-beta1---2026-11-19)

## [Unreleased]

## [0.1.0-beta.1] - 2026-11-19

### Added

- Sleep Control as a Flatpak app, `io.github.ghost_hackers.sleep-control`, built on the KDE 6.11 runtime with PyQt6.
- Tray icon that shows whether sleep is blocked, with Allow sleep, Keep awake, Sleep now, Show window and Quit in its menu.
- A small window with the same buttons. It opens from the app launcher, which helps on desktops without a tray.
- Terminal commands: `flatpak run io.github.ghost_hackers.sleep-control on`, `off`, `now`, `status` and `--version`. They talk to the running app and start it for `on`.
- Keep awake blocks idle sleep and suspend through the desktop's Inhibit portal. The block ends when you allow sleep or quit the app, and also when the app is stopped or crashes.
- One copy runs per session. Starting it again opens the window of the copy that is already running.
- Keep awake and Allow sleep as quick actions on the app launcher.
- Sleep now ends the block and suspends the PC right away through logind.
- When the desktop refuses a request, the reason shows in the window and as a tray notification.

### Security

- The control socket and its folder can be read by your user only.
- The Flatpak has no network access and no access to your files. It asks only for the display, the tray watcher and logind.

[Unreleased]: https://github.com/Ghost-Hackers/sleep-control/compare/v0.1.0-beta.1...HEAD
[0.1.0-beta.1]: https://github.com/Ghost-Hackers/sleep-control/releases/tag/v0.1.0-beta.1

[![Back to top](https://img.shields.io/badge/Back%20to%20top-222?style=plastic&logo=github)](#changelog)
