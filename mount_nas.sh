#!/bin/bash
# 確認 NAS 已掛載，沒有就掛（讀 .env）
set -e
cd "$(dirname "$0")"
set -a; source .env; set +a
MOUNT_POINT=$(eval echo "$MOUNT_POINT")
mkdir -p "$MOUNT_POINT"
if mount | grep -q " $MOUNT_POINT "; then
  echo "已掛載：$MOUNT_POINT"
else
  mount_smbfs "//$NAS_USER@$NAS_HOST/$NAS_SHARE" "$MOUNT_POINT"
  echo "掛載完成：$MOUNT_POINT"
fi
