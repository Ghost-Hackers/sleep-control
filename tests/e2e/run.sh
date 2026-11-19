#!/bin/bash
# End-to-end checks of the installed Flatpak, run the way a user runs it.
#   tests/e2e/run.sh                      every case except uninstall
#   tests/e2e/run.sh --reinstall <file>   also uninstall, then install <file> again
# Needs a KDE Plasma session with PowerDevil and the tray watcher, and logind.
# Starts and stops the app itself: quit your own copy first. Never suspends the machine.
set -u
usage() { echo "usage: $0 [--reinstall <bundle>]" >&2; exit 2; }
bundle=""
case "${1:-}" in
  "") [ $# -eq 0 ] || usage ;;
  --reinstall)
    [ $# -eq 2 ] || usage
    bundle=$2
    [ -f "$bundle" ] || { echo "$0: no bundle file at $bundle" >&2; exit 2; } ;;
  *) usage ;;
esac
ID=io.github.ghost_hackers.sleep-control
APP=(flatpak run "$ID")
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

cleanup() {
  [ -n "$holder" ] && kill -TERM "$holder" 2>/dev/null
  stop_started
  rm -rf "$snap"
}
trap cleanup EXIT

# Pids of the app's instances: the Python process the launcher starts in the sandbox.
app_pids() {
  local p
  for p in $(pgrep -x python3); do
    if tr '\0' ' ' <"/proc/$p/cmdline" | grep -q -- '-m sleep_control'; then echo "$p"; fi
  done
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

# PowerDevil's inhibitions that belong to the app.
list_inhibitions() {
  busctl --user call org.kde.Solid.PowerManagement /org/kde/Solid/PowerManagement/PolicyAgent \
    org.kde.Solid.PowerManagement.PolicyAgent ListInhibitions
}
ours() { list_inhibitions | grep -o "\"$ID\"" | wc -l; }
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

start_app() { "${APP[@]}" on >/dev/null 2>&1; wait_instances 1 10; note_started; }
stop_app() { stop_started; wait_instances 0 10; }

# Before anything runs.
if [ "$(instances)" -ne 0 ]; then
  echo "A Sleep Control instance is running. Quit it first; this script starts its own." >&2
  exit 2
fi
list_files "$snap/files-before"
lock_pattern='Keep awake'
locks_before=$(systemd-inhibit --list --no-pager | grep -c "$lock_pattern")
before=$(ours)
echo "inhibitions of the app before: $before"

# Command line
want=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$(dirname "$0")/../../src/sleep_control/__init__.py")
check "--version matches the source" "$("${APP[@]}" --version)" "sleep-control $want"
check "status with no instance" "$("${APP[@]}" status; echo "rc=$?")" "$(printf 'Sleep is allowed\nrc=0')"
check "no instance was started by status" "$(instances)" 0

t0=$SECONDS
out=$("${APP[@]}" on)
took=$((SECONDS - t0))
note_started
check "on starts the app in the background" "$out" "Sleep is blocked (kept awake)"
if [ "$took" -le 8 ]; then result "on returns within a few seconds" 0 "${took} s"; else result "on returns within a few seconds" 1 "${took} s"; fi
check "one instance after on" "$(instances)" 1
wait_ours $((before + 1)) 10
check "block appears in PowerDevil's list" "$(ours)" $((before + 1))
"${APP[@]}" on >/dev/null
sleep 6
check "on twice adds no second block" "$(ours)" $((before + 1))
check "status says blocked" "$("${APP[@]}" status)" "Sleep is blocked (kept awake)"
if tray_item >/dev/null; then result "tray item registered" 0 "$(tray_item)"; else result "tray item registered" 1; fi
"${APP[@]}" off >/dev/null
wait_ours "$before" 5
check "off removes the block" "$(ours)" "$before"
check "status says allowed" "$("${APP[@]}" status)" "Sleep is allowed"

# Second launch
"${APP[@]}" on >/dev/null
timeout 20 "${APP[@]}" >/dev/null 2>&1
check "second launch hands over to the first" "$(instances)" 1
wait_ours $((before + 1)) 10
check "block still held after the second launch" "$(ours)" $((before + 1))

# now, refused under a block lock of our own
systemd-inhibit --what=sleep --mode=block --who=$LOCK_WHO --why="sleep-control e2e checks that now is refused" sleep 60 &
holder=$!
sleep 1
state=$(busctl --system call org.freedesktop.login1 /org/freedesktop/login1 org.freedesktop.login1.Manager CanSuspend | cut -d'"' -f2)
if systemd-inhibit --list --no-pager | grep -q "$LOCK_WHO" && [ "$state" = inhibited ]; then
  err=$("${APP[@]}" now 2>&1 >/dev/null; echo "rc=$?")
  case "$err" in
    *"Operation denied due to active block inhibitor"*rc=1) result "now is refused under a block lock" 0 "logind refused it" ;;
    *) result "now is refused under a block lock" 1 "$err" ;;
  esac
  check "still running after the refused now" "$(instances)" 1
