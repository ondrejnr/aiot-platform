#!/usr/bin/env python3
from pathlib import Path
import sys, yaml

DROP_META = {
    "creationTimestamp",
    "resourceVersion",
    "uid",
    "selfLink",
    "generation",
    "managedFields",
}
DROP_TOP = {"status"}

def clean(obj):
    if isinstance(obj, dict):
        obj = {k: clean(v) for k, v in obj.items() if k not in DROP_TOP}
        if "metadata" in obj and isinstance(obj["metadata"], dict):
            obj["metadata"] = {k: clean(v) for k, v in obj["metadata"].items() if k not in DROP_META}
            anns = obj["metadata"].get("annotations")
            if isinstance(anns, dict):
                anns.pop("kubectl.kubernetes.io/last-applied-configuration", None)
                if not anns:
                    obj["metadata"].pop("annotations", None)
        return obj
    if isinstance(obj, list):
        return [clean(x) for x in obj]
    return obj

root = Path(sys.argv[1])
for f in root.rglob("*.yaml"):
    data = yaml.safe_load(f.read_text())
    data = clean(data)
    f.write_text(yaml.safe_dump(data, sort_keys=False))
print(f"Normalized YAML under {root}")
