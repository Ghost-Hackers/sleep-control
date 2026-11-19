# Testing

Copy this plan into the tracking issue of each release and fill it in before the build is published. Run the automated layers first, then the end-to-end script on the final build. The release waits for it to pass.

## Contents

- [Automated layers](#automated-layers)
- [End-to-end run](#end-to-end-run)
- [What the app writes](#what-the-app-writes)
- [Quit and kill at any moment](#quit-and-kill-at-any-moment)
- [Upgrade and downgrade](#upgrade-and-downgrade)
- [Attack plan](#attack-plan)
- [Exceptions](#exceptions)
- [Results](#results)

## Automated layers

[`tools/lint.sh`](../tools/lint.sh) runs Ruff on `src` and `tests`, Pyright in strict mode on the Python code and ShellCheck on every shell script, the end-to-end script included. It has to pass.

[`tools/test.sh`](../tools/test.sh) runs the unit and component tests. Each module in [`tests/`](../tests) names the host it needs, and [`tests/run.py`](../tests/run.py) skips modules the machine can't run unless you ask for them by name or pass `--all`. A release needs all three hosts, so run it on a machine that has them:

| Host | Modules |
| --- | --- |
| `any` | `test_cli`, `test_instance`, `test_instance_race`, `test_runner`, `test_runner_bus`, `test_coverage_gate`, `test_version`, `test_packaging`, `test_check_release` |
| `kde-session` | `test_state`, `test_window`, `test_session_app`, `test_stalls`, `test_desktop`, `test_desktop_race`, `test_portal_files` |
| `flatpak` | `test_flatpak`, `test_e2e_script` |

```sh
tools/lint.sh
tools/test.sh --all
tools/test.sh --coverage
```

`--coverage` needs 100% branch coverage of `src/sleep_control`. Lines no test can reach are listed in [`tests/unreachable.tsv`](../tests/unreachable.tsv) with the reason and the proof. For each release, read the list again: every entry must still be unreachable, and a new entry needs its proof in the same change. The gate already fails when a listed line runs.

## End-to-end run

[`tests/e2e/run.sh`](../tests/e2e/run.sh) drives the installed Flatpak through `flatpak run`, with a real PowerDevil, tray watcher and logind. It refuses to run while an instance is open and leaves that one alone. Install the release bundle first, quit any copy of the app you have running, then:

```sh
flatpak install --user -y --bundle dist/sleep-control-<version>.flatpak
tests/e2e/run.sh
```

It prints PASS or FAIL for each case and a total, and exits 1 when any case fails. The cases:

- `--version` matches the version in the source.
- `status` with no instance reports that sleep is allowed and starts nothing.
- `on` starts the app in the background and returns within a few seconds.
- The block shows up in PowerDevil's inhibition list, counting only the app's own entries against the count from before.
- `on` twice adds no second block, and `off` removes it.
- Every `on` and `off` the script runs returns 0.
- No call of the app runs longer than 60 seconds. One that hangs fails its case.
- A second launch returns 0 and hands over to the first instance.
- The tray item is registered with the tray watcher.
- With a block lock of its own in place, the script runs `now`. It must be refused, and nothing suspends. The script first checks that logind reports `CanSuspend` as `inhibited`, and fails without running `now` if it doesn't. If `now` ends in any other way than that refusal, the script ends the app before it releases the lock.
- The refused `now` has released the block, so the script turns it on again before the next case.
- Quit from the tray menu and SIGTERM each remove the block and the socket. SIGKILL of the instance the script started removes the block and leaves the socket behind, which the script checks.
- The app starts again over the stale socket SIGKILL left.
- The files the app wrote are listed (see below).
- The locks other programs held at the start, in logind and in PowerDevil, are still held at the end.

The script checks its arguments, and that the bundle file holds this app, before it starts anything. If the bundle does not install after the first uninstall, the script stops there and says how to install the app again. With `--reinstall <bundle>` it also uninstalls the app, reports that `~/.var/app/io.github.ghost_hackers.sleep-control` stays after a plain uninstall, checks that `--delete-data` removes it, and installs the bundle again. Without that option the uninstall cases don't run and the script says so, which makes the run safe on a machine you use. Run it twice before the release.

## What the app writes

The app keeps no settings and no state. The end-to-end script lists every file and folder that appears, while the app runs or after it has quit, under `~/.var/app/io.github.ghost_hackers.sleep-control` and `$XDG_RUNTIME_DIR/app/io.github.ghost_hackers.sleep-control` during the run, and fails if there is a file in the app's `data`, `config` or `.local/state` folder or in the runtime folder, from this run or an earlier one, beyond the control socket, its lock file and the empty `config/kdeglobals` that Flatpak creates as a mount point. On a clean install the first run leaves Flatpak's own folders, a Fontconfig cache and `control.sock.lock`; the socket is removed on exit. The lock file stays empty, and the next start takes the lock again. Copy the listing into the results and check it by eye for anything new. The only things the app takes outside its folders are the Inhibit request through the portal, the tray registration and, for `now`, the logind call.

## Quit and kill at any moment

Closing the app in any way must release the block and leave nothing to repair. Quit and SIGTERM also remove the socket. SIGKILL leaves it, and the next start replaces it. The end-to-end script already runs Quit, SIGTERM and SIGKILL with the block on. Do these by hand on the final build:

- Quit the app while a `now` is being refused.
- Log out of the session with the block on and check PowerDevil's list afterwards.
- Remove the app with `flatpak uninstall --user` while it runs with the block on.

## Upgrade and downgrade

Install the previous published release, turn Keep awake on and then off again, then install the new bundle over it with `flatpak install --user`. The app must start, report the right version and behave as in the end-to-end run. Do the same the other way round with the older bundle over the new one. Check that `~/.var/app/io.github.ghost_hackers.sleep-control` is unchanged by both steps apart from caches.

The first release has nothing to upgrade from, so this check starts with the second release.

## Attack plan

Try to break the app. Note a result for each item. Anything that breaks becomes a bug with a regression test.

- Send oversized input to the control socket, a line longer than `MAX_LINE` in [`src/sleep_control/ipc.py`](../src/sleep_control/ipc.py) (64 bytes) with and without a newline, and check that the app answers with an error and keeps running.
- Send forged commands, an unknown word, an empty line, binary data and a command with trailing characters, and check that nothing but `on`, `off`, `now`, `status` and `show` does anything.
- Try to reach another user's socket: from a second account, connect to the first user's `$XDG_RUNTIME_DIR/app/io.github.ghost_hackers.sleep-control/control.sock`. The folder is mode 700 and the socket 600, so the connection has to be refused.
- Put a stale socket file in place with no instance behind it, then run `status`, `on` and a plain launch. Each must recover.
- Run `on`, `off` and `now` from a script in a loop and in parallel, including with the app not running. There must be one instance, at most one block, and no suspend while a block lock is held.
- Make sure the build has no test hooks. The Flatpak must not contain [`tests/`](../tests), and `flatpak run --command=sh io.github.ghost_hackers.sleep-control -c 'ls /app/share/sleep-control'` must show only `sleep_control` and `icons`.
- Compare the installed permissions with the manifest's list: `flatpak info --show-permissions io.github.ghost_hackers.sleep-control` against `finish-args` in [`io.github.ghost_hackers.sleep-control.yml`](../packaging/flatpak/io.github.ghost_hackers.sleep-control.yml). The KDE runtime adds read access to `xdg-config/kdeglobals` and talk access to `org.kde.kconfig.notify`, `org.kde.KGlobalSettings` and `com.canonical.AppMenu.Registrar` on its own. Anything else is a defect, and the list in the [README](../README.md) must match the manifest.
- Check that nothing is built from input: the command line and socket handler never pass a received string to a shell, `eval` or a file path.

## Exceptions

Checks that are not run against the real service, with the reason. The tests use no test doubles.

| Check | Why not | Proof |
| --- | --- | --- |
| A suspend started by `now` or Sleep now, in the script and the automated tests | A suspend stops the run that would check it, so both only run `now` under a block lock, where logind refuses it | [`tests/e2e/run.sh`](../tests/e2e/run.sh) and [`tests/test_state.py`](../tests/test_state.py) check that `CanSuspend` is `inhibited` first. The suspend itself is done by hand, see [Results](#results) |
| The source lines in [`tests/unreachable.tsv`](../tests/unreachable.tsv) | No input, state or host reaches them | The file has the proof for each line, and the coverage gate fails when a listed line runs |

## Results

Copy this table into the release issue and fill it in. Write the command or run you used in the notes, and link the log for anything that failed.

| Case | Result | Notes |
| --- | --- | --- |
| `tools/lint.sh` | | |
| `tools/test.sh --all` | | |
| `tools/test.sh --coverage` | | |
| Unreachable list reread | | |
| `tests/e2e/run.sh --reinstall`, first run | | |
| `tests/e2e/run.sh --reinstall`, second run | | |
| Files the app wrote | | |
| Quit, SIGTERM and SIGKILL by hand | | |
| Sleep now by hand: the machine suspends and wakes with the block off | | |
| Upgrade from the previous release | | |
| Downgrade to the previous release | | |
| Oversized and forged socket input | | |
| Another user's socket | | |
| Stale socket | | |
| `on`, `off`, `now` from a script | | |
| No test hooks in the build | | |
| Permissions match the manifest | | |

[![Back to top](https://img.shields.io/badge/Back%20to%20top-222?style=plastic&logo=github)](#testing)
