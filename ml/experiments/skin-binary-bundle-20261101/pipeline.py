"""Run reviewed training, final evaluation, reports and bundle creation with logs."""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUTPUT = ROOT / "ml/runs/skin-binary-bundle-20261101"


def status(stage, **values):
    payload = dict(
        stage=stage, pid=os.getpid(), updated=datetime.now().astimezone().isoformat(), **values
    )
    temporary = OUTPUT / "pipeline-status.tmp"
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(OUTPUT / "pipeline-status.json")


def execute(stage, script, *arguments):
    status(stage, arguments=list(arguments))
    with (OUTPUT / f"{stage}.log").open("a", encoding="utf-8") as log:
        subprocess.run(
            [sys.executable, "-u", str(HERE / script), *arguments],
            cwd=ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=True,
        )


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    try:
        for task in ("pigmentation", "wrinkle"):
            summary = OUTPUT / task / "summary.json"
            if not summary.exists():
                execute(f"train-{task}", "experiment.py", "train", "--task", task)
        for task in ("pigmentation", "wrinkle"):
            summary = json.loads((OUTPUT / task / "summary.json").read_text(encoding="utf-8"))
            if "candidate_test" not in summary:
                execute(f"evaluate-{task}", "experiment.py", "evaluate", "--task", task)
        if not (OUTPUT / "bundle/manifest.json").exists():
            execute("build-bundle", "bundle.py", "build")
        status("complete", bundle=str(OUTPUT / "bundle"), archive=str(OUTPUT / "bundle.zip"))
    except Exception as error:
        status("error", error=str(error))
        raise


if __name__ == "__main__":
    main()
