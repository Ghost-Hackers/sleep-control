"""The coverage gate on hand-written coverage reports and lists."""

import os
import tempfile
import unittest
from collections.abc import Iterable

from .coverage_gate import Branch, Report, check, parse_lines, read_list

HOST = "any"
FILE = "src/sleep_control/x.py"


def report(executed: Iterable[int], missing: Iterable[int], missing_branches: Iterable[Branch] = ()) -> Report:
    return {"files": {FILE: {"executed_lines": list(executed), "missing_lines": list(missing),
                             "missing_branches": [list(b) for b in missing_branches]}}}


class GateTest(unittest.TestCase):
    def write_list(self, text: str) -> tuple[dict[str, set[int]], dict[str, set[Branch]], list[str]]:
        fd, path = tempfile.mkstemp(suffix=".tsv")
        with os.fdopen(fd, "w") as f:
            f.write(text)
        self.addCleanup(os.unlink, path)
        return read_list(path)

    def test_parse_lines(self) -> None:
        self.assertEqual(parse_lines("3, 5-7,9->12"), ({3, 5, 6, 7}, {(9, 12)}))

    def test_everything_ran(self) -> None:
        self.assertEqual(check(report([1, 2, 3], []), {}, {}), [])

    def test_line_not_run_and_not_listed(self) -> None:
        self.assertEqual(check(report([1, 2], [3]), {}, {}), [f"{FILE}:3: not run by any test"])

    def test_listed_line_and_the_branch_into_it(self) -> None:
        self.assertEqual(check(report([1, 2], [3], [(2, 3)]), {FILE: {3}}, {}), [])

    def test_listed_line_that_ran(self) -> None:
        problems = check(report([1, 2, 3], []), {FILE: {3}}, {})
        self.assertEqual(problems, [f"{FILE}:3: listed as unreachable, but a test ran it"])

    def test_listed_line_that_is_not_a_statement(self) -> None:
        problems = check(report([1, 2], []), {FILE: {4}}, {})
        self.assertEqual(problems, [f"{FILE}:4: listed as unreachable, but it is not a statement"])

    def test_branch_not_run(self) -> None:
        problems = check(report([1, 2, 3], [], [(2, -1)]), {}, {})
        self.assertEqual(problems, [f"{FILE}:2: the branch to the function's exit never ran"])
        self.assertEqual(check(report([1, 2, 3], [], [(2, -1)]), {}, {FILE: {(2, -1)}}), [])

    def test_listed_branch_that_ran(self) -> None:
        problems = check(report([1, 2, 3], []), {}, {FILE: {(2, 3)}})
        self.assertEqual(problems, [f"{FILE}:2->3: listed as unreachable, but it ran or is not a branch"])

    def test_listed_file_that_is_not_measured(self) -> None:
        problems = check(report([1], []), {"src/sleep_control/gone.py": {1}}, {})
        self.assertEqual(problems, ["src/sleep_control/gone.py: listed as unreachable but not measured"])

    def test_list_needs_header_reason_and_proof(self) -> None:
        _, _, problems = self.write_list("path\tlines\treason\n")
        self.assertIn("the first row must be", problems[0])
        listed, _, problems = self.write_list(f"path\tlines\treason\tproof\n{FILE}\t3\tbecause\t \n")
        self.assertEqual((listed, len(problems)), ({}, 1))
        self.assertIn("needs a path, lines, a reason and a proof", problems[0])
        _, _, problems = self.write_list(f"path\tlines\treason\tproof\n{FILE}\tthree\tbecause\tshown\n")
        self.assertIn("can't read the lines", problems[0])
        listed, arcs, problems = self.write_list(f"path\tlines\treason\tproof\n{FILE}\t3,4->6\tbecause\tshown\n")
        self.assertEqual((listed, arcs, problems), ({FILE: {3}}, {FILE: {(4, 6)}}, []))


if __name__ == "__main__":
    unittest.main()
