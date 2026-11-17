"""tools/build.sh's checks before it builds, and what the manifest installs."""

import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

HOST = "any"

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "packaging" / "flatpak" / "io.github.ghost_hackers.sleep-control.yml"
ICON_DIR = "/app/share/sleep-control/icons"


class BuildCheckTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        for part in ("tools", "src", "data", "packaging", "CHANGELOG.md"):
            source = ROOT / part
            if source.is_dir():
                shutil.copytree(source, self.dir / part)
            else:
                shutil.copy(source, self.dir / part)

    def dry_run(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["bash", "tools/build.sh", "--dry-run"], cwd=self.dir,
                              capture_output=True, text=True, timeout=60)

    def test_builds_while_the_version_is_still_unreleased(self) -> None:
        changelog = self.dir / "CHANGELOG.md"
        text = changelog.read_text()
        changelog.write_text(re.sub(r"(?ms)^## \[\d[^\]]*\].*?(?=^\[)", "", text))
        result = self.dry_run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("build: would build sleep-control-", result.stdout)

    def test_metainfo_release_must_match_the_version(self) -> None:
        init = self.dir / "src" / "sleep_control" / "__init__.py"
        init.write_text(re.sub(r'__version__ = "[^"]*"', '__version__ = "9.9.9"', init.read_text()))
        result = self.dry_run()
        self.assertEqual(result.returncode, 1)
        self.assertIn("expected 9.9.9", result.stderr)


class ManifestTest(unittest.TestCase):
    def installed_icons(self) -> set[str]:
        names: set[str] = set()
        for line in MANIFEST.read_text().splitlines():
            if "install" in line and f"-t {ICON_DIR} " in line:
                for pattern in line.split(f"-t {ICON_DIR} ", 1)[1].split():
                    names.update(p.name for p in ROOT.glob(pattern.replace("${FLATPAK_ID}", MANIFEST.stem)))
        return names

    def test_installs_every_tray_icon(self) -> None:
        tray = {p.name for p in (ROOT / "data" / "icons").glob("tray-*.svg")}
        self.assertEqual(tray - self.installed_icons(), set())


if __name__ == "__main__":
    unittest.main()
