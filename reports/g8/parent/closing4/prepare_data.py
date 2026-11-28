"""Approved clone-only preparation. Original databases are read/dumped, never migrated."""

import hashlib
import json
import os
import secrets
import shlex
import subprocess
import time
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
PRIVATE = Path(os.environ["TEMP"]) / "vishue-g8-closing4-506ab47f"
PG = "vishue-g8-closing4-pg"
REDIS = "vishue-g8-closing4-redis"
LABEL = "closing4-506ab47f"
DATABASES = {
    "catalog": "vishue_g8_closing4_catalog",
    "g5": "vishue_g8_closing4_knowledge",
    "chat": "vishue_g8_closing4_chat",
}


def inspect(name):
    return json.loads(subprocess.check_output(["docker", "inspect", name], text=True))[0]


def container_env(name):
    return dict(item.split("=", 1) for item in inspect(name)["Config"]["Env"] if "=" in item)


def record(**values):
    path = OUT / "manifest.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data.update(values)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def clone_url(database):
    obj = inspect(PG)
    assert obj["Config"]["Labels"]["vishue.g8-evaluation"] == LABEL
    port = int(obj["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostPort"])
    env = container_env(PG)
    from sqlalchemy.engine import URL

    assert database in DATABASES.values()
    return URL.create(
        "postgresql+asyncpg",
        username="g8_eval",
        password=env["POSTGRES_PASSWORD"],
        host="127.0.0.1",
        port=port,
        database=database,
    )


def psql(container, database, query):
    user = container_env(container).get("POSTGRES_USER", "postgres")
    return subprocess.check_output(
        ["docker", "exec", container, "psql", "-XqAt", "-U", user, "-d", database, "-c", query],
        text=True,
    ).strip()


def source_metadata():
    query = (
        "BEGIN READ ONLY; SELECT json_build_object("
        "'version',current_setting('server_version'),"
        "'revision',(SELECT version_num FROM alembic_version),"
        "'products',(SELECT count(*) FROM products),"
        "'rawOptions',(SELECT count(*) FROM raw_oy_product_option),"
        "'bytes',pg_database_size(current_database())); ROLLBACK;"
    )
    return json.loads(psql("vishue-postgres-0033", "vishue_db", query))


def wsl_command(program, extra):
    private = dotenv_values("D:/dev/02_TeamProjects/SKN34-Final-Project/.env.local")
    url = make_url(private["DATABASE_URL"])
    assert url.database and url.username and "\n" not in (url.password or "")
    # Password is sent over stdin, never argv or a repository file.
    command = [
        program,
        "-h",
        "127.0.0.1",
        "-p",
        "15441",
        "-U",
        url.username,
        "-d",
        url.database,
        *extra,
    ]
    script = (
        "export PGPASSWORD="
        + shlex.quote(url.password or "")
        + "\nexec "
        + shlex.join(command)
        + "\n"
    )
    return ["wsl", "-d", "vishue-g5", "--", "sh", "-s"], script.encode()


def run_logged(args, **kwargs):
    with (OUT / "data-preparation.log").open("ab") as log:
        result = subprocess.run(args, stdout=log, stderr=log, **kwargs)
    assert result.returncode == 0, "Preparation command failed; inspect scoped log"


