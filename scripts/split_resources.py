#!/usr/bin/env python3
from pathlib import Path
import sys, yaml, shutil

src = Path(sys.argv[1])
out = Path(sys.argv[2])
if out.exists():
    shutil.rmtree(out)
out.mkdir(parents=True, exist_ok=True)

text = src.read_text()
docs = list(yaml.safe_load_all(text))
count = 0

for doc in docs:
    if not doc:
        continue
    if isinstance(doc, dict) and doc.get("kind") == "List" and "items" in doc:
        items = doc.get("items") or []
    else:
        items = [doc]

    for item in items:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind", "Unknown")
        meta = item.get("metadata", {}) or {}
        name = meta.get("name", "noname")
        namespace = meta.get("namespace", "_cluster")
        path = out / namespace / kind
        path.mkdir(parents=True, exist_ok=True)
        with open(path / f"{name}.yaml", "w") as f:
            yaml.safe_dump(item, f, sort_keys=False)
        count += 1

print(f"Split {count} resources into {out}")
