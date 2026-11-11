"""Upsert a complete Olive Young CSV snapshot into existing raw_oy_* tables.

Stage IDs are never copied to the shared DB. Existing ingredient IDs and the
serving-catalog flag are preserved. Use --preflight before --apply.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import getpass
import hashlib
import json
import os
import ssl
from pathlib import Path

import asyncpg
from collect_snapshot import unavailable_records

LOOKUPS = {
    "brand": "brand_code",
    "supplier": "supplier_code",
    "category": "category_no",
    "survey_question": "question_code",
    "survey_answer": "answer_code",
    "image_applied": "image_url",
}


def _files(directory: Path, kind: str) -> dict[str, tuple[Path, list[str], int]]:
    manifest_path = directory / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("Snapshot manifest.json is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("kind") != kind
        or not manifest.get("listing_complete")
        or not manifest.get("complete")
    ):
        raise ValueError("Only a complete snapshot of the selected kind can be loaded")
    expected = {str(job[1]) for job in manifest["jobs"]}
    if not expected or len(expected) != len(manifest["jobs"]):
        raise ValueError(
            "Snapshot listing is empty or contains duplicate goods numbers"
        )
    unavailable = unavailable_records(manifest)
    if manifest.get("unavailable_count", len(unavailable)) != len(unavailable):
        raise ValueError("Snapshot unavailable count differs from its records")
    collected = expected - set(unavailable)
    if manifest.get("collected_count") != len(collected):
        raise ValueError("Snapshot collected count differs from its listing")
    tables = (
        "crawl_run",
        "brand",
        "supplier",
        "category",
        "survey_question",
        "survey_answer",
        "ingredient",
        "product",
        "product_notice",
        "product_option",
        "image",
        "price_snapshot",
        "review_summary",
        "review_ai_feature",
        "review_survey",
        "option_ingredient",
        "crawl_log",
    )
    tables += (
        ("skincare_attr",)
        if kind == "skincare"
        else (
            "product_texture",
            "option_color",
            "image_applied",
        )
    )
    if manifest.get("observation_version"):
        tables += ("option_ingredient_observation",)
    files = {}
    csv.field_size_limit(100_000_000)
    for table in tables:
        path = directory / f"{table}.csv"
        if not path.is_file():
            raise ValueError(f"Missing CSV: {path}")
        with path.open(encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            columns = reader.fieldnames or []
            if not columns or len(columns) != len(set(columns)):
                raise ValueError(f"Invalid CSV header: {path}")
            count = sum(1 for _ in reader)
        files[table] = (path, columns, count)
    with files["product"][0].open(encoding="utf-8-sig", newline="") as source:
        goods = [row["goods_no"] for row in csv.DictReader(source)]
    if len(goods) != len(collected) or set(goods) != collected:
        raise ValueError(
            "Product CSV does not match the listing minus confirmed unavailable goods"
        )
    if unavailable:
        for table, (path, columns, _) in files.items():
            if "goods_no" not in columns or table == "crawl_log":
                continue
            with path.open(encoding="utf-8-sig", newline="") as source:
                if any(
                    row["goods_no"] in unavailable for row in csv.DictReader(source)
                ):
                    raise ValueError(
                        f"Confirmed unavailable goods still have {table} CSV rows"
                    )
    with files["option_ingredient"][0].open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            if not row["ingredient_id"]:
                raise ValueError(
                    "Option ingredient link has no ingredient ID: "
                    f"{row['option_id']} seq {row['seq']}"
                )
    with files["crawl_run"][0].open(encoding="utf-8-sig", newline="") as source:
        runs = [
            r for r in csv.DictReader(source) if r["run_id"] == str(manifest["run_id"])
        ]
    if len(runs) != 1 or runs[0]["status"] != "done":
        raise ValueError("The crawl-run record is not complete")
    if "option_ingredient_observation" in files:
        import oliveyoung_erd_v30 as collector

        if manifest["observation_version"] != collector.OBSERVATION_VERSION:
            raise ValueError("Unsupported observation version")
        with files["product_option"][0].open(encoding="utf-8-sig", newline="") as source:
            options = {r["option_id"] for r in csv.DictReader(source)}
        with files["option_ingredient_observation"][0].open(encoding="utf-8-sig", newline="") as source:
            observations = list(csv.DictReader(source))
        if len(observations) != len(options) or {r["option_id"] for r in observations} != options:
            raise ValueError("Exactly one observation is required for every collected option")
        def records(table, key):
            with files[table][0].open(encoding="utf-8-sig", newline="") as stream:
                return {row[key]: row for row in csv.DictReader(stream)}

        option_rows = records("product_option", "option_id")
        notices = records("product_notice", "goods_no")
        products = records("product", "goods_no")
        grouped = {}
        for option in option_rows.values():
            grouped.setdefault(option["goods_no"], []).append(dict(
                goodsNumber=option["goods_no"], optionNumber=option["option_no"],
                optionName=option["option_name"],
            ))
        for record in observations:
            validate_observation(record)
            option = option_rows[record["option_id"]]
            goods = option["goods_no"]
            notice = notices.get(goods, {})
            expected = collector.ingredient_observation(
                notice.get("ingredients_raw", ""), grouped[goods],
                dict(goodsNumber=goods, optionNumber=option["option_no"], optionName=option["option_name"]),
                option["collected_at"], products[goods].get("product_url") or "",
                notice.get("volume") or "",
            )
            if record != expected:
                raise ValueError("Observation does not reproduce its collected option and notice")
    return files


def validate_observation(record):
    import oliveyoung_erd_v30 as collector

    raw = record["raw_text"]
    if record["raw_sha256"] != hashlib.sha256(raw.encode()).hexdigest():
        raise ValueError("Observation raw hash mismatch")
    if record["source_version"] != collector.observation_version(record):
        raise ValueError("Observation source version mismatch")
    entries = json.loads(record["entries"]) if isinstance(record["entries"], str) else record["entries"]
    previous_end = 0
    for seq, entry in enumerate(entries, 1):
        start, end = entry["source_start"], entry["source_end"]
        if (entry["sequence"] != seq or not previous_end <= start < end <= len(raw)
                or raw[start:end] != entry["name"]
                or collector.norm(collector.clean_ingredient(entry["name"])) != entry["ingredient_norm"]):
            raise ValueError("Observation occurrence is not supported by its original text")
        previous_end = end


async def _apply_observations(conn, files):
    if "option_ingredient_observation" not in files:
        return  # Legacy CSVs remain loadable, but never manufacture observations.
    cols = files["option_ingredient_observation"][1]
    # Source identities may repeat. Only the identity dictionary is deduplicated.
    await conn.execute("""
        INSERT INTO raw_oy_ingredient(ingredient_name, ingredient_norm)
        SELECT DISTINCT ON (entry->>'ingredient_norm')
               entry->>'ingredient_norm', entry->>'ingredient_norm'
        FROM stg_option_ingredient_observation s
        CROSS JOIN LATERAL jsonb_array_elements(s.entries) entry
        WHERE coalesce(entry->>'ingredient_norm','') <> ''
        ORDER BY entry->>'ingredient_norm' ON CONFLICT(ingredient_norm) DO NOTHING
    """)
    selected = ["s." + c for c in cols]
    selected[cols.index("entries")] = """coalesce((
        SELECT jsonb_agg(entry || jsonb_build_object('ingredient_id', i.ingredient_id)
                         ORDER BY (entry->>'sequence')::int)
        FROM jsonb_array_elements(s.entries) entry
        JOIN raw_oy_ingredient i ON i.ingredient_norm=entry->>'ingredient_norm'
    ), '[]'::jsonb)"""
    await conn.execute(
        f"INSERT INTO raw_oy_option_ingredient_observation ({','.join(cols)}) "
        f"SELECT {','.join(selected)} FROM stg_option_ingredient_observation s "
        "JOIN raw_oy_product_option o ON o.option_id=s.option_id "
        "ON CONFLICT(option_id,source_version) DO NOTHING"
    )


def _connection_args(args: argparse.Namespace) -> dict:
    if args.target == "shared":
        if not args.project_ref:
            raise ValueError("Shared project ref is required")
        if not args.host.endswith(".pooler.supabase.com") or args.port != 5432:
            raise ValueError(
                "Shared DB requires a Supabase session pooler on port 5432"
            )
        if args.database != "postgres" or args.user != f"postgres.{args.project_ref}":
            raise ValueError("Shared database/user mismatch")
        if args.apply and not args.execute_shared:
            raise ValueError("Shared write requires --execute-shared")
        if not args.ssl_ca_file:
            raise ValueError("Shared DB requires --ssl-ca-file")
        ca = Path(args.ssl_ca_file).resolve()
        if not ca.is_file():
            raise ValueError(f"SSL CA file is missing: {ca}")
        ssl_context = ssl.create_default_context(cafile=str(ca))
        password = getpass.getpass("Shared PostgreSQL password: ")
    else:
        if args.execute_shared or args.ssl_ca_file:
            raise ValueError("Shared flags are not valid for a local database")
        if args.host not in {"127.0.0.1", "localhost"}:
            raise ValueError("Local target must use a loopback host")
        ssl_context = False
        password = os.getenv("POSTGRES_PASSWORD") or getpass.getpass(
            "Local PostgreSQL password: "
        )
    return {
        "host": args.host,
        "port": args.port,
        "database": args.database,
        "user": args.user,
        "password": password,
        "ssl": ssl_context,
        "server_settings": {"application_name": "oliveyoung_collect_load"},
    }


async def _stage(conn: asyncpg.Connection, files: dict) -> None:
    for table, (path, columns, count) in files.items():
        real = f"raw_oy_{table}"
        available = {
            r["column_name"]
            for r in await conn.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=$1",
                real,
            )
        }
        if not available or not set(columns) <= available:
            raise ValueError(
                f"CSV columns differ from public.{real}: {sorted(set(columns) - available)}"
            )
        await conn.execute(
            f"CREATE TEMP TABLE stg_{table} (LIKE public.{real} INCLUDING DEFAULTS) ON COMMIT DROP"
        )
        result = await conn.copy_to_table(
            f"stg_{table}",
            source=path,
            columns=columns,
            format="csv",
            header=True,
            encoding="UTF8",
            force_not_null=["raw_text", "source_url"] if table == "option_ingredient_observation" else None,
        )
        if int(result.rsplit(" ", 1)[-1]) != count:
            raise ValueError(f"CSV row count changed during stage copy: {table}")
        text_columns = [
            r["column_name"]
            for r in await conn.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='pg_temp' AND table_name=$1 AND data_type='text'",
                f"stg_{table}",
            )
        ]
        # PostgreSQL exposes temp schemas as pg_temp_N, not pg_temp.
        if not text_columns:
            text_columns = [
                r["attname"]
                for r in await conn.fetch(
                    "SELECT a.attname FROM pg_attribute a WHERE a.attrelid=$1::regclass "
                    "AND a.attnum>0 AND NOT a.attisdropped AND a.atttypid='text'::regtype",
                    f"stg_{table}",
                )
            ]
        for column in text_columns:
            if table == "option_ingredient_observation" or (
                table == "product_notice" and column == "ingredients_raw"
            ):
                continue  # Source offsets/hashes refer to unmodified disclosure text.
            await conn.execute(
                f"UPDATE stg_{table} SET {column}=replace({column}, '■', '') "
                f"WHERE {column} LIKE '%■%'"
            )


async def _validate_stage(conn: asyncpg.Connection, files: dict) -> None:
    checks = {
        "duplicate products": "SELECT COUNT(*)-COUNT(DISTINCT goods_no) FROM stg_product",
        "duplicate options": "SELECT COUNT(*)-COUNT(DISTINCT option_id) FROM stg_product_option",
        "options without product": (
            "SELECT COUNT(*) FROM stg_product_option o LEFT JOIN stg_product p "
            "ON p.goods_no=o.goods_no WHERE p.goods_no IS NULL"
        ),
        "ingredient links without name": (
            "SELECT COUNT(*) FROM stg_option_ingredient oi LEFT JOIN stg_ingredient i "
            "ON i.ingredient_id=oi.ingredient_id WHERE i.ingredient_id IS NULL"
        ),
        "ingredient links without option": (
            "SELECT COUNT(*) FROM stg_option_ingredient oi LEFT JOIN stg_product_option o "
            "ON o.option_id=oi.option_id WHERE o.option_id IS NULL"
        ),
        "prices without option": (
            "SELECT COUNT(*) FROM stg_price_snapshot p LEFT JOIN stg_product_option o "
            "ON o.option_id=p.option_id WHERE o.option_id IS NULL"
        ),
    }
    if "option_color" in files:
        checks["colors without option"] = (
            "SELECT COUNT(*) FROM stg_option_color c LEFT JOIN stg_product_option o "
            "ON o.option_id=c.option_id WHERE o.option_id IS NULL"
        )
        checks["colors without image"] = (
            "SELECT COUNT(*) FROM stg_option_color c LEFT JOIN stg_image i "
            "ON i.image_id=c.color_image_id "
            "WHERE c.color_image_id IS NOT NULL AND i.image_id IS NULL"
        )
    for label, query in checks.items():
        count = await conn.fetchval(query)
        if count:
            raise ValueError(f"Snapshot has {count} {label}")


async def _lookup(
    conn: asyncpg.Connection, table: str, columns: list[str], key: str
) -> None:
    cols = ", ".join(columns)
    await conn.execute(
        f"INSERT INTO public.raw_oy_{table} ({cols}) "
        f"SELECT DISTINCT ON ({key}) {cols} FROM stg_{table} "
        f"WHERE {key} IS NOT NULL ORDER BY {key} "
        f"ON CONFLICT ({key}) DO NOTHING"
    )


async def _merge_simple(
    conn: asyncpg.Connection,
    table: str,
    columns: list[str],
    key: str,
    source: str = "stg_writable",
) -> None:
    cols = ", ".join(f"s.{col}" for col in columns)
    changes = ", ".join(
        (
            f"{col}=GREATEST(EXCLUDED.{col},t.{col})"
            if table == "product" and col == "last_collected_at"
            else f"{col}=COALESCE(EXCLUDED.{col}, t.{col})"
        )
        for col in columns
        if col != key
    )
    sql = (
        f"INSERT INTO public.raw_oy_{table} AS t ({', '.join(columns)}) "
        f"SELECT {cols} FROM stg_{table} s JOIN {source} w ON w.goods_no=s.goods_no "
        f"ON CONFLICT ({key}) DO UPDATE SET {changes}"
    )
    await conn.execute(sql)


async def _apply(
    conn: asyncpg.Connection,
    files: dict,
    kind: str,
    run_id: int,
    mode: str,
    unavailable: dict,
) -> dict:
    await conn.execute("SELECT pg_advisory_xact_lock(20261031, 301)")
    await conn.execute(
        "INSERT INTO public.raw_oy_crawl_run "
        "(run_id, script_version, started_at, finished_at, status) "
        "SELECT run_id, script_version, started_at, finished_at, status FROM stg_crawl_run "
        "WHERE run_id=$1 ON CONFLICT(run_id) DO UPDATE SET "
        "finished_at=EXCLUDED.finished_at,status=EXCLUDED.status",
        run_id,
    )
    for table in ("brand", "supplier", "category", "survey_question", "survey_answer"):
        await _lookup(conn, table, files[table][1], LOOKUPS[table])
    if kind == "makeup":
        await _lookup(conn, "image_applied", files["image_applied"][1], "image_url")
    # Existing makeup rows win when skincare categories overlap them.
    where = (
        ""
        if kind == "makeup"
        else (
            "WHERE NOT EXISTS (SELECT 1 FROM public.raw_oy_product_texture m "
            "WHERE m.goods_no=s.goods_no)"
        )
    )
    await conn.execute(
        f"CREATE TEMP TABLE stg_writable ON COMMIT DROP AS "
        f"SELECT s.goods_no FROM stg_product s {where}"
    )
    await _merge_simple(
        conn,
        "product",
        [
            c
            for c in files["product"][1]
            if c not in {"first_collected_at", "delisted_at"}
        ],
        "goods_no",
    )
    # The insert above leaves first_collected_at NULL on newly inserted rows; repair it from stage.
    await conn.execute(
        "UPDATE public.raw_oy_product p SET first_collected_at=s.first_collected_at, "
        "delisted_at=NULL FROM stg_product s JOIN stg_writable w ON w.goods_no=s.goods_no "
        "WHERE p.goods_no=s.goods_no AND "
        "(p.first_collected_at IS NULL OR p.delisted_at IS NOT NULL)"
    )
    if kind == "skincare":
        columns = files["skincare_attr"][1]
        await conn.execute(
            f"INSERT INTO public.raw_oy_skincare_attr AS t ({', '.join(columns)}) "
            f"SELECT {', '.join('s.' + c for c in columns)} FROM stg_skincare_attr s WHERE true "
            f"ON CONFLICT(goods_no) DO UPDATE SET "
            + ", ".join(
                f"{c}=COALESCE(EXCLUDED.{c},t.{c})" for c in columns if c != "goods_no"
            )
        )
    await _merge_simple(conn, "product_notice", files["product_notice"][1], "goods_no")
    columns = files["product_option"][1]
    changes = ", ".join(
        f"{c}=COALESCE(EXCLUDED.{c},t.{c})"
        for c in columns
        if c not in {"option_id", "delisted_at"}
    )
    await conn.execute(
        f"INSERT INTO public.raw_oy_product_option AS t ({', '.join(columns)}) "
        f"SELECT {', '.join('s.' + c for c in columns)} FROM stg_product_option s "
        f"JOIN stg_writable w ON w.goods_no=s.goods_no "
        f"ON CONFLICT(option_id) DO UPDATE SET {changes},delisted_at=NULL"
    )
    if mode == "full":
        await conn.execute(
            "UPDATE public.raw_oy_product_option o SET delisted_at=now() "
            "FROM stg_writable w WHERE o.goods_no=w.goods_no AND o.delisted_at IS NULL "
            "AND NOT EXISTS (SELECT 1 FROM stg_product_option s WHERE s.option_id=o.option_id)"
        )
    # Stage IDs are local. Insert only referenced new names, then resolve by stable name key.
    await conn.execute(
        "INSERT INTO public.raw_oy_ingredient (ingredient_name,ingredient_norm) "
        "SELECT DISTINCT ON (i.ingredient_norm) i.ingredient_name,i.ingredient_norm "
        "FROM stg_ingredient i JOIN stg_option_ingredient oi ON oi.ingredient_id=i.ingredient_id "
        "JOIN stg_product_option o ON o.option_id=oi.option_id "
        "JOIN stg_writable w ON w.goods_no=o.goods_no "
        "WHERE i.ingredient_norm IS NOT NULL AND i.ingredient_norm<>'' "
        "ORDER BY i.ingredient_norm ON CONFLICT(ingredient_norm) DO NOTHING"
    )
    await conn.execute(
        "INSERT INTO public.raw_oy_image "
        "(goods_no,option_id,image_type,image_url,sort_seq,collected_at) "
        "SELECT DISTINCT ON (s.goods_no,s.image_type,s.image_url) "
        "s.goods_no,s.option_id,s.image_type,s.image_url,s.sort_seq,s.collected_at "
        "FROM stg_image s JOIN stg_writable w ON w.goods_no=s.goods_no "
        "WHERE NOT EXISTS (SELECT 1 FROM public.raw_oy_image i WHERE i.goods_no=s.goods_no "
        "AND i.image_type IS NOT DISTINCT FROM s.image_type AND i.image_url=s.image_url) "
        "ORDER BY s.goods_no,s.image_type,s.image_url"
    )
    if kind == "makeup":
        cols = files["product_texture"][1]
        await conn.execute(
            f"INSERT INTO public.raw_oy_product_texture ({', '.join(cols)}) "
            f"SELECT {', '.join('s.' + c for c in cols)} FROM stg_product_texture s "
            "JOIN stg_writable w ON w.goods_no=s.goods_no "
            "ON CONFLICT(goods_no,collected_at) DO NOTHING"
        )
        cols = [c for c in files["option_color"][1] if c != "color_image_id"]
        await conn.execute(
            f"INSERT INTO public.raw_oy_option_color "
            f"({', '.join(cols)},color_image_id) "
            f"SELECT {', '.join('s.' + c for c in cols)}, i.image_id "
            "FROM stg_option_color s JOIN stg_product_option o ON o.option_id=s.option_id "
            "JOIN stg_writable w ON w.goods_no=o.goods_no "
            "LEFT JOIN stg_image si ON si.image_id=s.color_image_id "
            "LEFT JOIN LATERAL (SELECT image_id FROM public.raw_oy_image i "
            "WHERE i.goods_no=si.goods_no AND i.image_type=si.image_type "
            "AND i.image_url=si.image_url ORDER BY image_id LIMIT 1) i ON true "
            "ON CONFLICT(option_id,collected_at) DO NOTHING"
        )
    # Recompute latest flags after every merge, including replay of an older snapshot.
    await conn.execute(
        "UPDATE public.raw_oy_price_snapshot p SET is_latest=false "
        "WHERE p.option_id IN (SELECT s.option_id FROM stg_price_snapshot s "
        "JOIN stg_product_option o ON o.option_id=s.option_id "
        "JOIN stg_writable w ON w.goods_no=o.goods_no) AND p.is_latest"
    )
    cols = [
        c for c in files["price_snapshot"][1] if c not in {"snapshot_id", "is_latest"}
    ]
    await conn.execute(
        f"INSERT INTO public.raw_oy_price_snapshot ({', '.join(cols)},is_latest) "
        f"SELECT {', '.join('s.' + c for c in cols)},false FROM stg_price_snapshot s "
        "JOIN stg_product_option o ON o.option_id=s.option_id "
        "JOIN stg_writable w ON w.goods_no=o.goods_no "
        "ON CONFLICT(option_id,collected_at) DO NOTHING"
    )
    await conn.execute(
        "UPDATE public.raw_oy_price_snapshot p SET is_latest=true WHERE p.snapshot_id IN ("
        "SELECT DISTINCT ON (option_id) snapshot_id FROM public.raw_oy_price_snapshot "
        "WHERE option_id IN (SELECT s.option_id FROM stg_price_snapshot s "
        "JOIN stg_product_option o ON o.option_id=s.option_id "
        "JOIN stg_writable w ON w.goods_no=o.goods_no) "
        "ORDER BY option_id,collected_at DESC,snapshot_id DESC)"
    )
    await conn.execute(
        "UPDATE public.raw_oy_review_summary r SET is_latest=false "
        "WHERE r.goods_no IN (SELECT goods_no FROM stg_writable) AND r.is_latest"
    )
    cols = [
        c for c in files["review_summary"][1] if c not in {"summary_id", "is_latest"}
    ]
    await conn.execute(
        f"INSERT INTO public.raw_oy_review_summary ({', '.join(cols)},is_latest) "
        f"SELECT {', '.join('s.' + c for c in cols)},false FROM stg_review_summary s "
        "JOIN stg_writable w ON w.goods_no=s.goods_no "
        "ON CONFLICT(goods_no,collected_at) DO NOTHING"
    )
    await conn.execute(
        "UPDATE public.raw_oy_review_summary r SET is_latest=true WHERE r.summary_id IN ("
        "SELECT DISTINCT ON (goods_no) summary_id FROM public.raw_oy_review_summary "
        "WHERE goods_no IN (SELECT goods_no FROM stg_writable) "
        "ORDER BY goods_no,collected_at DESC,summary_id DESC)"
    )
    for table, key in (
        ("review_ai_feature", "goods_no,seq,collected_at"),
        ("review_survey", "goods_no,answer_code,collected_at"),
    ):
        cols = files[table][1]
        await conn.execute(
            f"INSERT INTO public.raw_oy_{table} ({', '.join(cols)}) "
            f"SELECT {', '.join('s.' + c for c in cols)} FROM stg_{table} s "
            "JOIN stg_writable w ON w.goods_no=s.goods_no "
            f"ON CONFLICT({key}) DO NOTHING"
        )
    # Existing option links may have been manually reviewed. Preserve them by default.
    linked = await conn.fetchval(
        "SELECT COUNT(DISTINCT oi.option_id) FROM stg_option_ingredient oi "
        "JOIN public.raw_oy_option_ingredient e ON e.option_id=oi.option_id"
    )
    await conn.execute(
        "INSERT INTO public.raw_oy_option_ingredient (option_id,ingredient_id,seq) "
        "SELECT oi.option_id,i.ingredient_id,MIN(oi.seq) FROM stg_option_ingredient oi "
        "JOIN stg_ingredient si ON si.ingredient_id=oi.ingredient_id "
        "JOIN public.raw_oy_ingredient i ON i.ingredient_norm=si.ingredient_norm "
        "JOIN stg_product_option o ON o.option_id=oi.option_id "
        "JOIN stg_writable w ON w.goods_no=o.goods_no "
        "WHERE NOT EXISTS (SELECT 1 FROM public.raw_oy_option_ingredient e "
        "WHERE e.option_id=oi.option_id) GROUP BY oi.option_id,i.ingredient_id "
        "ON CONFLICT(option_id,ingredient_id) DO NOTHING"
    )
    await _apply_observations(conn, files)
    await conn.execute("DELETE FROM public.raw_oy_crawl_log WHERE run_id=$1", run_id)
    cols = [c for c in files["crawl_log"][1] if c != "log_id"]
    await conn.execute(
        f"INSERT INTO public.raw_oy_crawl_log ({', '.join(cols)}) "
        f"SELECT {', '.join('s.' + c for c in cols)} FROM stg_crawl_log s "
        "WHERE s.run_id=$1",
        run_id,
    )
    if unavailable:
        await conn.executemany(
            "INSERT INTO public.raw_oy_crawl_log "
            "(run_id,goods_no,step,status,error_message,logged_at) "
            "VALUES ($1,$2,'detail_unavailable','confirmed',$3,now())",
            [
                (run_id, goods_no, f"{record['method']}: {record['reason']}")
                for goods_no, record in unavailable.items()
            ],
        )
    # Every seen goods number is logged so a later complete run can identify removals.
    await conn.execute(
        "INSERT INTO public.raw_oy_crawl_log (run_id,goods_no,step,status,logged_at) "
        "SELECT $1,goods_no,'scope_seen','success',now() FROM stg_product",
        run_id,
    )
    previous = await conn.fetchval(
        "SELECT r.run_id FROM public.raw_oy_crawl_run r "
        "WHERE r.script_version LIKE $1 AND r.status='done' AND r.run_id<>$2 "
        "AND EXISTS (SELECT 1 FROM public.raw_oy_crawl_log l "
        "WHERE l.run_id=r.run_id AND l.step='scope_seen') "
        "ORDER BY r.run_id DESC LIMIT 1",
        "makeup-v%-db" if kind == "makeup" else "skincare-v%-db",
        run_id,
    )
    delisted = 0
    if previous is not None and mode == "full":
        other_scope = (
            "NOT EXISTS (SELECT 1 FROM public.raw_oy_skincare_attr a WHERE a.goods_no=p.goods_no)"
            if kind == "makeup"
            else "NOT EXISTS (SELECT 1 FROM public.raw_oy_product_texture t WHERE t.goods_no=p.goods_no)"
        )
        status = await conn.execute(
            "UPDATE public.raw_oy_product p SET delisted_at=now() "
            "WHERE p.delisted_at IS NULL AND EXISTS "
            "(SELECT 1 FROM public.raw_oy_crawl_log l WHERE l.run_id=$1 "
            "AND l.step='scope_seen' AND l.goods_no=p.goods_no) "
            f"AND {other_scope} AND NOT EXISTS "
            "(SELECT 1 FROM stg_product s WHERE s.goods_no=p.goods_no)",
            previous,
        )
        delisted = int(status.rsplit(" ", 1)[-1])
    return {
        "existing_ingredient_link_options_preserved": linked,
        "newly_delisted_products": delisted,
    }


async def load(args: argparse.Namespace) -> None:
    directory = Path(args.snapshot_dir).resolve()
    files = _files(directory, args.kind)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if not args.apply and args.execute_shared:
        raise ValueError("--execute-shared requires --apply")
    conn = await asyncpg.connect(**_connection_args(args))
    try:
        version = await conn.fetchval("SELECT version_num FROM public.alembic_version")
        if version < "0010":
            raise ValueError(f"DB migration is too old: {version}")
        # Preflight uses a read-only transaction, without creating temp tables.
        for table in files:
            if (
                await conn.fetchval("SELECT to_regclass($1)", f"public.raw_oy_{table}")
                is None
            ):
                raise ValueError(f"Missing table: raw_oy_{table}")
        product_count = await conn.fetchval(
            "SELECT COUNT(*) FROM public.raw_oy_product"
        )
        print(
            f"Connected to {args.host}:{args.port}/{args.database}; "
            f"existing products={product_count}; snapshot products={files['product'][2]}"
        )
        if not args.apply:
            async with conn.transaction():
                await _stage(conn, files)
                await _validate_stage(conn, files)
            print(
                "Preflight passed; staged CSV types and references; no database rows were written"
            )
            return
        async with conn.transaction():
            await _stage(conn, files)
            await _validate_stage(conn, files)
            result = await _apply(
                conn,
                files,
                args.kind,
                manifest["run_id"],
                manifest["mode"],
                unavailable_records(manifest),
            )
        print(f"Committed snapshot {manifest['run_id']}: {json.dumps(result)}")
    finally:
        await conn.close()


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--snapshot-dir", required=True)
    parser.add_argument("--target", choices=("local", "shared"), default="local")
    parser.add_argument("--project-ref")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=15432)
    parser.add_argument("--database", default="vishue_db")
    parser.add_argument("--user", default="vishue")
    parser.add_argument("--ssl-ca-file")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--execute-shared", action="store_true")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=("makeup", "skincare"), required=True)
    add_arguments(parser)
    asyncio.run(load(parser.parse_args()))


if __name__ == "__main__":
    main()
