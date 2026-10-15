#!/usr/bin/env python3
"""看 state.db 裡美學分數的分布，決定 --rating-thresholds 要設多少。
用法: python scripts/score_histogram.py [門檻,門檻,門檻,門檻]
"""
import sqlite3, sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
rows = [r[0] for r in sqlite3.connect(root / "state.db").execute(
    "SELECT aesthetic FROM processed WHERE aesthetic IS NOT NULL")]
if not rows:
    sys.exit("state.db 還沒有分數")

th = [float(x) for x in (sys.argv[1] if len(sys.argv) > 1 else "-0.4,-0.1,0.2,0.5").split(",")]
rows.sort()
n = len(rows)
print(f"{n} 張  最低 {rows[0]:+.2f}  中位 {rows[n//2]:+.2f}  最高 {rows[-1]:+.2f}\n")

print("分布（每格 0.1）：")
lo = -1.0
while lo < 1.0:
    c = sum(lo <= s < lo + 0.1 for s in rows)
    print(f"  {lo:+.1f} ~ {lo+0.1:+.1f}  {'#' * (c * 60 // max(1, n))}  {c}")
    lo += 0.1

print(f"\n用門檻 {th} 會得到：")
for star in range(1, 6):
    if star == 1:   c = sum(s < th[0] for s in rows)
    elif star == 5: c = sum(s >= th[3] for s in rows)
    else:           c = sum(th[star-2] <= s < th[star-1] for s in rows)
    print(f"  {'★'*star:<5} {c:4d} 張  ({c*100//n}%)")