else
  result "now is refused under a block lock" 1 "CanSuspend is '$state' under the lock, now was not called"
fi
kill -TERM "$holder" 2>/dev/null
wait "$holder" 2>/dev/null
holder=""

# Quit with the block on
before_quit=$(ours)
if tray_quit; then
  wait_instances 0 10
  check "Quit in the tray menu ends the app" "$(instances)" 0
  wait_ours "$before" 5
  check "Quit releases the block" "$(ours)" "$before"
else
  result "Quit in the tray menu ends the app" 1 "no tray menu to click ($before_quit blocks)"
fi
check "no socket left after Quit" "$(find "$RUNTIME" -name '*.sock' 2>/dev/null | wc -l)" 0

# SIGTERM with the block on
start_app
wait_ours $((before + 1)) 10
check "block on before SIGTERM" "$(ours)" $((before + 1))
pid=$(app_pids | head -n 1)
kill -TERM "$pid"
wait_instances 0 10
check "SIGTERM ends the app" "$(instances)" 0
wait_ours "$before" 5
check "SIGTERM releases the block" "$(ours)" "$before"
check "no socket left after SIGTERM" "$(find "$RUNTIME" -name '*.sock' 2>/dev/null | wc -l)" 0

# SIGKILL of the instance this script started: the app keeps no config to corrupt.
start_app
wait_ours $((before + 1)) 10
pid=$(app_pids | head -n 1)
kill -KILL "$pid"
wait_instances 0 10
check "SIGKILL ends the app" "$(instances)" 0
wait_ours "$before" 5
check "SIGKILL releases the block" "$(ours)" "$before"
start_app
check "the app starts again over the stale socket" "$("${APP[@]}" status)" "Sleep is blocked (kept awake)"
"${APP[@]}" off >/dev/null
stop_app

# What the app wrote
list_files "$snap/files-after"
echo "files the app wrote (new since the start, under $DATA and $RUNTIME):"
comm -13 "$snap/files-before" "$snap/files-after" | sed 's/^/  /'
# The lock file stays after exit. The kernel drops the lock with the process, so the next start takes it again.
stray=$(comm -13 "$snap/files-before" "$snap/files-after" | grep "^f $DATA/data/\|^f $RUNTIME/" | grep -vxc "f $RUNTIME/control.sock.lock" || true)
check "no state or config file of its own" "$stray" 0

check "other sleep locks untouched" "$(systemd-inhibit --list --no-pager | grep -c "$lock_pattern")" "$locks_before"

# Uninstall
if [ -n "$bundle" ]; then
  flatpak uninstall --user -y "$ID" >/dev/null 2>&1
  check "uninstall removes the app" "$(flatpak list --user --app --columns=application | grep -c "^$ID$")" 0
  if [ -d "$DATA" ]; then echo "INFO uninstall without --delete-data leaves $DATA"; else echo "INFO uninstall without --delete-data removed $DATA"; fi
  flatpak install --user -y --bundle "$bundle" >/dev/null 2>&1
  flatpak uninstall --user -y --delete-data "$ID" >/dev/null 2>&1
  check "--delete-data removes $DATA" "$([ -d "$DATA" ] && echo present || echo gone)" gone
  flatpak install --user -y --bundle "$bundle" >/dev/null 2>&1
  check "bundle installed again" "$("${APP[@]}" --version)" "sleep-control $want"
else
  echo "uninstall cases not run (pass --reinstall <bundle>)"
fi

echo "total: $pass PASS, $fail FAIL"
[ "$fail" -eq 0 ]
