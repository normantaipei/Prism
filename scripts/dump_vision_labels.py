#!/usr/bin/env python3
"""列出這台 Mac 的 Vision framework 支援的所有分類標籤，並標出 tag_map.json 還缺哪些。
用法: source .venv/bin/activate && python scripts/dump_vision_labels.py > vision_labels.txt
"""
import json, sys
from pathlib import Path
import Vision

req = Vision.VNClassifyImageRequest.alloc().init()
labels, err = req.supportedIdentifiersAndReturnError_(None)
if err:
    sys.exit(f"取不到標籤清單: {err}")
labels = sorted(labels)

tm_path = Path(__file__).resolve().parent.parent / "tag_map.json"
tm = {k.lower() for k in json.loads(tm_path.read_text(encoding="utf-8")) if not k.startswith("_")} if tm_path.exists() else set()

missing = [l for l in labels if l.lower() not in tm]
print(f"# Vision 共 {len(labels)} 個標籤，tag_map.json 已有 {len(labels)-len(missing)}，缺 {len(missing)}", file=sys.stderr)
for l in labels:
    print(("  " if l.lower() in tm else "? ") + l)
