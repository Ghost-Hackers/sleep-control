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
        self.metainfo = self.dir / "data" / "io.github.ghost_hackers.sleep-control.metainfo.xml"

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

    def comment_out_a_release(self, version: str) -> None:
        """Puts a commented-out release for version, dated 2030-01-01, ahead of the real ones."""
        text = self.metainfo.read_text()
        self.assertIn("<releases>", text)
        self.metainfo.write_text(text.replace(
            "<releases>", f'<releases>\n    <!-- <release version="{version}" date="2030-01-01"/> -->', 1))

    def test_release_inside_an_xml_comment_does_not_count(self) -> None:
        init = self.dir / "src" / "sleep_control" / "__init__.py"
        init.write_text(re.sub(r'__version__ = "[^"]*"', '__version__ = "9.9.9"', init.read_text()))
        self.comment_out_a_release("9.9.9")
        result = self.dry_run()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("expected 9.9.9", result.stderr)

    def test_timestamps_come_from_the_newest_release_that_is_not_a_comment(self) -> None:
        before = self.dry_run()
        self.assertEqual(before.returncode, 0, before.stderr)
        version = re.search(r"sleep-control-(.+)\.flatpak", before.stdout)
        assert version is not None
        self.comment_out_a_release(version.group(1))
        after = self.dry_run()
        self.assertEqual((after.returncode, after.stdout), (0, before.stdout), after.stderr)

    def newest_release(self, attributes: str) -> None:
        """Puts a release with these attributes ahead of the real ones."""
        text = self.metainfo.read_text()
        self.assertIn("<releases>", text)
        self.metainfo.write_text(text.replace("<releases>", f"<releases>\n    <release {attributes}/>", 1))

    def test_newest_release_without_a_version_is_missing(self) -> None:
        self.newest_release('date="2030-01-01"')
        result = self.dry_run()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("build: newest <release> in the metainfo is missing, expected ", result.stderr)

    def test_newest_release_without_a_date_fails(self) -> None:
        before = self.dry_run()
        version = re.search(r"sleep-control-(.+)\.flatpak", before.stdout)
        assert version is not None
        self.newest_release(f'version="{version.group(1)}"')
        result = self.dry_run()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("build: newest <release> in the metainfo has no date", result.stderr)

    def test_metainfo_that_is_not_xml_fails_with_the_parser_error(self) -> None:
        self.metainfo.write_text(self.metainfo.read_text().replace("</component>", ""))
        result = self.dry_run()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertRegex(result.stderr, r"build: data/\S+\.metainfo\.xml: no element found: line \d+, column \d+")

    def test_missing_metainfo_fails_with_the_reason(self) -> None:
        self.metainfo.unlink()
        result = self.dry_run()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertRegex(result.stderr, r"build: data/\S+\.metainfo\.xml: .*No such file or directory")


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
