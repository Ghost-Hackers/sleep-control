#!/bin/bash
# Run by .github/workflows/release.yml before it builds a tag.
#   check_release.sh <tag>   the version in src/sleep_control/__init__.py is X.Y.Z or X.Y.Z-(alpha|beta|rc).N,
#                            the tag is v<version>, and the version has a section in CHANGELOG.md and a
#                            <release> in the metainfo
set -euo pipefail
[ $# = 1 ] || { echo "usage: check_release.sh <tag>" >&2; exit 2; }
tag=$1
cd "$(dirname "$0")/../.."
metainfo=data/io.github.ghost_hackers.sleep-control.metainfo.xml
version=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' src/sleep_control/__init__.py)
[ -n "$version" ] || { echo "no __version__ in src/sleep_control/__init__.py" >&2; exit 1; }
scheme='^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-(alpha|beta|rc)\.[1-9][0-9]*)?$'
[[ $version =~ $scheme ]] || { echo "version $version is not X.Y.Z or X.Y.Z-(alpha|beta|rc).N" >&2; exit 1; }
[ "$tag" = "v$version" ] || { echo "tag $tag does not match __version__ $version in src/sleep_control/__init__.py" >&2; exit 1; }
awk -v h="## [$version]" 'index($0, h) == 1 { found = 1 } END { exit !found }' CHANGELOG.md \
  || { echo "CHANGELOG.md has no section for $version" >&2; exit 1; }
# Parsed as XML, so a release inside a comment doesn't count.
python3 -c 'import sys, xml.etree.ElementTree as ET
try:
    found = any(r.get("version") == sys.argv[2] for r in ET.parse(sys.argv[1]).iter("release"))
except (OSError, ET.ParseError):
    found = False
sys.exit(not found)' "$metainfo" "$version" || { echo "$metainfo has no <release> for $version" >&2; exit 1; }
echo "release: $tag ok"
