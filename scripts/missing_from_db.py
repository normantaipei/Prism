#!/usr/bin/env python3
"""從 state.db 統計實際出現過、但 tag_map.json 沒中文的標籤（依出現次數排序）。
用法: python scripts/missing_from_db.py
"""
import json, sqlite3
from collections import Counter
from pathlib import Path

root = Path(__file__).resolve().parent.parent
tm = {k.lower() for k in json.loads((root / "tag_map.json").read_text(encoding="utf-8")) if not k.startswith("_")}
zh_values = set()
for v in json.loads((root / "tag_map.json").read_text(encoding="utf-8")).values():
    if isinstance(v, str): zh_values.add(v)
    elif isinstance(v, list): zh_values.update(v)

con = sqlite3.connect(root / "state.db")
cnt = Counter()
for (tags,) in con.execute("SELECT tags FROM processed"):
    for t in json.loads(tags or "[]"):
        if t.lower() not in tm and t not in zh_values and t.isascii():
            cnt[t] += 1

print(f"實際出現過但沒中文的標籤：{len(cnt)} 個\n")
for t, n in cnt.most_common():
    print(f"{n:5d}  {t}")
