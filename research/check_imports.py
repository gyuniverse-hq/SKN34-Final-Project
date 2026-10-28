"""Fail if app/client code imports research-only models or YouCam."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NEEDLES = (
    "from research",
    "youcam_vto",
    "compare_liner",
    "eval_liner",
    "eval_bisenet",
    "bisenet_resnet",
    "face-parsing",
)
DIRS = ("app", "components", "lib", "server", "store")


def main():
    hits = []
    for d in DIRS:
        root = ROOT / d
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if p.suffix not in {".ts", ".tsx", ".js", ".jsx"}:
                continue
            text = p.read_text(encoding="utf-8", errors="replace").lower()
            for n in NEEDLES:
                if n in text:
                    hits.append(f"{p.relative_to(ROOT)}: {n}")
    if hits:
        raise SystemExit("research-only names in app code:\n" + "\n".join(hits))
    print("check_imports ok")


if __name__ == "__main__":
    main()
