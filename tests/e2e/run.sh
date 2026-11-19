#!/bin/bash
# End-to-end checks of the installed Flatpak, run the way a user runs it.
#   tests/e2e/run.sh                      every case except uninstall
#   tests/e2e/run.sh --reinstall <file>   also uninstall, then install <file> again
# Needs a KDE Plasma session with PowerDevil and the tray watcher, and logind.
# Starts and stops the app itself: quit your own copy first. Never suspends the machine.
set -u
ID=io.github.ghost_hackers.sleep-control
usage() { echo "usage: $0 [--reinstall <bundle>]" >&2; exit 2; }
bundle=""
case "${1:-}" in
  "") [ $# -eq 0 ] || usage ;;
  --reinstall)
    [ $# -eq 2 ] || usage
    bundle=$2
    [ -f "$bundle" ] || { echo "$0: no bundle file at $bundle" >&2; exit 2; }
    command -v ostree >/dev/null || { echo "$0: --reinstall needs ostree to check the bundle" >&2; exit 2; }
    # The uninstall cases must be able to put the app back: the bundle holds this app for this machine, its runtime
    # is installed, and the app is a user installation only.
    repo=$(mktemp -d)
    ref=$(ostree init --repo="$repo" --mode=archive-z2 >/dev/null 2>&1 &&
      flatpak build-import-bundle "$repo" "$bundle" >/dev/null 2>&1 && ostree refs --repo="$repo")
    grep -qx "app/${ID//./\\.}/[^/]*/[^/]*" <<<"$ref" || { rm -rf "$repo"; echo "$0: $bundle is not a Flatpak bundle of $ID" >&2; exit 2; }
    runtime=$(ostree cat --repo="$repo" "$ref" /metadata 2>/dev/null | sed -n 's/^runtime=//p')
    rm -rf "$repo"
    arch=$(cut -d/ -f3 <<<"$ref")
    flatpak --supported-arches | grep -qxF "$arch" ||
      { echo "$0: $bundle is built for $arch, which this machine doesn't run" >&2; exit 2; }
    { [ -n "$runtime" ] && flatpak info "$runtime" >/dev/null 2>&1; } ||
      { echo "$0: $bundle needs the runtime ${runtime:-its metadata names}, which is not installed" >&2; exit 2; }
    flatpak info --user "$ID" >/dev/null 2>&1 ||
      { echo "$0: --reinstall needs $ID installed with flatpak install --user" >&2; exit 2; }
    if flatpak info --system "$ID" >/dev/null 2>&1; then
      echo "$0: $ID is also installed system-wide, and --reinstall only handles a user installation" >&2
      exit 2
    fi ;;
  *) usage ;;
esac
# Every call ends within 60 seconds: SIGTERM after 50, SIGKILL 10 later. A call that is ended fails its case.
APP=(call 50 10)
DATA=$HOME/.var/app/$ID
RUNTIME=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/app/$ID
LOCK_WHO=sleep-control-e2e
pass=0
fail=0
holder=""
started=""
snap=$(mktemp -d)

result() { # result <case> <ok:0|1> <note>
  if [ "$2" -eq 0 ]; then pass=$((pass + 1)); echo "PASS $1${3:+ ($3)}"
  else fail=$((fail + 1)); echo "FAIL $1${3:+ ($3)}"; fi
}
check() { # check <case> <got> <want>
  if [ "$2" = "$3" ]; then result "$1" 0 "$2"; else result "$1" 1 "got '$2', want '$3'"; fi
}
# call <secs> <kill-after> <args>: runs the app with a limit. The pid goes to a file, so the exit trap sees a call
# made inside $(...) too.
call() {
  local rc
  # No signal is taken between the start and its record. env gives the app the default signals back.
  trap '' INT TERM HUP
  timeout --kill-after="$2" "$1" env --default-signal=INT,TERM,HUP flatpak run "$ID" "${@:3}" &
  echo "$!" >"$snap/call"
  stop_on_signals
  wait "$!"
  rc=$?
  : >"$snap/call"
  return "$rc"
}
said() { "${APP[@]}" "$@"; echo "rc=$?"; } # what a command prints, then its exit status
ok() { printf '%s\nrc=0' "$1"; }           # the same for a command that prints $1 and returns 0
cli() { # cli <case> <command>: the command has to return 0
  "${APP[@]}" "$2" >/dev/null
  check "$1" "$?" 0
  note_started
}

