#!/usr/bin/env python3
"""補救：把資料夾裡「沒有 EXIF 拍攝日期」的圖片，用檔案修改時間寫進 DateTimeOriginal。

適用於已經被舊版 Prism 處理過、時間軸跑掉的截圖類檔案（-P 保住了修改時間，所以能救回來）。
不跑 Vision，只動日期欄位，很快。

用法:
  python scripts/fix_dates.py <資料夾>            # 只列出會動哪些檔
  python scripts/fix_dates.py <資料夾> --write    # 實際寫入
"""
import argparse, subprocess, sys
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("folder")
ap.add_argument("--write", action="store_true")
args = ap.parse_args()
root = Path(args.folder).expanduser()

# 一次呼叫 exiftool 遞迴列出所有「沒有任何拍攝日期」的圖片
r = subprocess.run(
    ["exiftool", "-r", "-q", "-if",
     "not $EXIF:DateTimeOriginal and not $EXIF:CreateDate and not $XMP:CreateDate and not $XMP:DateCreated and not $QuickTime:CreateDate",
     "-ext", "jpg", "-ext", "jpeg", "-ext", "png", "-ext", "heic", "-ext", "dng",
     "-i", "@eaDir", "-i", "#recycle",
     "-p", "$Directory/$FileName", str(root)],
    capture_output=True, text=True)
files = [l for l in r.stdout.splitlines() if l.strip()]
print(f"找到 {len(files)} 張沒有拍攝日期的圖片", file=sys.stderr)
for f in files[:20]:
    print("  " + f)
if len(files) > 20:
    print(f"  … 共 {len(files)} 張")

if not args.write:
    print("\n加 --write 才會實際寫入", file=sys.stderr)
    sys.exit(0)

# 批次寫入（exiftool 一個行程處理全部，比逐檔快很多）
if files:
    r = subprocess.run(
        ["exiftool", "-overwrite_original_in_place", "-P", "-q",
         "-EXIF:DateTimeOriginal<FileModifyDate", "-EXIF:CreateDate<FileModifyDate",
         "-XMP:CreateDate<FileModifyDate", "-XMP:DateCreated<FileModifyDate",
         *files],
        capture_output=True, text=True)
    print(r.stdout.strip() or "完成", file=sys.stderr)
    if r.stderr.strip():
        print(r.stderr.strip(), file=sys.stderr)
