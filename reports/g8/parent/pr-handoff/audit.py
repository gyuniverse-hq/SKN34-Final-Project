"""Record the approved formatting change without rerunning live consultations."""

import ast
import hashlib
import json
import os
import re
import runpy
import subprocess
import sys
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
BASE = "d4ae462c5d89f9efd3710a5a60fa0e281d64fd31"
DEVELOP = "991dd634dba33b99ceeb1c03de4dd8d921ce07f9"
TARGETS = """backend/api/app/repositories/oy_catalog_repository.py
backend/api/app/schemas/product_option.py
backend/api/app/services/product_option_service.py
backend/api/tests/test_product_options.py
backend/api/tests/test_style_looks.py
backend/chatbot/app/schemas/consultation_parent.py
backend/chatbot/app/services/beauty_consultation_service.py
backend/chatbot/app/services/chat_service.py
backend/chatbot/app/services/compound_consultation_graph.py
backend/chatbot/app/services/consultation_intent_service.py
backend/chatbot/app/services/consultation_parent_graph.py
backend/chatbot/app/services/owned_look_consultation_service.py
backend/chatbot/tests/test_beauty_consultation.py
backend/chatbot/tests/test_g4_option_search.py
backend/chatbot/tests/test_g7_conversation_api_pg.py
backend/chatbot/tests/test_g7_memory_api_pg.py
backend/chatbot/tests/test_g8_compound_consultation.py
backend/chatbot/tests/test_g8_consultation_intent.py
backend/chatbot/tests/test_g8_consultation_parent.py
backend/chatbot/tests/test_g8_owned_look.py
backend/chatbot/tests/test_knowledge_service.py""".splitlines()
DOCS = ["docs/ai-design/G8-WORKLOG.md", "docs/ai-design/G8-IMPLEMENTATION-SPEC.md"]
ARTIFACTS = [
    "audit.py",
    "manifest.json",
    "formatting.patch",
    "verification.json",
    "checks.log",
    "security.log",
]


def now():
    return datetime.now(UTC).isoformat()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def ast_digest(data):
    tree = ast.parse(data.decode("utf-8"), type_comments=True)
    return digest(ast.dump(tree, include_attributes=False).encode())


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def write(name, data):
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load():
    return json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))


def baseline():
    assert len(TARGETS) == 21 and git("rev-parse", "HEAD").decode().strip() == BASE
    assert not (OUT / "manifest.json").exists(), "Do not replace an earlier baseline"
    assert not git("diff", "--name-only").strip()
    tracked = git("ls-files", "-z").decode().split("\0")
    sources, evidence = [], []
    prefixes = (
        "backend/",
        "app/",
        "components/",
        "hooks/",
        "lib/",
        "store/",
        "types/",
        "server/",
        "constants/",
        "__tests__/",
    )
    for name in filter(None, tracked):
        path = ROOT / name
        if name.startswith("reports/g8/"):
            evidence.append({"path": name, "sha256": digest(path.read_bytes())})
        elif name.startswith(prefixes) and path.suffix in {".py", ".ts", ".tsx"}:
            sources.append({"path": name, "sha256": digest(path.read_bytes())})
    write(
        "manifest.json",
        {
            "at": now(),
            "baselineHead": BASE,
            "integratedDevelop": DEVELOP,
            "branch": git("branch", "--show-current").decode().strip(),
            "before": [
                {
                    "path": p,
                    "sha256": digest((ROOT / p).read_bytes()),
                    "astSha256": ast_digest((ROOT / p).read_bytes()),
                }
                for p in TARGETS
            ],
            "sourcesBefore": sources,
            "priorEvidenceBefore": evidence,
            "allowedDocuments": DOCS,
            "allowedArtifacts": ARTIFACTS,
            "baselineDocuments": [
                {"path": p, "sha256": digest((ROOT / p).read_bytes())} for p in DOCS
            ],
            "paidModelCallsPlanned": 0,
            "commitPushPRDeployAuthorized": False,
        },
    )
    print(f"Baseline saved: {len(sources)} sources, {len(evidence)} old evidence files")