# A call still running ends within its limit. Waiting for it beats ending it: an on that is cut short can still start
# the app, and a now that finds no app suspends the machine itself.
wait_call() {
  local pid
  pid=$(cat "$snap/call" 2>/dev/null)
  [ -n "$pid" ] || return 0
  echo "waiting for the call of the app that is still running" >&2
  wait "$pid" 2>/dev/null
  for _ in $(seq 1 210); do
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.3
  done
  note_started
}
# The lock has a session of its own: systemd-inhibit and its sleep.
release_lock() {
  local h=$holder
  holder=""
  [ -n "$h" ] || return 0
  kill -TERM -- "-$h" 2>/dev/null
  wait "$h" 2>/dev/null
}
cleanup() {
  # Runs to the end: a second Ctrl-C must not leave the app or the lock behind.
  trap '' INT TERM HUP
  wait_call
  # The app goes before the lock, so a now that is still waiting in it can't suspend the machine.
  if end_started; then
    release_lock
  elif [ -n "$holder" ]; then
    echo "$0: an instance did not end, so the sleep lock stays until it expires" >&2
  fi
  rm -rf "$snap"
}
trap cleanup EXIT
# After the first signal the others are ignored, so the exit trap is not cut short.
stop_on_signals() {
  trap 'trap "" INT TERM HUP; exit 130' INT
  trap 'trap "" INT TERM HUP; exit 143' TERM
  trap 'trap "" INT TERM HUP; exit 129' HUP
}
stop_on_signals

# Pids of the app's instances: the holder of the instance lock, from /proc/locks. It lists the locks of this pid
# namespace only. A line looks like "1: FLOCK  ADVISORY  WRITE 1234 00:4d:5678 0 EOF"; a waiter has "->" after "1:".
app_pids() {
  local major minor inode
  read -r major minor inode < <(stat -c '%Hd %Ld %i' "$RUNTIME/control.sock.lock" 2>/dev/null) || return 0
  awk -v file="$(printf '%02x:%02x:%s' "$major" "$minor" "$inode")" \
    '$2 == "FLOCK" && $3 == "ADVISORY" && $4 == "WRITE" && $5 > 0 && $6 == file { print $5 }' /proc/locks
}
instances() { app_pids | wc -l; }
# The instances this run started. One that was running before is never touched.
note_started() { started="$started $(app_pids | tr '\n' ' ')"; }
stop_started() {
  local p
  for p in $(app_pids); do
    case " $started " in *" $p "*) kill -TERM "$p" 2>/dev/null ;; esac
  done
}
# started_pid prints the instance's pid when this run started it, and fails otherwise.
started_pid() {
  local p
  p=$(app_pids | head -n 1)
  case " $started " in *" $p "*) [ -n "$p" ] && echo "$p" ;; *) return 1 ;; esac
}
# Ends them for sure: SIGKILL for one that doesn't answer SIGTERM.
end_started() {
  local p
  [ -n "${started// /}" ] || return 0
  stop_started
  wait_instances 0 10 && return 0
  for p in $(app_pids); do
    case " $started " in *" $p "*) kill -KILL "$p" 2>/dev/null ;; esac
  done
  wait_instances 0 5
}

