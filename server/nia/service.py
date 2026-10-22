"""Loopback-only HTTP service. Start with python -m server.nia.service."""

import base64
import csv
import hmac
import io
import json
import os
import threading
import time
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from server.acne.engine import AcneEngine
from urllib.parse import parse_qs, urlparse

from .catalog import SOURCE_URL, TASKS
from .dataset import prepare_dataset
from .engine import Engine, sha256
from .metrics import classification, regression, timing
from .profile import FEATURES, run_profile

MAX_BODY = 18 * 1024 * 1024


class Service:
    def __init__(self, config_path):
        self.config_path = Path(config_path).resolve()
        self.config = json.loads(self.config_path.read_text(encoding="utf-8")) if self.config_path.is_file() else {}
        self.engines = {}
        self.errors = {}
        for model in self.config.get("models", []):
            identifier = model.get("id", "invalid")
            if identifier in self.engines or identifier in self.errors:
                raise ValueError("Duplicate model ID")
            try:
                self.engines[identifier] = Engine(model)
            except (ValueError, KeyError) as error:
                self.errors[identifier] = str(error)
        self.jobs = {}
        self.lock = threading.Lock()
        self.jobs_lock = threading.Lock()
        self.worker = ThreadPoolExecutor(max_workers=1)
        # Optional separately trained model; never reinterpret it as an original NIA task.
        self.acne = AcneEngine(self.config["acne"]) if self.config.get("acne") else None

    def status(self):
        return dict(source=SOURCE_URL, config_exists=self.config_path.is_file(),
                    models=[dict(id=key, task=e.config["task"], areas=e.config["areas"],
                                 present=Path(e.config["checkpoint"]).is_file(),
                                 loaded=e.model is not None, metadata=e.metadata)
                            for key, e in self.engines.items()], errors=self.errors,
                            acne=dict(configured=self.acne is not None,
                                      present=bool(self.acne and isinstance(self.acne.config, dict)
                                                   and isinstance(self.acne.config.get("checkpoint"), str)
                                                   and Path(self.acne.config["checkpoint"]).is_file()),
                                      loaded=bool(self.acne and self.acne.model is not None)),
                            dataset_configured=bool(self.config.get("dataset_roots")),
                    previews_allowed=bool(self.config.get("allow_dataset_previews", False)))

    def engine(self, identifier):
        if identifier not in self.engines:
            raise ValueError("Checkpoint not configured or validation failed")
        return self.engines[identifier]

    def infer(self, body):
        start = time.perf_counter()
        if body.get("roi_confirmed") is not True:
            raise ValueError("Explicit manual ROI confirmation required")
        raw = base64.b64decode(body["image"], validate=True)
        selections = body.get("selections")
        if not isinstance(selections, list) or not 1 <= len(selections) <= 10:
            raise ValueError("Select between 1 and 10 verified models/areas")
        with self.lock:
            results = [self.engine(s["model_id"]).predict(raw, s["area"], s["bbox"],
                                                        repeats=body.get("repeats", 1)) for s in selections]
        return dict(results=results, sequence_server_ms=(time.perf_counter() - start) * 1000,
                    roi_source="manual_unverified_against_training_annotations")

    def evaluate(self, request):
        with self.jobs_lock:
            return self.submit_evaluation(request)

    def profile(self, request):
        raw = base64.b64decode(request["image"], validate=True)
        with self.jobs_lock:
            if any(job["status"] in ("queued", "running") for job in self.jobs.values()):
                raise ValueError("An evaluation is already running")
            if len(self.jobs) >= 4:
                del self.jobs[next(iter(self.jobs))]
            identifier = uuid.uuid4().hex
            total = sum(len(parts) for _, areas in FEATURES.values() for parts in areas.values()) + int(self.acne is not None)
            job = dict(id=identifier, kind="profile", status="queued", completed=0, total=total, report=None)
            self.jobs[identifier] = job
            self.worker.submit(self.run_profile_job, job, raw)
            return dict(id=identifier)

    def run_profile_job(self, job, raw):
        job["status"] = "running"
        try:
            with self.lock:
                job["report"] = run_profile(raw, self.engines, job, self.acne)
                job["status"] = "completed"
        except Exception as error:
            job.update(status="failed", error=str(error))

    def submit_evaluation(self, request):
        engine = self.engine(request["model_id"])
        if engine.config.get("training_device") == "smartphone":
            raise ValueError(
                "Retrained smartphone models use a new person split. Use the held-out results in "
                "reports/skin-analysis/smartphone-training.md; original-split evaluation is blocked."
            )
        active = [job for job in self.jobs.values() if job["status"] in ("queued", "running")]
        if active:
            raise ValueError("An evaluation is already running")
        if len(self.jobs) >= 4:
            del self.jobs[next(iter(self.jobs))]
        identifier = uuid.uuid4().hex
        job = dict(id=identifier, status="queued", completed=0, total=None, report=None)
        self.jobs[identifier] = job
        self.worker.submit(self.run_job, job, engine, request)
        return dict(id=identifier)

    def run_job(self, job, engine, request):
        start = time.perf_counter()
        job["status"] = "running"
        try:
            with self.lock:
                records, dataset = prepare_dataset(request, engine.config,
                                                    self.config.get("dataset_roots", []),
                                                    self.config.get("metadata_evidence"))
                job["total"] = len(records)
                engine.load()
                rows = []
                for record in records:
                    result = engine.predict(record["path"].read_bytes(), record["area"], record["bbox"],
                                            record["precropped"], preview=False)
                    prediction = result["prediction"].get("grade", result["prediction"].get("value"))
                    rows.append(dict(id=record["id"], area=record["area"], device=record["device"],
                                     truth=record["truth"], prediction=prediction,
                                     error=abs(record["truth"] - prediction),
                                     inference_ms=result["inference"]["mean_ms"],
                                     preprocessing_ms=result["preprocessing_ms"], server_ms=result["server_ms"],
                                     gpu_peak_process_bytes=result["gpu_peak_process_bytes"],
                                     image_sha256=sha256(record["path"]),
                                     **{k: record[k] for k in ("age_group", "skin_tone", "population") if k in record}))
                    job["completed"] = len(rows)
                def metrics(subset):
                    truth, prediction = [r["truth"] for r in subset], [r["prediction"] for r in subset]
                    return classification(truth, prediction, TASKS[engine.config["task"]][1]) if result["mode"] == "class" else regression(truth, prediction)
                groups = {}
                keys = ["area", "device", "age_group", "skin_tone", "population"]
                if result["mode"] == "class":
                    keys.append("truth")
                for key in keys:
                    grouped = defaultdict(list)
                    for row in rows:
                        if key in row:
                            grouped[str(row[key])].append(row)
                    if grouped:
                        groups[key] = {value: metrics(subset) for value, subset in sorted(grouped.items())}
                report = dict(model=engine.metadata, settings=request, dataset=dataset, mode=result["mode"],
                              unit=engine.config.get("unit"), metrics=metrics(rows), groups=groups,
                              timing=timing([r["inference_ms"] for r in rows]),
                              preprocessing=timing([r["preprocessing_ms"] for r in rows]),
                              sample_server=timing([r["server_ms"] for r in rows]),
                              gpu_peak_process_bytes=max((r["gpu_peak_process_bytes"] or 0 for r in rows)) or None,
                              samples=rows, server_ms=(time.perf_counter() - start) * 1000,
                              macro_f1_policy="all_checkpoint_grades_zero_division_0",
                              claim="NIA evaluation only; global generalization has not been established")
                # Paths stay in server memory for explicitly permitted local previews, never in CSV rows.
                job["records"] = records
                job["report"] = report
                job["status"] = "completed"
        except Exception as error:
            job["error"] = str(error)
            job["status"] = "failed"

    def dispatch(self, action, body, query):
        if action == "status":
            return self.status()
        if action == "load":
            with self.lock:
                return self.engine(body["model_id"]).load()
        if action == "infer":
            return self.infer(body)
        if action == "profile":
            return self.profile(body)
        if action == "evaluate":
            return self.evaluate(body)
        if action in ("job", "export", "sample"):
            job = self.jobs.get(query.get("id", [""])[0])
            if job is None:
                raise ValueError("Evaluation job not found; reports are held only until restart/eviction")
            if action == "job":
                return {k: v for k, v in job.items() if k != "records"}
            if job["status"] != "completed":
                raise ValueError("Evaluation has not completed")
            if job.get("kind") == "profile":
                raise ValueError("Use the photo profile ML JSON export in the client")
            if action == "sample":
                if not self.config.get("allow_dataset_previews", False):
                    raise PermissionError("Dataset previews are disabled by the server")
                index = int(query.get("index", ["-1"])[0])
                if not 0 <= index < len(job["records"]):
                    raise ValueError("Invalid sample index")
                record = job["records"][index]
                from .imaging import prepare
                _, preview = prepare(record["path"].read_bytes(), record["bbox"],
                                     self.engine(job["report"]["model"]["id"]).config["areas"][record["area"]][0],
                                     record["precropped"])
                return preview
            report = job["report"]
            if query.get("format", ["json"])[0] == "csv":
                output = io.StringIO(newline="")
                fields = sorted({k for row in report["samples"] for k in row})
                writer = csv.DictWriter(output, fieldnames=["checkpoint_sha256", "task", "device_runtime", "settings_json", *fields])
                writer.writeheader()
                for row in report["samples"]:
                    export = dict(checkpoint_sha256=report["model"]["sha256"], task=report["model"]["task"],
                                  device_runtime=report["model"]["device"], settings_json=json.dumps(report["settings"]), **row)
                    # Keep spreadsheet applications from evaluating untrusted metadata as formulae.
                    writer.writerow({k: "'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@", "\t", "\r")) else v for k, v in export.items()})
                return output.getvalue()
            return report
        raise ValueError("Unknown evaluation action")


