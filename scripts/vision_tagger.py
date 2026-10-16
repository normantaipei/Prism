#!/usr/bin/env python3
"""
Prism — 用 macOS Vision framework 幫 NAS 照片加標籤

預設只印出分析結果，不動檔案。加 --write 才會用 exiftool 寫入
IPTC:Keywords + XMP-dc:Subject（Synology Photos 會自動索引這兩個欄位）。

用法:
  ./run.sh <資料夾>                        # 只印出，不寫
  ./run.sh <資料夾> --limit 5              # 先試 5 張
  ./run.sh <資料夾> --write                # 寫入 JPG
  ./run.sh <資料夾> --write --raw-mode sidecar   # RAW 另寫 .xmp sidecar
  ./run.sh <資料夾> --write --force        # 忽略已處理紀錄，重跑

已處理的檔案記在 state.db（SQLite），再跑同一個資料夾會自動跳過。
"""

import argparse
import hashlib
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

try:
    import objc
    import Vision
    from Foundation import NSURL
except ImportError:
    sys.exit("缺少 pyobjc：請先執行 ./setup.sh")

PROJECT_DIR = Path(__file__).resolve().parent.parent
STATE_DB = PROJECT_DIR / "state.db"
TAG_MAP = PROJECT_DIR / "tag_map.json"

IMAGE_EXT = {".jpg", ".jpeg", ".heic", ".png"}
RAW_EXT = {".arw", ".raw", ".dng", ".cr2", ".cr3", ".nef", ".raf", ".orf", ".rw2"}
SKIP_DIRS = {"@eaDir", "#recycle"}


# ---------- 狀態紀錄 ----------

def db_init():
    con = sqlite3.connect(STATE_DB)
    con.execute("""CREATE TABLE IF NOT EXISTS processed (
        path TEXT PRIMARY KEY,
        size INTEGER,
        mtime REAL,
        tags TEXT,
        aesthetic REAL,
        written INTEGER,
        ts REAL)""")
    con.commit()
    return con


def db_seen(con, p: Path, written_only: bool, st=None) -> bool:
    """同路徑、同大小、同 mtime 視為已處理（寫入會改 mtime，所以寫過後也會更新紀錄）。"""
    st = st or p.stat()
    row = con.execute("SELECT size, mtime, written FROM processed WHERE path=?", (str(p),)).fetchone()
    if not row:
        return False
    if written_only and not row[2]:
        return False
    return row[0] == st.st_size and abs(row[1] - st.st_mtime) < 1


def db_mark(con, p: Path, tags, aesthetic, written: bool):
    st = p.stat()
    con.execute("INSERT OR REPLACE INTO processed VALUES (?,?,?,?,?,?,?)",
                (str(p), st.st_size, st.st_mtime, json.dumps(tags, ensure_ascii=False),
                 aesthetic, int(written), time.time()))
    con.commit()


# ---------- 檔案列舉 ----------

def iter_images(root: Path):
    """用 os.scandir 逐目錄串流列出圖片，不先把整棵樹讀完。
    scandir 一次目錄只要一次網路來回，而且 entry 自帶 is_file / stat 快取，
    對 SMB 上幾萬張的資料夾比 rglob + 逐檔 stat 快一個數量級。"""
    import os
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                entries = sorted(it, key=lambda e: e.name)
        except OSError as e:
            print(f"  略過 {d}: {e}", file=sys.stderr)
            continue
        names = {e.name for e in entries}
        subdirs = []
        for e in entries:
            if e.name in SKIP_DIRS or e.name.startswith("."):
                continue
            if e.is_dir(follow_symlinks=False):
                subdirs.append(Path(e.path))
                continue
            if not e.is_file(follow_symlinks=False) or e.name.endswith("_original"):
                continue
            stem, ext = os.path.splitext(e.name)
            ext = ext.lower()
            if ext in IMAGE_EXT:
                yield Path(e.path), e.stat()
            elif ext in RAW_EXT:
                # 同目錄已有同名 JPG 就不分析 RAW（用剛列出的名稱判斷，不再 stat）
                if not any((stem + j) in names for j in (".jpg", ".JPG", ".jpeg", ".JPEG")):
                    yield Path(e.path), e.stat()
        stack.extend(reversed(subdirs))  # 保持字母序


