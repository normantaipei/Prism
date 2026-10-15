#!/bin/bash
# 第一次使用：建立 venv、裝依賴、檢查 exiftool
set -e
cd "$(dirname "$0")"

if ! command -v brew >/dev/null; then
  echo "需要 Homebrew：https://brew.sh"; exit 1
fi
command -v exiftool >/dev/null || brew install exiftool

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

[ -f .env ] || cp .env.example .env
mkdir -p logs

echo
echo "✅ 安裝完成。"
echo "   測試：./run.sh ~/mnt/PhotoLibrary/<某個拍攝資料夾> --limit 5"