def main():
    PRIVATE.mkdir(parents=True, exist_ok=True)
    assert (
        subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        == json.loads((OUT / "plan.json").read_text(encoding="utf-8"))["sourceHead"]
    )
    before = source_metadata()
    record(
        sourceHead="506ab47f617b8fcdae7e78d9de651d9c6c1fb3f5", sourceBefore=before, originalWrites=0
    )
    dumps = json.loads((OUT / "manifest.json").read_text(encoding="utf-8")).get("dumps", [])
    for role in ("catalog", "g5"):
        previous = next((item for item in dumps if item["role"] == role), None)
        if previous:
            with Path(previous["privatePath"]).open("rb") as stream:
                assert hashlib.file_digest(stream, "sha256").hexdigest() == previous["sha256"]
            continue
        path = PRIVATE / f"{role}.dump"
        attempt = 1
        while path.exists():
            attempt += 1
            path = PRIVATE / f"{role}-{attempt}.dump"
        if role == "catalog":
            user = container_env("vishue-postgres-0033").get("POSTGRES_USER", "postgres")
            cmd = [
                "docker",
                "exec",
                "vishue-postgres-0033",
                "pg_dump",
                "-U",
                user,
                "-d",
                "vishue_db",
                "-Fc",
                "-Z1",
                "--no-owner",
                "--no-acl",
            ]
            password = None
        else:
            cmd, password = wsl_command("pg_dump", ["-Fc", "-Z1", "--no-owner", "--no-acl"])
        with path.open("wb") as output, (OUT / "data-preparation.log").open("ab") as log:
            result = subprocess.run(cmd, input=password, stdout=output, stderr=log)
        assert result.returncode == 0 and path.stat().st_size > 0, "Dump failed"
        dumps.append(
            {
                "role": role,
                "bytes": path.stat().st_size,
                "sha256": hashlib.file_digest(path.open("rb"), "sha256").hexdigest(),
                "privatePath": str(path),
            }
        )
        record(dumps=dumps)
        print(f"{role} dump preserved: {path.stat().st_size} bytes", flush=True)
    if (
        subprocess.run(
            ["docker", "inspect", PG], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        ).returncode
        != 0
    ):
        run_logged(
            [
                "docker",
                "run",
                "-d",
                "--name",
                PG,
                "--label",
                f"vishue.g8-evaluation={LABEL}",
                "-e",
                "POSTGRES_USER=g8_eval",
                "-e",
                "POSTGRES_PASSWORD=" + secrets.token_urlsafe(32),
                "-p",
                "127.0.0.1::5432",
                "pgvector/pgvector:0.8.2-pg17-bookworm",
            ]
        )
    else:
        assert inspect(PG)["Config"]["Labels"]["vishue.g8-evaluation"] == LABEL
    for _ in range(60):
        if (
            subprocess.run(
                ["docker", "exec", PG, "pg_isready", "-h", "127.0.0.1", "-U", "g8_eval"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ).returncode
            == 0
        ):
            break
        time.sleep(0.5)
    else:
        raise AssertionError("Clone PG not ready")
    for role, database in DATABASES.items():
        exists = (
            psql(
                PG, "postgres", "SELECT count(*) FROM pg_database WHERE datname='" + database + "'"
            )
            == "1"
        )
        manifest = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
        restored = manifest.get("restoredRoles", [])
        if exists:
            assert role in restored, "Do not overwrite an unconfirmed evaluation database"
        else:
            run_logged(["docker", "exec", PG, "createdb", "-U", "g8_eval", database])
        if role != "chat" and not exists:
            with Path(next(item["privatePath"] for item in dumps if item["role"] == role)).open(
                "rb"
            ) as dump:
                run_logged(
                    [
                        "docker",
                        "exec",
                        "-i",
                        PG,
                        "pg_restore",
                        "-U",
                        "g8_eval",
                        "-d",
                        database,
                        "--no-owner",
                        "--no-acl",
                        "--exit-on-error",
                    ],
                    stdin=dump,
                )
        if role not in restored:
            record(restoredRoles=[*restored, role])
        env = dict(
            os.environ,
            PYTHONUTF8="1",
            PYTHONDONTWRITEBYTECODE="1",
            SKINCARE_REFRESH_ENABLED="false",
        )
        env["DATABASE_URL" if role != "chat" else "CHAT_DATABASE_URL"] = clone_url(
            database
        ).render_as_string(hide_password=False)
        folder = ROOT / "backend" / ("chatbot" if role == "chat" else "api")
        python = str(folder / ".venv/Scripts/python.exe")
        if role == "g5" and psql(PG, database, "SELECT version_num FROM alembic_version") == "0030":
            checks = manifest.get("g5LegacySchemaChecks", [])
            assert len(checks) == 3 and all(item["equal"] for item in checks)
            # Only the clone: existing 0031/0032 columns, constraints and indexes match exactly.
            run_logged([python, "-B", "-m", "alembic", "stamp", "0032"], cwd=folder, env=env)
            record(
                g5CloneRevisionReconciled=(
                    "0030 -> 0032 after exact schema comparison; original unchanged"
                )
            )
        run_logged([python, "-B", "-m", "alembic", "upgrade", "head"], cwd=folder, env=env)
        if role == "catalog":
            for args in ([], ["--write"], []):
                run_logged(
                    [python, "-B", "-m", "app.jobs.load_makeup_look_catalog", *args],
                    cwd=folder,
                    env=env,
                )
        if role == "chat":
            run_logged([python, "-B", "-m", "app.jobs.init_chat_checkpoints"], cwd=folder, env=env)
        print(f"{role} clone migrated", flush=True)
    run_logged(
        [
            "docker",
            "run",
            "-d",
            "--name",
            REDIS,
            "--label",
            f"vishue.g8-evaluation={LABEL}",
            "-p",
            "127.0.0.1::6379",
            "redis:7-alpine",
            "redis-server",
            "--save",
            "",
            "--appendonly",
            "no",
        ]
    )
    after = source_metadata()
    assert before == after, "Original metadata changed during evaluation setup"
    record(
        sourceAfterPreparation=after,
        databases=DATABASES,
        cloneContainer=PG,
        redisContainer=REDIS,
        prepared=True,
    )
    print("Clone-only preparation complete; original metadata unchanged", flush=True)


if __name__ == "__main__":
    main()