def sibling_raws(p: Path):
    out = []
    for e in RAW_EXT:
        for cand in (p.with_suffix(e), p.with_suffix(e.upper())):
            if cand.exists() and cand not in out:
                out.append(cand)
    return out


# ---------- Vision ----------

def analyze(path: Path, min_conf: float, top_n: int):
    # 每張圖一個 autorelease pool：pyobjc 在長迴圈裡不會自動釋放 ObjC 物件，
    # VNImageRequestHandler 開的檔案 handle 會一直累積，幾千張後 "Too many open files"。
    with objc.autorelease_pool():
        url = NSURL.fileURLWithPath_(str(path))
        handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, None)

        classify = Vision.VNClassifyImageRequest.alloc().init()
        requests = [classify]

        aesthetics = None
        if hasattr(Vision, "VNCalculateImageAestheticsScoresRequest"):  # macOS 15+
            aesthetics = Vision.VNCalculateImageAestheticsScoresRequest.alloc().init()
            requests.append(aesthetics)

        ok, err = handler.performRequests_error_(requests, None)
        if not ok:
            raise RuntimeError(str(err))

        labels = []
        for obs in classify.results() or []:
            conf = float(obs.confidence())
            if conf >= min_conf:
                labels.append((str(obs.identifier()), conf))
        labels.sort(key=lambda x: -x[1])
        labels = labels[:top_n]

        score = utility = None
        if aesthetics is not None and aesthetics.results():
            obs = aesthetics.results()[0]
            score = float(obs.overallScore())   # -1 ~ 1
            utility = bool(obs.isUtility())     # 截圖/文件類「工具照」

        # 離開 pool 前把 ObjC 物件丟掉，只帶純 Python 值出去
        del handler, classify, aesthetics, url
    return labels, score, utility


# ---------- 中文對照 ----------

def load_tag_map():
    if not TAG_MAP.exists():
        return {}
    raw = json.loads(TAG_MAP.read_text(encoding="utf-8"))
    out = {}
    for k, v in raw.items():
        if k.startswith("_"):
            continue
        out[k.lower()] = [v] if isinstance(v, str) else list(v)
    return out


def localize(tags, tag_map, lang: str, missing: set):
    """lang: both = 英+中 / zh = 只中文（查不到的保留英文） / en = 只英文"""
    if lang == "en":
        return list(tags)
    out = []
    for t in tags:
        zh = tag_map.get(t.lower())
        if lang == "both":
            out.append(t)
        if zh:
            out.extend(zh)
        else:
            missing.add(t)
            if lang == "zh":
                out.append(t)
    # 去重保序
    seen, dedup = set(), []
    for x in out:
        if x not in seen:
            seen.add(x); dedup.append(x)
    return dedup


# ---------- 美學 → 星等 ----------

# Vision overallScore 範圍 -1 ~ +1。門檻可用 --rating-thresholds 調整。
DEFAULT_THRESHOLDS = [-0.4, -0.1, 0.2, 0.5]   # 低於 t0 → 1星, t0~t1 → 2星, ... 高於 t3 → 5星

def score_to_stars(score, thresholds):
    if score is None:
        return None
    stars = 1
    for t in thresholds:
        if score >= t:
            stars += 1
    return stars


