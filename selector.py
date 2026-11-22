
"""Blast Radius selector: conservative coverage-based test selection."""

import json
import shlex
import sys
from pathlib import Path

DATA = Path("/data")
COVERAGE_FILE = Path("/app/coverage.json")
EXPECTED_COMMIT = "eb11aec4be8cb2122afe713a4816662c3f0fb2fa"
WORKERS = 3


def split(tests: list[dict], worker_count: int) -> list[list[int]]:
    """Longest test first, each onto the worker with the least work so far."""
    workers: list[list[int]] = [[] for _ in range(worker_count)]
    loads = [0.0] * worker_count

    for test in sorted(
        tests, key=lambda test: test["seconds"], reverse=True
    ):
        lightest = loads.index(min(loads))
        workers[lightest].append(test["number"])
        loads[lightest] += test["seconds"]

    return workers


def changed_paths(patch_path: Path) -> set[str]:
    """Return old and new paths mentioned in a unified Git diff."""
    paths: set[str] = set()

    for line in patch_path.read_text(
        encoding="utf-8", errors="replace"
    ).splitlines():
        if not line.startswith("diff --git "):
            continue

        try:
            parts = shlex.split(line)
        except ValueError:
            continue

        if len(parts) != 4:
            continue

        for token, prefix in ((parts[2], "a/"), (parts[3], "b/")):
            if token == "/dev/null":
                continue
            if token.startswith(prefix):
                paths.add(token[len(prefix):])

    return paths


def describe_patch(paths: set[str]) -> str:
    """Summarize patch paths for diagnostics."""
    source = sum(path.startswith("sqlglot/") for path in paths)
    tests = sum(
        path.startswith("tests/") and "fixtures/" not in path
        for path in paths
    )
    fixtures = sum("tests/fixtures/" in path for path in paths)
    other = len(paths) - source - tests - fixtures

    return (
        f"{len(paths)} paths "
        f"(source={source}, test_files={tests}, "
        f"fixtures={fixtures}, other={other})"
    )


def load_coverage() -> dict[str, set[int]]:
    """Load and validate the source-file-to-test-number mapping."""
    raw = json.loads(COVERAGE_FILE.read_text(encoding="utf-8"))

    if raw.get("commit") != EXPECTED_COMMIT:
        raise ValueError("Coverage map has the wrong repository commit")

    source_map = raw.get("source_to_tests")
    if not isinstance(source_map, dict):
        raise ValueError("Coverage map has no valid source_to_tests object")

    result: dict[str, set[int]] = {}

    for path, numbers in source_map.items():
        if not isinstance(path, str) or not isinstance(numbers, list):
            raise ValueError("Malformed coverage map entry")

        if not all(type(number) is int for number in numbers):
            raise ValueError(f"Invalid test number in coverage entry: {path}")

        result[path] = set(numbers)

    return result


def select_tests(
    paths: set[str],
    tests: list[dict],
    source_map: dict[str, set[int]],
    always_include: set[int],
) -> tuple[list[dict], str]:
    """Select tests conservatively for one patch."""
    all_tests = {test["number"]: test for test in tests}

    def fallback(reason: str) -> tuple[list[dict], str]:
        return tests, f"all tests (fallback: {reason})"

    if not paths:
        return fallback("no changed paths could be parsed")

    # These subsystems have cross-cutting dependencies that direct
    # execution coverage does not reliably capture.
    high_risk_prefixes = (
        "sqlglot/optimizer/",
        "sqlglot/dialects/",
        "sqlglot/parsers/",
    )

    high_risk_paths = [
        path for path in paths
        if path.startswith(high_risk_prefixes)
    ]

    if high_risk_paths:
        return fallback(
            "high-risk subsystem change: "
            + ", ".join(sorted(high_risk_paths))
        )

    selected: set[int] = set()
    saw_source = False
    saw_test_file = False

    for path in paths:
        if path.startswith("sqlglot/"):
            saw_source = True

            # An unmapped source file may have indirect effects.
            if path not in source_map:
                return fallback(f"source file absent from coverage map: {path}")

            selected.update(source_map[path])

        elif path.startswith("tests/fixtures/"):
            # Fixture dependencies aren't represented by source coverage.
            return fallback(f"fixture changed: {path}")

        elif path.startswith("tests/") and path.endswith(".py"):
            saw_test_file = True
            matching = {
                test["number"]
                for test in tests
                if test["file"] == path
            }

            # A new or unrecognized test file is not safely mappable.
            if not matching:
                return fallback(f"test file absent from inventory: {path}")

            selected.update(matching)

        else:
            # Documentation, configuration, build files, and unknown paths
            # may have effects not represented in the coverage map.
            return fallback(f"unrecognized changed path: {path}")

    # Always retain tests that did not execute any measured SQLGlot source.
    selected.update(always_include)

    # Defensive check: never emit a test number absent from the inventory.
    if not selected.issubset(all_tests):
        return fallback("coverage map contains unknown test numbers")

    chosen = [
        test for test in tests
        if test["number"] in selected
    ]

    reasons = []
    if saw_source:
        reasons.append("source coverage")
    if saw_test_file:
        reasons.append("changed test files")
    reasons.append("unmapped tests retained")

    return chosen, ", ".join(reasons)


def main() -> None:
    tests = json.loads(
        (DATA / "tests.json").read_text(encoding="utf-8")
    )["tests"]

    all_numbers = {test["number"] for test in tests}

    try:
        source_map = load_coverage()
        mapped_numbers = {
            number
            for numbers in source_map.values()
            for number in numbers
        }

        if not mapped_numbers.issubset(all_numbers):
            raise ValueError("Coverage map contains unknown test numbers")

        # Automatically retain every inventory test not represented
        # in any source-file coverage relationship.
        always_include = all_numbers - mapped_numbers

    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(
            f"WARNING: coverage map unavailable or invalid: {error}",
            file=sys.stderr,
        )
        source_map = {}
        always_include = all_numbers

    patches = sorted((DATA / "commits").glob("*.patch"))

    for patch in patches:
        paths = changed_paths(patch)

        selected, reason = select_tests(
            paths,
            tests,
            source_map,
            always_include,
        )

        workers = split(selected, WORKERS) if selected else []

        print(
            f"{patch.stem}: {describe_patch(paths)}; "
            f"selected {len(selected)}/{len(tests)} tests "
            f"({reason})",
            file=sys.stderr,
        )

        print(json.dumps({
            "commit": patch.stem,
            "workers": workers,
        }))

    print(
        f"Processed {len(patches)} commits; "
        f"{len(tests)} tests available",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