# PowerDevil's inhibitions that belong to the app.
list_inhibitions() {
  busctl --user "$@" call org.kde.Solid.PowerManagement /org/kde/Solid/PowerManagement/PolicyAgent \
    org.kde.Solid.PowerManagement.PolicyAgent ListInhibitions
}
# ours prints how many there are. Without an answer from PowerDevil it prints that instead, so no count check passes.
ours() {
  local list
  list=$(list_inhibitions 2>/dev/null) || { echo "no answer from PowerDevil"; return 1; }
  grep -o "\"$ID\"" <<<"$list" | wc -l
}
# Other programs' locks, one per line: logind's without this script's own, PowerDevil's without the app's.
# Fails without an answer from PowerDevil.
other_locks() {
  local list
  systemd-inhibit --list --no-pager --no-legend | grep -v "^$LOCK_WHO " | tr -s ' ' | sed 's/^/logind /'
  list=$(list_inhibitions --json=short 2>/dev/null) || return 1
  python3 -I -c '
import json, sys
for app, reason in json.load(sys.stdin)["data"][0]:
    if app != sys.argv[1]:
        print("powerdevil", app, reason)' "$ID" <<<"$list"
}
# wait_ours <count> <seconds>: PowerDevil applies a new block after about five seconds.
wait_ours() {
  local end=$((SECONDS + $2))
  while [ "$(ours)" != "$1" ]; do
    [ $SECONDS -ge $end ] && return 1
    sleep 0.5
  done
  return 0
}
wait_instances() { # wait_instances <count> <seconds>
  local end=$((SECONDS + $2))
  while [ "$(instances)" != "$1" ]; do
    [ $SECONDS -ge $end ] && return 1
    sleep 0.3
  done
  return 0
}

