#!/bin/bash
# 包一層：確認掛載 + 啟用 venv + 跑 tagger
cd "$(dirname "$0")"
./mount_nas.sh >/dev/null || { echo "NAS 掛載失敗"; exit 1; }
source .venv/bin/activate
exec python scripts/vision_tagger.py "$@"
