#!/bin/bash
# Run by .github/workflows/release.yml before it builds a tag.
#   check_release.sh <tag>   the tag is v<version> for the version in src/sleep_control/__init__.py, and that
#                            version has a section in CHANGELOG.md and a <release> in the metainfo
set -euo pipefail
[ $# = 1 ] || { echo "usage: check_release.sh <tag>" >&2; exit 2; }
tag=$1
cd "$(dirname "$0")/../.."
metainfo=data/io.github.ghost_hackers.sleep-control.metainfo.xml
version=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' src/sleep_control/__init__.py)
[ -n "$version" ] || { echo "no __version__ in src/sleep_control/__init__.py" >&2; exit 1; }
[ "$tag" = "v$version" ] || { echo "tag $tag does not match __version__ $version in src/sleep_control/__init__.py" >&2; exit 1; }
awk -v h="## [$version]" 'index($0, h) == 1 { found = 1 } END { exit !found }' CHANGELOG.md \
  || { echo "CHANGELOG.md has no section for $version" >&2; exit 1; }
grep -qF "<release version=\"$version\"" "$metainfo" || { echo "$metainfo has no <release> for $version" >&2; exit 1; }
echo "release: $tag ok"
