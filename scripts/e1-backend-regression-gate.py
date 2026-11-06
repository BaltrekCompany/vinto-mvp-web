#!/usr/bin/env python3
"""Run EVERY backend unittest and fail on any result beyond the exact pre-E1 baseline.

This is a differential gate, not a claim that the historical suite is green.
The baseline contains every known FAIL/ERROR, including repeated test names.
Delete allowances as historical failures are repaired; never add new allowances
without independent pre-E1 evidence and review.
"""
from collections import Counter
from pathlib import Path
import json
import re
import subprocess
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent / "backend"
BASELINE = SCRIPT_DIR / "e1-backend-regression-baseline.json"


def main() -> int:
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    expected = Counter(
        (item["kind"], item["name"]) for item in baseline["allowed_existing_results"]
    )
    assert sum(expected.values()) == 105, "The audited original baseline must have 105 results"
    command = [
        sys.executable, "-B", "-m", "unittest", "discover",
        "-s", "tests", "-p", "test_*.py", "-v",
    ]
    print("Running full backend discovery; flag OFF and disposable PG17 only.", flush=True)
    process = subprocess.Popen(
        command, cwd=BACKEND_DIR, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
        bufsize=1,
    )
    chunks = []
    assert process.stdout is not None
    for n, line in enumerate(process.stdout, 1):
        chunks.append(line)
        if n % 400 == 0:
            print(f"Backend discovery output received: {n} lines", flush=True)
    exit_code = process.wait()
    output = "".join(chunks)

    rows = re.findall(r"(?m)^(FAIL|ERROR): ([^\r\n]+)", output)
    observed = Counter(rows)
    extra = observed - expected
    resolved = expected - observed
    totals = re.findall(r"\bRan (\d+) tests in [0-9.]+s", output)
    executed = int(totals[-1]) if totals else -1
    summaries = re.findall(r"FAILED \(([^)]*)\)", output)
    summary = dict(
        (name, int(value))
        for name, value in re.findall(r"(\w+)=(\d+)", summaries[-1])
    ) if summaries else {}
    counted_failures = sum(n for (kind, _), n in observed.items() if kind == "FAIL")
    counted_errors = sum(n for (kind, _), n in observed.items() if kind == "ERROR")
    skipped = summary.get("skipped", 0)

    problems = []
    if exit_code not in (0, 1):
        problems.append(f"Unexpected runner exit code {exit_code}")
    if executed < baseline["minimum_candidate_tests"]:
        problems.append(f"Incomplete test discovery: {executed} tests")
    if skipped > baseline["maximum_candidate_skips"]:
        problems.append(f"New skipped tests detected: {skipped}")
    if summaries and (
        counted_failures != summary.get("failures", 0)
        or counted_errors != summary.get("errors", 0)
    ):
        problems.append("Unparsed FAILURE/ERROR result; cannot trust comparison")
    if exit_code != 0 and not summaries:
        problems.append("Unittest failed without a recognizable summary")
    if exit_code == 0 and observed:
        problems.append("Unittest exit 0 but failures were parsed")
    if extra:
        problems.append(f"{sum(extra.values())} NEW FAIL/ERROR results beyond pre-E1 main")

    print(
        f"Tests={executed}; historical FAIL={counted_failures}; "
        f"historical ERROR={counted_errors}; skipped={skipped}; "
        f"resolved historical={sum(resolved.values())}; "
        f"new={sum(extra.values())}; raw_unittest_exit={exit_code}",
        flush=True,
    )
    if extra:
        for (kind, name), quantity in sorted(extra.items()):
            print(f"NEW {kind} x{quantity}: {name}", flush=True)
            location = output.rfind(f"{kind}: {name}")
            if location >= 0:
                print(output[location:location + 1700], flush=True)
    for problem in problems:
        print("NO-GO:", problem, flush=True)
    if problems:
        return 1
    print(
        "PASS differential only: all historical failures remain visible "
        "and there are NO additional backend failures.",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
