#!/usr/bin/env python3
"""補救：把資料夾裡「沒有 EXIF 拍攝日期」的圖片，用檔案修改時間寫進 DateTimeOriginal。

適用於已經被舊版 Prism 處理過、時間軸跑掉的截圖類檔案（-P 保住了修改時間，所以能救回來）。
不跑 Vision，只動日期欄位。

用法:
  python scripts/fix_dates.py <資料夾>            # 只列出會動哪些檔
  python scripts/fix_dates.py <資料夾> --write    # 實際寫入
"""
import argparse, subprocess, sys, time
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("folder")
ap.add_argument("--write", action="store_true")
ap.add_argument("--batch", type=int, default=200, help="每批寫幾個檔（預設 200）")
args = ap.parse_args()
root = Path(args.folder).expanduser()

# ---- 第一步：掃描 ----
# 讓 exiftool 印出「每個看過的檔案 + 有沒有日期」，邊讀邊算進度，而不是等它全部跑完
print(f"掃描 {root} …（走 SMB 每個檔要讀一次檔頭，幾萬張需要十幾分鐘）", file=sys.stderr)
proc = subprocess.Popen(
    ["exiftool", "-r", "-q", "-f", "-fast2",
     "-ext", "jpg", "-ext", "jpeg", "-ext", "png", "-ext", "heic", "-ext", "dng",
     "-i", "@eaDir", "-i", "#recycle",
     "-p", "$Directory/$FileName\t$EXIF:DateTimeOriginal|$EXIF:CreateDate|$XMP:CreateDate|$XMP:DateCreated|$QuickTime:CreateDate",
     str(root)],
    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)

files, seen, last = [], 0, time.time()
for line in proc.stdout:
    seen += 1
    path, _, dates = line.rstrip("\n").partition("\t")
    if all(d in ("-", "", "0000:00:00 00:00:00") for d in dates.split("|")):
        files.append(path)
    if time.time() - last > 2:
        print(f"  已掃 {seen} 張，沒日期的 {len(files)} 張", file=sys.stderr)
        last = time.time()
proc.wait()
print(f"\n掃描完成：共 {seen} 張，其中 {len(files)} 張沒有拍攝日期", file=sys.stderr)
for f in files[:20]:
    print("  " + f)
if len(files) > 20:
    print(f"  … 共 {len(files)} 張")

if not args.write:
    print("\n加 --write 才會實際寫入", file=sys.stderr)
    sys.exit(0)

# ---- 第二步：分批寫入 ----
done = 0
for i in range(0, len(files), args.batch):
    chunk = files[i:i + args.batch]
    r = subprocess.run(
        ["exiftool", "-overwrite_original_in_place", "-P", "-q", "-q",
         "-EXIF:DateTimeOriginal<FileModifyDate", "-EXIF:CreateDate<FileModifyDate",
         "-XMP:CreateDate<FileModifyDate", "-XMP:DateCreated<FileModifyDate",
         *chunk],
        capture_output=True, text=True)
    done += len(chunk)
    print(f"  已寫入 {done}/{len(files)}", file=sys.stderr)
    err = r.stderr.strip()
    if err:
        print("    " + err.replace("\n", "\n    "), file=sys.stderr)
print("完成", file=sys.stderr)
