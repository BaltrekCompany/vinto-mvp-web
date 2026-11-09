#!/usr/bin/env python3
"""Run ONLY formerly-new E1-08 failures on isolated PG17; zero tolerated failures.

This is supplemental evidence, NOT a substitute for the immutable original
E1 broad regression gate. Do not suppress/skips/approve legacy failures.
"""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
TESTS = BACKEND / "tests"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(TESTS))

def main() -> int:
    config = json.loads((ROOT / "scripts/mp3-rg01-broad-focus.json").read_text(encoding="utf-8"))
    names = config["tests"]
    assert len(names) == config["count"] == len(set(names)), "Do not weaken focused regression census"
    assert len(names) >= 50, "Expected complete 56-result baseline, not a reduced subset"
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for name in names:
        selected = loader.loadTestsFromName(name)
        assert selected.countTestCases() == 1, f"Unresolvable test: {name}"
        suite.addTests(selected)
    print(f"MP3_FOCUSED_TEST_COUNT={suite.countTestCases()}", flush=True)
    result = unittest.TextTestRunner(verbosity=2, failfast=False).run(suite)
    print(
        f"MP3_E108_FOCUS= {'PASS' if result.wasSuccessful() else 'FAIL'} "
        f"tests={result.testsRun} failures={len(result.failures)} "
        f"errors={len(result.errors)} skipped={len(result.skipped)}",
        flush=True,
    )
    if result.testsRun != len(names) or result.skipped:
        return 1
    return 0 if result.wasSuccessful() else 1

if __name__ == "__main__":
    raise SystemExit(main())
