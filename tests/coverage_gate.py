"""Checks a coverage JSON report against the list of lines no test can reach.

    python -m tests.coverage_gate coverage.json tests/unreachable.tsv

The list is tab separated: path, lines, reason, proof. Lines are numbers,
ranges or branches ("12", "12-14", "12->15"), several joined with commas.
Every line and branch of src/sleep_control must run in the tests or be on the
list. A listed line has to be a statement that really did not run, a listed
branch has to be one that did not run, and every entry needs a reason and a
proof. A branch into a listed line counts as listed too.
"""

import csv
import json
import sys
from typing import NotRequired, TypedDict

COLUMNS = ["path", "lines", "reason", "proof"]

Branch = tuple[int, int]


class FileData(TypedDict):
    """One file in coverage.py's JSON report. A branch is [from, to]; to is negative for the function's exit."""

    executed_lines: list[int]
    missing_lines: list[int]
    missing_branches: NotRequired[list[list[int]]]


class Report(TypedDict):
    files: dict[str, FileData]


class Totals(TypedDict):
    num_statements: int
    num_branches: int


class FullReport(Report):
    totals: Totals


def parse_lines(text: str) -> tuple[set[int], set[Branch]]:
    """Returns (set of lines, set of (from, to) branches)."""
    lines: set[int] = set()
    branches: set[Branch] = set()
    for part in text.split(","):
        start, arrow, end = part.strip().partition("->")
        if arrow:
            branches.add((int(start), int(end)))
            continue
        first, _, last = part.strip().partition("-")
        lines.update(range(int(first), int(last or first) + 1))
    return lines, branches


def read_list(path: str) -> tuple[dict[str, set[int]], dict[str, set[Branch]], list[str]]:
    """Returns ({path: set of lines}, {path: set of branches}, problems)."""
    listed: dict[str, set[int]] = {}
    arcs: dict[str, set[Branch]] = {}
    problems: list[str] = []
    with open(path, newline="") as f:
        rows = [r for r in csv.reader(f, delimiter="\t") if r and not r[0].startswith("#")]
    if not rows or rows[0] != COLUMNS:
        return {}, {}, [f"{path}: the first row must be {' '.join(COLUMNS)}"]
    for number, row in enumerate(rows[1:], start=2):
        if len(row) != len(COLUMNS) or not all(cell.strip() for cell in row):
            problems.append(f"{path} row {number}: needs a path, lines, a reason and a proof")
            continue
        try:
            lines, branches = parse_lines(row[1])
        except ValueError:
            problems.append(f"{path} row {number}: can't read the lines {row[1]!r}")
            continue
        listed.setdefault(row[0], set()).update(lines)
        arcs.setdefault(row[0], set()).update(branches)
    return listed, arcs, problems


def check(report: Report, listed: dict[str, set[int]], arcs: dict[str, set[Branch]]) -> list[str]:
    problems: list[str] = []
    files = report["files"]
    for path in sorted((set(listed) | set(arcs)) - set(files)):
        problems.append(f"{path}: listed as unreachable but not measured")
    for path, data in sorted(files.items()):
        ran = set(data["executed_lines"])
        missing = set(data["missing_lines"])
        skip = listed.get(path, set[int]())
        for line in sorted(skip & ran):
            problems.append(f"{path}:{line}: listed as unreachable, but a test ran it")
        for line in sorted(skip - ran - missing):
            problems.append(f"{path}:{line}: listed as unreachable, but it is not a statement")
        for line in sorted(missing - skip):
            problems.append(f"{path}:{line}: not run by any test")
        not_ran = {(b[0], b[1]) for b in data.get("missing_branches", [])}
        for start, end in sorted(arcs.get(path, set[Branch]()) - not_ran):
            problems.append(f"{path}:{start}->{end}: listed as unreachable, but it ran or is not a branch")
        for start, end in sorted(not_ran):
            if end not in skip and start not in skip and (start, end) not in arcs.get(path, set[Branch]()):
                target = f"line {end}" if end > 0 else "the function's exit"
                problems.append(f"{path}:{start}: the branch to {target} never ran")
    return problems


def main(argv: list[str]) -> int:
    report_path, list_path = argv
    with open(report_path) as f:
        report: FullReport = json.load(f)
    listed, arcs, problems = read_list(list_path)
    problems += check(report, listed, arcs)
    count = sum(len(lines) for lines in listed.values())
    branch_count = sum(len(b) for b in arcs.values())
    for problem in problems:
        print(f"coverage: {problem}", file=sys.stderr)
    if problems:
        print(f"coverage: FAILED with {len(problems)} problems", file=sys.stderr)
        return 1
    total = report["totals"]
    print(f"coverage: 100% of {total['num_statements']} statements and {total['num_branches']} branches in "
          f"src/sleep_control, apart from the {count} lines and {branch_count} branch(es) listed in {list_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
