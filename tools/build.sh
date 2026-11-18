#!/bin/bash
# Builds dist/sleep-control-<version>.flatpak and its .sha256. Reproducible for the same
# SDK and BaseApp commits, which it prints.
#   tools/build.sh        runs the tests, builds, keeps a copy under prereleases/ or releases/
#   tools/build.sh --ci   builds in the flathub-infra container; CI runs the tests separately
#   tools/build.sh --dry-run   checks the version and metainfo and prints what it would build
# Needs: flatpak install --user flathub org.flatpak.Builder org.kde.Sdk//6.11 com.riverbankcomputing.PyQt.BaseApp//6.11
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd); cd "$root"
ci=false
dry=false
case "${1:-}" in
  --ci) ci=true ;;
  --dry-run) dry=true ;;
  "") ;;
  *) echo "usage: tools/build.sh [--ci | --dry-run]" >&2; exit 2 ;;
esac
app=io.github.ghost_hackers.sleep-control
manifest=packaging/flatpak/$app.yml
flathub=https://dl.flathub.org/repo/flathub.flatpakrepo
v=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' src/sleep_control/__init__.py)
[ -n "$v" ] || { echo "build: no __version__ in src/sleep_control/__init__.py" >&2; exit 1; }
# shellcheck source=tools/env.sh
. tools/env.sh
# Parsed as XML, so a release inside a comment doesn't count.
release=$("$PYTHON" -c 'import sys, xml.etree.ElementTree as ET
try:
    r = next(ET.parse(sys.argv[1]).iter("release"), None)
except (OSError, ET.ParseError) as e:
    sys.exit(f"build: {sys.argv[1]}: {e}")
print(*((r.get("version", ""), r.get("date", "")) if r is not None else ()))' "data/$app.metainfo.xml") || exit 1
# Every timestamp is the metainfo release date, midnight UTC.
read -r first date <<<"$release"
[ "$first" = "$v" ] || { echo "build: newest <release> in the metainfo is ${first:-missing}, expected $v" >&2; exit 1; }
SOURCE_DATE_EPOCH=$(date -u -d "${date}T00:00:00Z" +%s)
export SOURCE_DATE_EPOCH
if $dry; then
  echo "build: would build sleep-control-$v.flatpak, timestamps $date (SOURCE_DATE_EPOCH=$SOURCE_DATE_EPOCH)"
  exit 0
fi
$ci || tools/test.sh

# Keep builder state out of the source tree.
work=${SLEEP_CONTROL_BUILD_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/sleep-control-build}
mkdir -p "$work" dist
log="$work/flatpak-builder.log"
inst=--user
if $ci; then
  # The container's built-in SDK can't always be updated in place, so CI installs its own copy.
  flatpak remote-add "$inst" --if-not-exists flathub "$flathub"
  builder=(flatpak-builder "$inst" --install-deps-from=flathub)
else
  builder=(flatpak run --filesystem="$root:ro" --filesystem="$work" org.flatpak.Builder "$inst")
fi
echo "build: flatpak-builder, log in $log"
# Otherwise the manifest's mtime ends up in /app/manifest.json.
if ! "${builder[@]}" --force-clean --disable-rofiles-fuse --state-dir="$work/state" \
     --override-source-date-epoch="$SOURCE_DATE_EPOCH" "$work/build" "$manifest" >"$log" 2>&1; then
  tail -n 20 "$log" >&2
  echo "build: flatpak-builder failed" >&2
  exit 1
fi
key() { sed -n "s/^$1: '\{0,1\}\([^']*\)'\{0,1\}$/\1/p" "$manifest"; }
for ref in "$(key sdk)//$(key runtime-version)" "$(key base)//$(key base-version)"; do
  echo "build: $ref $(flatpak "$inst" info --show-commit "$ref")"
done

# Commit with the release time so the same tree gives the same commit.
rm -rf -- "${work:?}/repo"
flatpak build-export --timestamp="${date}T00:00:00Z" "$work/repo" "$work/build" >>"$log" 2>&1
commit=$(cat "$work/repo/refs/heads/app/$app/"*/master)
echo "build: app commit $commit"
name="sleep-control-$v"
flatpak build-bundle --runtime-repo="$flathub" "$work/repo" "dist/$name.flatpak" "$app"

# build-bundle writes its run time into the bundle and ignores SOURCE_DATE_EPOCH. The bundle
# is a GVariant (a{sv}tayay(commit)aya(uayttay)a(yaytt)); t is a big-endian uint64 at the
# first 8-byte boundary after the a{sv}, whose end is the tuple's last framing offset.
uint() { # file offset count le|be
  local hex
  hex=$(od -An -v -t x1 -j "$2" -N "$3" "$1" | tr -d ' \n')
  [ "$4" = be ] || hex=$(echo "$hex" | fold -w2 | tac | tr -d '\n')
  echo $((16#$hex))
}
set_bundle_time() { # file epoch
  local f=$1 t=$2 size w end pos old bytes='' i
  size=$(stat -c %s "$f")
  if ((size > 0xFFFFFFFF)); then w=8; elif ((size > 0xFFFF)); then w=4; elif ((size > 0xFF)); then w=2; else w=1; fi
  end=$(uint "$f" $((size - w)) "$w" le)
  pos=$(((end + 7) & ~7))
  ((pos + 8 <= size - w)) || { echo "build: $f does not look like a Flatpak bundle" >&2; return 1; }
  old=$(uint "$f" "$pos" 8 be)
  ((old >= 1000000000 && old < 10000000000)) || { echo "build: no timestamp at byte $pos of $f (found $old)" >&2; return 1; }
  for i in 7 6 5 4 3 2 1 0; do bytes+=$(printf '\\x%02x' $(((t >> (8 * i)) & 255))); done
  printf '%b' "$bytes" | dd of="$f" bs=1 seek="$pos" conv=notrunc status=none
  ((old == t)) || echo "build: bundle time $old set to $t"
}
set_bundle_time "dist/$name.flatpak" "$SOURCE_DATE_EPOCH"
(cd dist && sha256sum "$name.flatpak" > "$name.flatpak.sha256")
echo "build: dist/$name.flatpak ($(cut -d' ' -f1 "dist/$name.flatpak.sha256"))"
$ci && exit 0

# Keep a local copy: pre-releases under prereleases/<stage>/, final releases under releases/.
case "$v" in
  *-*) keep="prereleases/$(echo "${v#*-}" | cut -d. -f1)/v$v" ;;
  *)   keep="releases/v$v" ;;
esac
mkdir -p "$keep"
cp "dist/$name.flatpak" "dist/$name.flatpak.sha256" "$keep/"
echo "build: copy in $keep/"