def read_meta(path: Path) -> dict:
    """一次讀出寫入前要知道的欄位：既有星等、有沒有拍攝日期。"""
    r = subprocess.run(
        ["exiftool", "-s3", "-f", "-XMP:Rating", "-EXIF:DateTimeOriginal", "-EXIF:CreateDate",
         "-XMP:CreateDate", "-XMP:DateCreated", "-QuickTime:CreateDate", str(path)],
        capture_output=True, text=True)
    vals = [v.strip() for v in r.stdout.splitlines()]
    vals += ["-"] * (6 - len(vals))
    rating = None
    if vals[0] not in ("-", ""):
        try:
            rating = int(float(vals[0]))
        except ValueError:
            pass
    has_date = any(v not in ("-", "", "0000:00:00 00:00:00") for v in vals[1:])
    return {"rating": rating, "has_date": has_date}


# ---------- 寫入 ----------

def write_tags(path: Path, tags, raw_mode: str, marker: str, stars=None, fill_date=False) -> bool:
    kw = list(tags) + ([marker] if marker else [])
    # -overwrite_original_in_place：原地覆寫，不走「暫存檔再改名」，保住檔案建立時間
    # -P：保留修改時間
    args = ["exiftool", "-overwrite_original_in_place", "-charset", "iptc=UTF8", "-P",
            "-api", "NoDups=1"]  # 重跑時不讓同一關鍵字重複（需 exiftool >= 12.35）
    if fill_date:
        # 截圖、通訊軟體存圖等沒有 EXIF 拍攝日期的檔案，Synology Photos 會退而用檔案時間，
        # 一旦檔案被重寫時間軸就跑掉。把原本的修改時間寫進 metadata，日期就跟著檔案走了。
        args += ["-EXIF:DateTimeOriginal<FileModifyDate", "-EXIF:CreateDate<FileModifyDate",
                 "-XMP:CreateDate<FileModifyDate", "-XMP:DateCreated<FileModifyDate"]
    for t in kw:
        args += [f"-IPTC:Keywords+={t}", f"-XMP-dc:Subject+={t}"]
    if stars is not None:
        args += [f"-XMP:Rating={stars}"]

    targets = [str(path)]
    if raw_mode != "none":
        for raw in sibling_raws(path):
            if raw_mode == "embed":
                targets.append(str(raw))
            else:  # sidecar
                side = raw.with_suffix(raw.suffix + ".xmp")
                if not side.exists():
                    subprocess.run(["exiftool", "-o", str(side), "-TagsFromFile", str(raw), "-xmp:all"],
                                   capture_output=True)
                targets.append(str(side))

    r = subprocess.run(args + targets, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"    exiftool 錯誤: {r.stderr.strip()}", file=sys.stderr)
        return False
    return True


# ---------- main ----------

def raise_fd_limit():
    """macOS 預設 soft limit 很低（256~4096），拉到 hard limit 以免長批次中途爆掉。"""
    try:
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        target = min(hard, 65536) if hard != resource.RLIM_INFINITY else 65536
        if soft < target:
            resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))
    except Exception:
        pass


