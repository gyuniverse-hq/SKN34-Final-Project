"""Local files used by the explicitly invoked review jobs."""

import csv
import json
import os
import tempfile
from pathlib import Path

from app.schemas.catalog import CatalogBundle

ROOT = Path(__file__).resolve().parents[4]
API = ROOT / "backend" / "api"
SOURCES = {
    "celebrity": (
        API / "app/catalog_data/celebrity_videos.json",
        ROOT / "lib/devCatalog/celebrityVideos.json",
    ),
    "style": (API / "app/catalog_data/style_looks.json", ROOT / "lib/devCatalog/styleLooks.json"),
}
FIELDS = [
    "source",
    "videoId",
    "number",
    "brand",
    "name",
    "option",
    "zone",
    "matchStatus",
    "score",
    "reason",
    "candidateProductId",
    "candidateProductName",
    "candidateShadeId",
    "candidateShadeName",
    "alt2ProductId",
    "alt3ProductId",
    "ruleVersion",
    "decision",
    "reviewer",
    "decidedAt",
]


class VideoMappingFiles:
    def __init__(self, sources: dict | None = None):
        self.sources = sources or SOURCES

    def load_sources(self) -> dict[str, list[dict]]:
        data = {}
        for source, (server, client) in self.sources.items():
            data[source] = json.loads(server.read_text(encoding="utf-8"))
            if data[source] != json.loads(client.read_text(encoding="utf-8")):
                raise ValueError(f"{source}: server and client copies differ")
        return data

    @staticmethod
    def catalog(path: Path) -> CatalogBundle:
        return CatalogBundle.model_validate_json(path.read_text(encoding="utf-8"))

    @staticmethod
    def read_csv(path: Path) -> list[dict]:
        if not path.exists():
            return []
        with path.open(encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))

    @staticmethod
    def write_csv(path: Path, rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)

    def write_sources(self, data: dict[str, list[dict]]) -> None:
        originals, temp_files, replaced = {}, {}, []
        try:
            for source, paths in self.sources.items():
                payload = (json.dumps(data[source], ensure_ascii=False, indent=2) + "\n").encode(
                    "utf-8"
                )
                for path in paths:
                    originals[path] = path.read_bytes()
                    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
                        temp_files[path] = Path(f.name)
                        f.write(payload)
            for path, temp in temp_files.items():
                os.replace(temp, path)
                replaced.append(path)
        except OSError:
            for path in replaced:
                path.write_bytes(originals[path])
            raise
        finally:
            for temp in temp_files.values():
                temp.unlink(missing_ok=True)