tray_items() {
  busctl --user get-property org.kde.StatusNotifierWatcher /StatusNotifierWatcher \
    org.kde.StatusNotifierWatcher RegisteredStatusNotifierItems | grep -o '"[^"]*"' | tr -d '"'
}
# tray_item prints "<service> <path>" of the registered icon titled Sleep Control.
tray_item() {
  local entry service path title
  while read -r entry; do
    service=${entry%%/*}
    path=/${entry#*/}
    title=$(busctl --user get-property "$service" "$path" org.kde.StatusNotifierItem Title 2>/dev/null)
    if [ "$title" = 's "Sleep Control"' ]; then echo "$service $path"; return 0; fi
  done < <(tray_items)
  return 1
}
# tray_quit clicks Quit in the tray icon's menu, as the panel does.
tray_quit() {
  local service path menu id
  read -r service path < <(tray_item) || return 1
  menu=$(busctl --user get-property "$service" "$path" org.kde.StatusNotifierItem Menu | cut -d'"' -f2)
  id=$(busctl --user --json=short -- call "$service" "$menu" com.canonical.dbusmenu GetLayout iias 0 -1 0 |
    python3 -I -c '
import json, sys
def walk(node):
    ident, props, children = node
    if props.get("label", {}).get("data", "").replace("&", "") == "Quit":
        print(ident)
    for child in children:
        walk(child["data"])
walk(json.load(sys.stdin)["data"][1])') || return 1
  [ -n "$id" ] || return 1
  busctl --user -- call "$service" "$menu" com.canonical.dbusmenu Event isvu "$id" clicked i 0 0 >/dev/null
}

list_files() { # list_files <outfile>
  { find "$DATA" "$RUNTIME" -printf '%y %p\n' 2>/dev/null; } | sort >"$1"
}

start_app() {
  "${APP[@]}" on >/dev/null 2>&1
  check "on that starts the app returns 0" "$?" 0
  wait_instances 1 10
  note_started
}
stop_app() { stop_started; wait_instances 0 10; }

# Before anything runs.
if [ "$(instances)" -ne 0 ]; then
  echo "A Sleep Control instance is running. Quit it first; this script starts its own." >&2
  exit 2
fi
if ! before=$(ours) || ! locks=$(other_locks); then
  echo "$0: PowerDevil doesn't answer on the session bus" >&2
  exit 2
fi
sort <<<"$locks" >"$snap/locks-before"
list_files "$snap/files-before"
echo "inhibitions of the app before: $before"

# Command line
want=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$(dirname "$0")/../../src/sleep_control/__init__.py")
check "--version matches the source" "$(said --version)" "$(ok "sleep-control $want")"
check "status with no instance" "$(said status)" "$(ok "Sleep is allowed")"
check "no instance was started by status" "$(instances)" 0

# Bounded, so a start that hangs fails the check below.
t0=$SECONDS
out=$(call 25 5 on)
rc=$?
took=$((SECONDS - t0))
note_started
check "the first on returns 0" "$rc" 0
check "on starts the app in the background" "$out" "Sleep is blocked (kept awake)"
if [ "$took" -le 8 ]; then result "on returns within a few seconds" 0 "${took} s"; else result "on returns within a few seconds" 1 "${took} s"; fi
check "one instance after on" "$(instances)" 1
wait_ours $((before + 1)) 10
check "block appears in PowerDevil's list" "$(ours)" $((before + 1))
cli "on again returns 0" on
sleep 6
check "on twice adds no second block" "$(ours)" $((before + 1))
check "status says blocked" "$(said status)" "$(ok "Sleep is blocked (kept awake)")"
list_files "$snap/files-running"
if tray_item >/dev/null; then result "tray item registered" 0 "$(tray_item)"; else result "tray item registered" 1; fi
cli "off returns 0" off
wait_ours "$before" 5
check "off removes the block" "$(ours)" "$before"
check "status says allowed" "$(said status)" "$(ok "Sleep is allowed")"

# Second launch
cli "on before the second launch returns 0" on
call 15 5 >/dev/null 2>&1
check "second launch returns 0" "$?" 0
check "second launch hands over to the first" "$(instances)" 1
wait_ours $((before + 1)) 10
check "block still held after the second launch" "$(ours)" $((before + 1))

# now, refused under a block lock of our own. The lock outlasts every call made under it. In a session of its own,
# Ctrl-C and a closed terminal don't reach it. setsid doesn't fork here, so $! is systemd-inhibit itself.
# No signal is taken between the start and holder=$!. env gives the lock the default signals back.
trap '' INT TERM HUP
setsid env --default-signal=INT,TERM,HUP systemd-inhibit --what=sleep --mode=block --who=$LOCK_WHO \
  --why="sleep-control e2e checks that now is refused" sleep 600 </dev/null &
holder=$!
stop_on_signals
# This run's own lock, by its pid. One left by an earlier run doesn't count.
lock_held() {
  kill -0 "$holder" 2>/dev/null && systemd-inhibit --list --no-pager --no-legend |
    awk -v who="$LOCK_WHO" -v pid="$holder" '$1 == who && $4 == pid { found = 1 } END { exit !found }'
}
for _ in $(seq 1 20); do
  lock_held && break
  sleep 0.5
done
state=$(busctl --system call org.freedesktop.login1 /org/freedesktop/login1 org.freedesktop.login1.Manager CanSuspend | cut -d'"' -f2)
if lock_held && [ "$state" = inhibited ]; then
  err=$("${APP[@]}" now 2>&1 >/dev/null; echo "rc=$?")
  case "$err" in
    *"Operation denied due to active block inhibitor"*rc=1) result "now is refused under a block lock" 0 "logind refused it" ;;
    *)
      result "now is refused under a block lock" 1 "$err"
      # The request may still be waiting in the app, so the app goes before the lock does.
      if ! end_started; then
        echo "$0: an instance did not end, so the sleep lock stays until it expires" >&2
        holder=""
        exit 1
      fi ;;
  esac
  check "still running after the refused now" "$(instances)" 1
  wait_ours "$before" 5
  check "the refused now released the block" "$(ours)" "$before"
else
  result "now is refused under a block lock" 1 "CanSuspend is '$state' under the lock, now was not called"
fi
release_lock

# Quit with the block on
cli "on before Quit returns 0" on
wait_ours $((before + 1)) 10
check "block on before Quit" "$(ours)" $((before + 1))
if tray_quit; then
  wait_instances 0 10
  check "Quit in the tray menu ends the app" "$(instances)" 0
  wait_ours "$before" 5
  check "Quit releases the block" "$(ours)" "$before"
else
  result "Quit in the tray menu ends the app" 1 "no tray menu to click"
fi
check "no socket left after Quit" "$(find "$RUNTIME" -name '*.sock' 2>/dev/null | wc -l)" 0

# SIGTERM with the block on
start_app
wait_ours $((before + 1)) 10
check "block on before SIGTERM" "$(ours)" $((before + 1))
if pid=$(started_pid); then
  kill -TERM "$pid"
  wait_instances 0 10
  check "SIGTERM ends the app" "$(instances)" 0
