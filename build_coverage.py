
"""Build a test-to-source-file coverage map for pinned sqlglot."""

import json
import os
import sys
from pathlib import Path

import coverage
import pytest

ROOT = Path("/build/sqlglot").resolve()
TESTS_FILE = Path("/build/tests.json")
OUTPUT = Path("/build/coverage.json")


class PerTestCoverage:
    """Switch coverage context for each individual pytest test."""

    def __init__(self, collector):
        self.collector = collector

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_protocol(self, item):
        self.collector.switch_context(item.nodeid)
        yield
        self.collector.switch_context("between-tests")


def main():
    inventory = json.loads(TESTS_FILE.read_text(encoding="utf-8"))["tests"]
    number_by_id = {test["id"]: test["number"] for test in inventory}
    source_to_tests = {}

    os.chdir(ROOT)

    collector = coverage.Coverage(
        data_file=None,
        source=[str(ROOT / "sqlglot")],
        config_file=False,
    )

    collector.start()

    result = pytest.main(
        ["-q", "tests", "-p", "no:cacheprovider"],
        plugins=[PerTestCoverage(collector)],
    )

    collector.stop()

    data = collector.get_data()

    for filename in data.measured_files():
        path = Path(filename).resolve()

        try:
            relative = path.relative_to(ROOT).as_posix()
        except ValueError:
            continue

        if not relative.startswith("sqlglot/"):
            continue

        if not relative.endswith(".py"):
            continue

        test_ids = set()

        for contexts in data.contexts_by_lineno(filename).values():
            for context in contexts:
                if context in number_by_id:
                    test_ids.add(context)

        if test_ids:
            source_to_tests[relative] = sorted(
                number_by_id[test_id] for test_id in test_ids
            )

    OUTPUT.write_text(
        json.dumps(
            {
                "commit": "eb11aec4be8cb2122afe713a4816662c3f0fb2fa",
                "source_to_tests": source_to_tests,
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )

    mapped = sum(len(numbers) for numbers in source_to_tests.values())

    print(
        f"Coverage map: {len(source_to_tests)} source files, "
        f"{mapped} file-test relationships",
        file=sys.stderr,
    )

    print(f"pytest exit code: {result}", file=sys.stderr)
    print(f"Coverage map written to {OUTPUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
