"""Opt-in real infrastructure test. Environment failure never becomes a mock PASS."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(
    os.environ.get("VISHUE_RUN_REDIS_INTEGRATION") != "1",
    reason="Real Redis opt-in: set VISHUE_RUN_REDIS_INTEGRATION=1",
)
def test_real_redis_two_http_processes():
    result = subprocess.run(
        [sys.executable, "-B", "-m", "tests.run_redis_sessions"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=120,
    )
    report = json.loads(result.stdout.strip().splitlines()[-1])
    print(json.dumps(report))  # Sanitized runner report, never response bodies/capabilities.
    assert result.returncode == 0, report
    assert report["realRedisConnected"] and report["realHttpProcesses"] == 2
    assert report["failed"] == 0 and report["cleanup"]
    assert report["passed"] == 12 and report["existingContainersUnchanged"]