else
  result "SIGTERM ends the app" 1 "no instance this run started"
fi
wait_ours "$before" 5
check "SIGTERM releases the block" "$(ours)" "$before"
check "no socket left after SIGTERM" "$(find "$RUNTIME" -name '*.sock' 2>/dev/null | wc -l)" 0

# SIGKILL of the instance this script started: the app keeps no config to corrupt.
start_app
wait_ours $((before + 1)) 10
check "block on before SIGKILL" "$(ours)" $((before + 1))
if pid=$(started_pid); then
  kill -KILL "$pid"
  wait_instances 0 10
  check "SIGKILL ends the app" "$(instances)" 0
else
  result "SIGKILL ends the app" 1 "no instance this run started"
fi
wait_ours "$before" 5
check "SIGKILL releases the block" "$(ours)" "$before"
check "SIGKILL leaves the socket behind" "$(find "$RUNTIME" -name '*.sock' 2>/dev/null | wc -l)" 1
start_app
check "the app starts again over the stale socket" "$(said status)" "$(ok "Sleep is blocked (kept awake)")"
cli "off at the end returns 0" off
stop_app
check "the app ends at the end of the run" "$(instances)" 0

# What the app wrote
list_files "$snap/files-after"
# What was there while the app ran with the block on counts too, so a file it removes on exit is seen.
sort -u "$snap/files-running" "$snap/files-after" >"$snap/files-seen"
echo "files the app wrote (new since the start, under $DATA and $RUNTIME):"
comm -13 "$snap/files-before" "$snap/files-seen" | sed 's/^/  /'
# The lock file stays after exit. The kernel drops the lock with the process, so the next start takes it again.
# config/kdeglobals is empty: Flatpak creates it as the mount point for the desktop's file.
# Every file counts, also one an earlier run left.
stray=$(grep "^f $DATA/data/\|^f $DATA/config/\|^f $DATA/.local/state/\|^f $RUNTIME/" "$snap/files-seen" |
  grep -vxc -e "f $RUNTIME/control.sock.lock" -e "f $DATA/config/kdeglobals" || true)
check "no state or config file of its own" "$stray" 0

if locks=$(other_locks); then
  gone=$(sort <<<"$locks" | comm -23 "$snap/locks-before" -)
  [ -z "$gone" ] || while read -r line; do echo "  gone: $line"; done <<<"$gone"
  check "other programs' locks still held" "$(echo -n "$gone" | grep -c .)" 0
else
  result "other programs' locks still held" 1 "PowerDevil doesn't answer"
fi

# Uninstall
if [ -n "$bundle" ]; then
  flatpak uninstall --user -y "$ID" >/dev/null 2>&1
  check "uninstall returns 0" "$?" 0
  installed=$(flatpak info "$ID" >/dev/null 2>&1 && echo installed || echo gone)
  check "uninstall removes the app" "$installed" gone
  if [ "$installed" != gone ]; then
    echo "INFO the app is still installed, so the other uninstall cases are not run"
  else
    if [ -d "$DATA" ]; then echo "INFO uninstall without --delete-data leaves $DATA"; else echo "INFO uninstall without --delete-data removed $DATA"; fi
    if flatpak install --user -y --bundle "$bundle" >/dev/null 2>&1; then
      flatpak uninstall --user -y --delete-data "$ID" >/dev/null 2>&1
      check "uninstall --delete-data returns 0" "$?" 0
      check "--delete-data removes $DATA" "$([ -d "$DATA" ] && echo present || echo gone)" gone
      flatpak install --user -y --bundle "$bundle" >/dev/null 2>&1
      check "the bundle installs again" "$?" 0
      check "bundle installed again" "$(said --version)" "$(ok "sleep-control $want")"
    else
      result "the bundle installs after the uninstall" 1 "the app is not installed now; run: flatpak install --user --bundle $bundle"
    fi
  fi
else
  echo "uninstall cases not run (pass --reinstall <bundle>)"
fi

echo "total: $pass PASS, $fail FAIL"
[ "$fail" -eq 0 ]