def main():
    token = os.environ.get("NIA_EVAL_TOKEN", "")
    if len(token) < 32:
        raise SystemExit("Set NIA_EVAL_TOKEN to a random secret with at least 32 characters")
    service = Service(os.environ.get("NIA_EVAL_CONFIG", "server/nia/config.local.json"))

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Do not write sample IDs, paths or authentication headers to HTTP logs.

        def respond(self):
            try:
                if not hmac.compare_digest(self.headers.get("X-NIA-Token", ""), token):
                    raise PermissionError("Unauthorized")
                length = int(self.headers.get("Content-Length", "0"))
                if length < 0 or length > MAX_BODY:
                    raise ValueError("Request exceeds upload limit")
                if self.headers.get("Transfer-Encoding"):
                    raise ValueError("Chunked request bodies are unsupported")
                body = json.loads(self.rfile.read(length)) if length else {}
                url = urlparse(self.path)
                result = service.dispatch(url.path.strip("/"), body, parse_qs(url.query))
                is_csv = isinstance(result, str)
                raw = result.encode() if is_csv else json.dumps(result, allow_nan=False).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8" if is_csv else "application/json")
            except Exception as error:
                raw = json.dumps(dict(error=str(error))).encode()
                self.send_response(403 if isinstance(error, PermissionError) else 400)
                self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        do_GET = respond
        do_POST = respond

    port = int(os.environ.get("NIA_EVAL_PORT", "8765"))
    print(f"NIA evaluation service: http://127.0.0.1:{port} (no weights/data loaded)")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
