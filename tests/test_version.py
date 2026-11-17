"""Version and app ID format."""

import re
import unittest

import sleep_control

HOST = "any"

SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-(alpha|beta|rc)\.[1-9]\d*)?$")


class VersionTest(unittest.TestCase):
    def test_version_is_semver_with_a_stage(self) -> None:
        self.assertRegex(sleep_control.__version__, SEMVER)

    def test_app_id_matches_flathub_rules(self) -> None:
        self.assertRegex(sleep_control.APP_ID, r"^io\.github\.[a-z0-9_]+\.[A-Za-z0-9_-]+$")
