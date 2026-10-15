# Prism

把照片丟進去，分出標籤和評分。

用 macOS 內建 Vision framework 幫 Synology NAS 上的照片自動加標籤。
零 API 費用，全部在 Mac 本機跑；標籤寫進檔案的 IPTC/XMP 關鍵字，
Synology Photos 會自動索引（已實測：寫入後幾分鐘內可搜尋到）。

## 架構

```
NAS (SMB) ──掛載──> Mac ──Vision 分析──> exiftool 寫回 Keywords ──> Synology Photos 自動索引
                                  └──> state.db 記錄已處理
```

## 第一次安裝

```bash
cd ~/SideProject/Prism
./setup.sh              # 裝 exiftool、建 .venv、裝 pyobjc
vim .env                # 確認 NAS IP / 帳號 / 共用路徑
```

免密碼掛載：建 `~/Library/Preferences/nsmb.conf`

```
[<NAS_IP>:<NAS_USER>]
password=你的NAS密碼
```

然後 `chmod 600 ~/Library/Preferences/nsmb.conf`。

## 使用

```bash
# 先看標籤品質，不寫檔
./run.sh ~/mnt/PhotoLibrary/2026_09_27_旭cos --limit 5

# 滿意後實際寫入 JPG
./run.sh ~/mnt/PhotoLibrary/2026_09_27_旭cos --write

# RAW 也要：先用 sidecar 測 Synology Photos 讀不讀 .xmp
./run.sh ~/mnt/PhotoLibrary/2026_09_27_旭cos --write --raw-mode sidecar
```

| 參數 | 說明 |
|---|---|
| `--limit N` | 只處理前 N 張 |
| `--min-conf 0.3` | 標籤最低信心值，想多一點標籤就調低 |
| `--top 12` | 每張最多幾個標籤 |
| `--write` | 實際寫入（預設只印） |
| `--raw-mode none/embed/sidecar` | 同名 RAW 怎麼處理 |
| `--rating` | 把美學分數寫成 `XMP:Rating`（Synology Photos 的星星），預設不覆蓋已有評分 |
| `--rating-overwrite` | 已有星等也覆蓋 |
| `--rating-thresholds a,b,c,d` | 四個門檻切 1~5 星，先用 `scripts/score_histogram.py` 看分布再調 |
| `--lang both/zh/en` | 標籤語言，預設中英都寫（Synology Photos 搜尋只比對標籤文字，英文標籤搜中文找不到） |
| `--marker AI_VISION` | 額外加一個標記 tag，在 Synology Photos 搜這個就能看到哪些跑過了 |
| `--force` | 忽略 state.db 重跑 |
| `--json` | 機器可讀輸出 |

## 排程（Mac mini）

```bash
# 先把 plist 裡的 YOUR_NAME 改成你的使用者名稱
cp launchd/com.prism.tagger.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.prism.tagger.plist
tail -f logs/out.log
```

停用：`launchctl unload ~/Library/LaunchAgents/com.prism.tagger.plist`

## 中文標籤

Synology Photos 的搜尋只比對標籤文字，英文標籤搜中文找不到，所以預設中英都寫。

- `tag_map.json`：Vision 全部 1303 個英文標籤 → 中文的對照表（值可為字串或陣列）。
- `scripts/build_tag_map.py`：翻譯的原始來源，改這裡再執行即可重新產生 `tag_map.json`。
- `scripts/dump_vision_labels.py`：列出這台 Mac 的 Vision 支援的全部標籤（新版 macOS 可能增加）。
- `scripts/missing_from_db.py`：統計實際出現過但沒中文的標籤。

## 美學評分

Vision 的 `VNCalculateImageAestheticsScoresRequest`（macOS 15+）會給 -1 ~ +1 的分數。
加 `--rating` 會依門檻切成 1~5 星寫進 `XMP:Rating`，Synology Photos 索引後可用「評分」篩選或建條件相簿。
先用 `scripts/score_histogram.py` 看自己照片的分布再決定門檻；實測 cos 棚拍大多落在 +0.3 ~ +0.7，
失焦／誤觸的廢片會掉到 0 以下，所以 `0,0.4,0.55,0.7` 是個合理的起點。

## 注意

- `@eaDir`（Synology 縮圖）會自動排除。
- `--write` 會用 `-overwrite_original`，不留 `_original` 備份；第一次請先在小資料夾測。
- `-P` 會保留檔案原本的修改日期，所以 Synology Photos 的時間軸不會跑掉。
- Vision 的標籤是通用詞彙（person / costume / indoor…），角色、coser、活動名這類標籤
  需另外從資料夾名或對照表補，或接本機 VLM（Ollama + Qwen2-VL）。

## 後續可加

- [ ] 從資料夾名解析日期與活動名自動加 tag
- [ ] `VNGenerateImageFeaturePrintRequest` 做連拍去重
- [ ] 美學分數低於門檻的照片自動加 `LOW_QUALITY` tag
- [ ] 本機 VLM 補語意標籤