def record_command(command, cwd):
    started = datetime.now(UTC)
    env = os.environ.copy()
    for key in list(env):
        if key.startswith(("TEST_", "ADMIN_TEST_", "VISHUE_RUN_", "G8_")):
            env.pop(key)
    env["G7_ALLOW_DESTRUCTIVE_TESTS"] = "0"
    result = subprocess.run(
        command, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    header = {
        "at": started.isoformat(),
        "cwd": str(cwd),
        "command": command,
        "seconds": round((datetime.now(UTC) - started).total_seconds(), 3),
        "exit": result.returncode,
        "databaseAndLiveOptIn": "disabled",
    }
    data = b"\n" + json.dumps(header).encode() + b"\n" + result.stdout
    fd = os.open(OUT / "checks.log", os.O_WRONLY | os.O_CREAT | os.O_APPEND)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    print(json.dumps(header), flush=True)
    assert result.returncode == 0, "See checks.log; do not change product behavior"


def format_targets():
    for service in ("api", "chatbot"):
        cwd = ROOT / "backend" / service
        names = [
            str(Path(p).relative_to(Path("backend") / service))
            for p in TARGETS
            if p.startswith(f"backend/{service}/")
        ]
        record_command(
            ["uv", "run", "--frozen", "--no-sync", "ruff", "format", "--no-cache", *names], cwd
        )
    m = load()
    m["after"] = []
    for row in m["before"]:
        content = (ROOT / row["path"]).read_bytes()
        same = ast_digest(content) == row["astSha256"]
        m["after"].append(
            {
                "path": row["path"],
                "sha256": digest(content),
                "astSha256": ast_digest(content),
                "astEqual": same,
            }
        )
    write("manifest.json", m)
    assert all(row["astEqual"] for row in m["after"]), "AST differs; stop and investigate"
    (OUT / "formatting.patch").write_bytes(git("diff", "--binary", BASE, "--", *TARGETS))
    print("All 21 ASTs identical (type comments included, line/column attributes excluded)")


def checks(service):
    cwd = ROOT / "backend" / service
    for args in (
        ["ruff", "format", "--check", "--no-cache", "."],
        ["ruff", "check", "--no-cache", "."],
        ["lint-imports"],
    ):
        record_command(["uv", "run", "--frozen", "--no-sync", *args], cwd)
    scratch = Path(tempfile.gettempdir()) / ("vishue-g8-handoff-" + uuid.uuid4().hex[:10])
    record_command(
        [
            "uv",
            "run",
            "--frozen",
            "--no-sync",
            "python",
            "-B",
            "-m",
            "pytest",
            "-q",
            "-ra",
            "--tb=short",
            "-p",
            "no:cacheprovider",
            "--basetemp",
            str(scratch),
        ],
        cwd,
    )


def integrity():
    m = load()
    changed = [
        r["path"]
        for r in m["sourcesBefore"]
        if digest((ROOT / r["path"]).read_bytes()) != r["sha256"]
    ]
    old_evidence = [
        r["path"]
        for r in m["priorEvidenceBefore"]
        if digest((ROOT / r["path"]).read_bytes()) != r["sha256"]
    ]
    assert set(changed) == set(TARGETS) and not old_evidence
    allowed = set(
        TARGETS + DOCS + [str((OUT / n).relative_to(ROOT)).replace("\\", "/") for n in ARTIFACTS]
    )
    actual = set(git("diff", "--name-only").decode().splitlines())
    actual.update(git("ls-files", "--others", "--exclude-standard").decode().splitlines())
    assert not (actual - allowed), "Changed paths outside the 29-file approval"
    assert git("rev-parse", "HEAD").decode().strip() == BASE
    assert not git("diff", "--cached", "--name-only").strip()
    return {
        "sourcesChecked": len(m["sourcesBefore"]),
        "changedSources": len(changed),
        "oldEvidenceChecked": len(m["priorEvidenceBefore"]),
        "oldEvidenceChanged": 0,
        "outsideApproval": [],
        "headUnchanged": True,
    }


def security():
    # Reuse only the existing read-only environment loader; never log its values.
    previous = runpy.run_path(str(OUT.parent / "closing-last" / "audit.py"), run_name="read_keys")
    env = previous["base"].live_environment()
    protected = [
        v
        for k, v in env.items()
        if isinstance(v, str)
        and len(v) > 10
        and any(t in k.upper() for t in ("KEY", "TOKEN", "PASSWORD", "SECRET"))
        and "PUBLISHABLE" not in k
        and not k.startswith("EXPO_PUBLIC_")
    ]
    counts = {"protectedValue": 0, "jwt": 0, "privateKey": 0, "email": 0}
    for p in OUT.iterdir():
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        counts["protectedValue"] += sum(v in text for v in protected)
        counts["jwt"] += len(re.findall(r"eyJ[\w-]{12,}\.[\w-]{12,}\.[\w-]{12,}", text))
        counts["privateKey"] += len(re.findall(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", text))
        text = re.sub(
            r"(?m)^([ +\-]*)@pytest\.(?:mark\.[A-Za-z_]\w*|fixture)\b", r"\1PYTEST_DECORATOR", text
        )
        counts["email"] += len(re.findall(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text))
    with (OUT / "security.log").open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps({"at": now(), "counts": counts, "pytestDecoratorClassificationOnly": True})
            + "\n"
        )
    assert not any(counts.values()), "Review category counts; never print matched values"
    linux_root = "/mnt/" + ROOT.drive[0].lower() + ROOT.as_posix()[2:]
    scanner = ["wsl", "-d", "vishue-g5", "--", "/var/tmp/g8-gitleaks-audit-20261126/gitleaks"]
    options = [
        "--config",
        linux_root + "/.gitleaks.toml",
        "--gitleaks-ignore-path",
        "/dev/null",
        "--redact",
        "--verbose",
    ]
    scans = [
        (
            "new-evidence",
            scanner
            + ["dir", linux_root + "/" + str(OUT.relative_to(ROOT)).replace("\\", "/"), *options],
            None,
        ),
        ("working-diff", scanner + ["stdin", *options], git("diff", "--no-ext-diff")),
    ]
    for name, command, data in scans:
        result = subprocess.run(
            command, input=data, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        with (OUT / "security.log").open("ab") as stream:
            stream.write(
                (
                    "\n"
                    + json.dumps(
                        {
                            "at": now(),
                            "scan": name,
                            "command": command,
                            "exit": result.returncode,
                            "version": "8.30.1",
                        }
                    )
                    + "\n"
                ).encode()
            )
            stream.write(result.stdout)
        assert result.returncode == 0, "Review redacted security.log"
    print("New evidence and working diff security PASS; protected-value counts all zero")


if __name__ == "__main__":
    action = sys.argv[1]
    if action == "baseline":
        baseline()
    elif action == "format":
        format_targets()
    elif action in {"api", "chatbot"}:
        checks(action)
    elif action == "app":
        for name in ("typecheck", "lint"):
            record_command(["npm.cmd", "run", name], ROOT)
    elif action == "integrity":
        print(json.dumps(integrity()))
    elif action == "security":
        security()