def main():
    raise_fd_limit()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder")
    ap.add_argument("--limit", type=int, default=0, help="只處理前 N 張（0=全部）")
    ap.add_argument("--min-conf", type=float, default=0.3, help="標籤最低信心 0~1（預設 0.3）")
    ap.add_argument("--top", type=int, default=12, help="每張最多幾個標籤（預設 12）")
    ap.add_argument("--write", action="store_true", help="實際寫入關鍵字")
    ap.add_argument("--raw-mode", choices=["none", "embed", "sidecar"], default="none",
                    help="同名 RAW：none 不寫 / embed 寫進 RAW / sidecar 寫 .xmp（預設 none）")
    ap.add_argument("--marker", default="AI_VISION", help="額外標記 tag（空字串=不加）")
    ap.add_argument("--rating", action="store_true",
                    help="把美學分數寫成 XMP:Rating 星等（Synology Photos 的星星）")
    ap.add_argument("--rating-overwrite", action="store_true",
                    help="就算檔案已有星等也覆蓋（預設只寫沒評過分的）")
    ap.add_argument("--rating-thresholds", default=",".join(map(str, DEFAULT_THRESHOLDS)),
                    help="四個分數門檻切出 1~5 星，預設 %(default)s")
    ap.add_argument("--lang", choices=["both", "zh", "en"], default="both",
                    help="標籤語言：both 中英都寫（預設）/ zh 只中文 / en 只英文")
    ap.add_argument("--force", action="store_true", help="忽略 state.db，全部重跑")
    ap.add_argument("--json", action="store_true", help="JSON 輸出")
    args = ap.parse_args()

    root = Path(args.folder).expanduser()
    if not root.is_dir():
        sys.exit(f"找不到資料夾: {root}")

    thresholds = sorted(float(x) for x in args.rating_thresholds.split(","))
    if len(thresholds) != 4:
        sys.exit("--rating-thresholds 需要 4 個數字")

    con = db_init()
    tag_map = load_tag_map()
    missing_zh = set()
    mode = "（會寫入）" if args.write else "（只印出）"
    print(f"開始掃描 {root} {mode}，邊掃邊處理…\n", file=sys.stderr)

    def pending():
        """串流產生要處理的檔案，順便印掃描進度。"""
        seen = skipped = 0
        last = time.time()
        for p, st in iter_images(root):
            seen += 1
            if not args.force and db_seen(con, p, written_only=args.write, st=st):
                skipped += 1
                if time.time() - last > 2:
                    print(f"  掃描中… 已看 {seen} 張，跳過 {skipped} 張已處理", file=sys.stderr)
                    last = time.time()
                continue
            yield p
        if skipped:
            print(f"\n掃描完成：共 {seen} 張，跳過 {skipped} 張已處理", file=sys.stderr)

    files = pending()
    if args.limit:
        import itertools
        files = itertools.islice(files, args.limit)

    results = []
    t0 = time.time()
    for i, p in enumerate(files, 1):  # files 是 generator，總數未知
        try:
            labels, score, utility = analyze(p, args.min_conf, args.top)
        except Exception as e:
            print(f"[{i}] {p.name}  分析失敗: {e}", file=sys.stderr)
            continue

        en_tags = [l for l, _ in labels]
        tags = localize(en_tags, tag_map, args.lang, missing_zh)
        rec = {"file": str(p), "tags": tags,
               "labels": [{"id": l, "conf": round(c, 3)} for l, c in labels],
               "aesthetic": None if score is None else round(score, 3),
               "utility": utility}
        results.append(rec)

        if not args.json:
            print(f"[{i}] {p.name}")
            if score is not None:
                st = score_to_stars(score, thresholds)
                print(f"    美學 {score:+.2f}  {'★' * st}{'☆' * (5 - st)}{'  (工具照)' if utility else ''}")
            for l, c in labels:
                zh = " / ".join(tag_map.get(l.lower(), []))
                print(f"    {c:.2f}  {l}" + (f"  → {zh}" if zh else "  (無中文)"))
            if not labels:
                print("    (沒有超過門檻的標籤，試試 --min-conf 0.1)")

        stars = None
        fill_date = False
        if args.write:
            meta = read_meta(p)
            fill_date = not meta["has_date"]
            if args.rating and score is not None and (args.rating_overwrite or meta["rating"] in (None, 0)):
                stars = score_to_stars(score, thresholds)
        written = False
        if args.write and (tags or stars is not None or fill_date):
            written = write_tags(p, tags, args.raw_mode, args.marker, stars, fill_date)
            if not args.json:
                note = "  (補上拍攝日期)" if fill_date else ""
                print(("    -> 已寫入" + note) if written else "    -> 寫入失敗")
        db_mark(con, p, tags, score, written)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(f"\n完成 {len(results)} 張，{time.time()-t0:.1f} 秒", file=sys.stderr)
        if missing_zh and args.lang != "en":
            print(f"\n以下 {len(missing_zh)} 個標籤 tag_map.json 還沒有中文，可自行補上：", file=sys.stderr)
            print("  " + ", ".join(sorted(missing_zh)), file=sys.stderr)


if __name__ == "__main__":
    main()
