"""tools/build.sh's checks before it builds."""

import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

HOST = "any"

ROOT = pathlib.Path(__file__).resolve().parents[1]


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


if __name__ == "__main__":
    unittest.main()
