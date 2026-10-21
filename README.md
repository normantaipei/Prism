# Prism

把照片丟進去，分出標籤和評分。

**只要有一台 Mac，就能讓任何第三方相簿擁有和 Apple「照片」一樣的自動分類能力，而且不花一毛 token 費用。**

Apple 照片 App 之所以能自動認出「海邊」「貓」「生日蛋糕」，靠的是 macOS 內建的 Vision framework。
這套模型其實是公開 API，任何程式都能呼叫，只是沒人把它接到 NAS 相簿上。
Prism 做的就是這件事：掛載你的 NAS 照片資料夾 → 用 Vision 跑分類與美學評分 → 把結果寫進照片本身的
IPTC/XMP metadata。Synology Photos、Immich、Lightroom、digiKam……任何讀標準 metadata 的相簿都能直接搜到。

- **零成本**：不呼叫任何雲端 AI，所有運算在你的 Mac 上完成，M 系列晶片一張約 0.1 秒
- **照片不出門**：不上傳任何東西，對 cosplay、人像這類有肖像權考量的照片特別重要
- **標籤跟著檔案走**：寫在 metadata 裡，換 NAS、換相簿軟體都不會丟
- **中英雙語**：內建 Vision 全部 1303 個標籤的繁體中文對照，中文搜尋也找得到
- **美學評分 → 星等**：Vision 的美學分數轉成 1~5 星寫進 `XMP:Rating`，廢片一鍵篩掉

目前以 Synology Photos 為主要目標實測（寫入後幾分鐘內可搜尋到，不需手動重建索引），
但只要相簿會讀 IPTC Keywords / XMP Subject / XMP Rating，就能用。

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
./run.sh ~/mnt/PhotoLibrary/<某個拍攝資料夾> --limit 5

# 滿意後實際寫入 JPG
./run.sh ~/mnt/PhotoLibrary/<某個拍攝資料夾> --write

# RAW 也要：先用 sidecar 測 Synology Photos 讀不讀 .xmp
./run.sh ~/mnt/PhotoLibrary/<某個拍攝資料夾> --write --raw-mode sidecar
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
| `--rating-thresholds a,b,c,d` | 四個門檻切 1~5 星，預設 `0,0.4,0.55,0.7`；先用 `scripts/score_histogram.py` 看分布再調 |
| `--lang both/zh/en` | 標籤語言，預設中英都寫（Synology Photos 搜尋只比對標籤文字，英文標籤搜中文找不到） |
| `--marker AI_VISION` | 額外加一個標記 tag，在 Synology Photos 搜這個就能看到哪些跑過了 |
| `--shard I/N` | 多台機器分工：這台只處理第 I 片（0 起算），共 N 片 |
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
失焦／誤觸的廢片會掉到 0 以下，所以預設門檻是 `0,0.4,0.55,0.7`（不加 `--rating-thresholds` 就用這組）。

## 多台 Mac 一起跑

每台給一個分片編號，用檔名 hash 切分，互不重疊、不需要共享狀態（同名 JPG/RAW 保證落在同一台）：

```bash
# 機器 A                                  # 機器 B
./run.sh <資料夾> --write --shard 0/2      ./run.sh <資料夾> --write --shard 1/2
```

三台就 `0/3`、`1/3`、`2/3`。瓶頸最終會落在 NAS 的 SMB 與硬碟，機器加到一定數量就不再變快。

## 沒有拍攝日期的檔案（截圖、通訊軟體存圖）

這類檔案沒有 EXIF 日期，Synology Photos 只能用檔案時間排時間軸，檔案一被改寫日期就會跑掉。
Prism 寫入時會偵測並把原本的修改時間補進 `DateTimeOriginal`，讓日期跟著 metadata 走。
已經跑掉的用 `python scripts/fix_dates.py <資料夾> --write` 一次補回（只動日期，不重跑 Vision）。

## 注意

- `@eaDir`（Synology 縮圖）會自動排除。
- `--write` 會原地覆寫、不留 `_original` 備份；第一次請先在小資料夾測。
- `-P` 會保留檔案原本的修改日期，所以 Synology Photos 的時間軸不會跑掉。
- Vision 的標籤是通用詞彙（person / costume / indoor…），角色、coser、活動名這類標籤
  需另外從資料夾名或對照表補，或接本機 VLM（Ollama + Qwen2-VL）。

## 後續可加

- [ ] 從資料夾名解析日期與活動名自動加 tag
- [ ] `VNGenerateImageFeaturePrintRequest` 做連拍去重
- [ ] 美學分數低於門檻的照片自動加 `LOW_QUALITY` tag
- [ ] 本機 VLM 補語意標籤
