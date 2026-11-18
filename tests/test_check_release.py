"""The tag check in .github/scripts/check_release.sh, run on throwaway copies of the files it reads."""

import pathlib
import shutil
import subprocess
import tempfile
import unittest

HOST = "any"

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github" / "scripts" / "check_release.sh"
METAINFO = "data/io.github.ghost_hackers.sleep-control.metainfo.xml"


class TagCheckTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        (self.dir / ".github" / "scripts").mkdir(parents=True)
        shutil.copy(SCRIPT, self.dir / ".github" / "scripts")
        self.release("0.2.0")

    def write(self, name: str, text: str) -> None:
        path = self.dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def release(self, version: str) -> None:
        self.write("src/sleep_control/__init__.py", f'"""Sleep Control."""\n\n__version__ = "{version}"\n')
        self.write("CHANGELOG.md", f"# Changelog\n\n## [Unreleased]\n\n## [{version}] - 2026-12-01\n\n- A timer.\n")
        self.write(METAINFO, f'<component>\n  <releases>\n    <release version="{version}" date="2026-12-01"/>\n'
                             "  </releases>\n</component>\n")

    def check(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["bash", ".github/scripts/check_release.sh", *args],
                              cwd=self.dir, capture_output=True, text=True)

    def test_tag_with_its_section_and_release_passes(self) -> None:
        result = self.check("v0.2.0")
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "release: v0.2.0 ok\n", ""))

    def test_pre_release_tag_passes(self) -> None:
        self.release("0.2.0-beta.1")
        self.assertEqual(self.check("v0.2.0-beta.1").returncode, 0)

    def test_versions_in_the_release_scheme_pass(self) -> None:
        for version in ("0.2.0", "10.20.30", "0.2.0-alpha.1", "0.2.0-beta.12", "1.0.0-rc.2"):
            with self.subTest(version=version):
                self.release(version)
                self.assertEqual(self.check(f"v{version}").returncode, 0)

    def test_version_outside_the_release_scheme_fails(self) -> None:
        for version in ("not-semver", "1.2", "1.2.3.4", "01.2.3", "1.2.3-dev.1", "1.2.3-beta", "1.2.3-beta.0",
                        "1.2.3+build"):
            with self.subTest(version=version):
                self.release(version)
                result = self.check(f"v{version}")
                self.assertEqual(result.returncode, 1)
                self.assertIn(f"version {version} is not X.Y.Z or X.Y.Z-(alpha|beta|rc).N", result.stderr)

    def test_tag_for_another_version_fails(self) -> None:
        result = self.check("v0.3.0")
        self.assertEqual(result.returncode, 1)
        self.assertIn("tag v0.3.0 does not match __version__ 0.2.0", result.stderr)

    def test_tag_without_the_v_fails(self) -> None:
        self.assertEqual(self.check("0.2.0").returncode, 1)

    def test_lines_still_under_unreleased_fail(self) -> None:
        self.write("CHANGELOG.md", "# Changelog\n\n## [Unreleased]\n\n- A timer.\n")
        result = self.check("v0.2.0")
        self.assertEqual(result.returncode, 1)
        self.assertIn("CHANGELOG.md has no section for 0.2.0", result.stderr)

    def test_section_of_a_pre_release_does_not_count_for_the_release(self) -> None:
        self.write("CHANGELOG.md", "# Changelog\n\n## [Unreleased]\n\n## [0.2.0-beta.1] - 2026-11-20\n\n- A timer.\n")
        self.assertEqual(self.check("v0.2.0").returncode, 1)

    def test_version_dots_match_only_dots(self) -> None:
        self.write("CHANGELOG.md", "# Changelog\n\n## [0x2y0] - 2026-12-01\n\n- A timer.\n")
        self.assertEqual(self.check("v0.2.0").returncode, 1)

    def test_section_heading_inside_a_line_does_not_count(self) -> None:
        self.write("CHANGELOG.md", "# Changelog\n\n## [Unreleased]\n\n- See ## [0.2.0] below.\n")
        self.assertEqual(self.check("v0.2.0").returncode, 1)

    def test_missing_metainfo_release_fails(self) -> None:
        self.write(METAINFO, '<component>\n  <releases>\n    <release version="0.1.0" date="2026-11-20"/>\n'
                             "  </releases>\n</component>\n")
        result = self.check("v0.2.0")
        self.assertEqual(result.returncode, 1)
        self.assertIn("has no <release> for 0.2.0", result.stderr)

    def test_metainfo_release_of_a_pre_release_does_not_count_for_the_release(self) -> None:
        self.write(METAINFO, '<component>\n  <releases>\n    <release version="0.2.0-beta.1" date="2026-11-20"/>\n'
                             "  </releases>\n</component>\n")
        result = self.check("v0.2.0")
        self.assertEqual(result.returncode, 1)
        self.assertIn("has no <release> for 0.2.0", result.stderr)

    def test_release_inside_an_xml_comment_does_not_count(self) -> None:
        self.write(METAINFO, '<component>\n  <releases>\n    <!-- <release version="0.2.0" date="2026-12-01"/> -->\n'
                             '    <release version="0.1.0" date="2026-11-20"/>\n  </releases>\n</component>\n')
        result = self.check("v0.2.0")
        self.assertEqual(result.returncode, 1)
        self.assertIn("has no <release> for 0.2.0", result.stderr)

    def test_metainfo_that_is_not_xml_fails(self) -> None:
        self.write(METAINFO, '<component>\n  <release version="0.2.0" date="2026-12-01">\n')
        result = self.check("v0.2.0")
        self.assertEqual(result.returncode, 1)
        self.assertIn("has no <release> for 0.2.0", result.stderr)

    def test_missing_version_fails(self) -> None:
        self.write("src/sleep_control/__init__.py", '"""Sleep Control."""\n')
        result = self.check("v0.2.0")
        self.assertEqual(result.returncode, 1)
        self.assertIn("no __version__", result.stderr)

    def test_no_tag_or_two_tags_is_a_usage_error(self) -> None:
        for args in ((), ("v0.2.0", "v0.2.0")):
            with self.subTest(args=args):
                result = self.check(*args)
                self.assertEqual((result.returncode, result.stderr), (2, "usage: check_release.sh <tag>\n"))
