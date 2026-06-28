# 廣告素材生成平台

這是一套給電商、品牌方與廣告投手使用的內部工具，可建立產品專案、分析受眾與賣點、產生平面素材、短影音腳本、分鏡圖、配音、影片合成，以及爆款素材拆解。

## 技術棧

- Next.js App Router
- Tailwind CSS + shadcn/ui 風格元件
- PostgreSQL + Prisma
- OpenAI API / OpenAI Images / OpenAI Vision / OpenAI 語音轉文字
- ElevenLabs 配音
- FFmpeg 影片處理
- Sharp 圖片處理
- Playwright 商品頁擷取
- Local Storage，正式環境可擴充 S3 / Cloudflare R2

## 主要頁面

- `/`：Dashboard
- `/help`：新進行銷人員使用說明
- `/brands`：Brand Brain
- `/competitors`：競品情報
- `/projects/new`：新增產品分析專案
- `/projects/[id]`：產品分析報告
- `/projects/[id]/static-creatives`：平面素材
- `/projects/[id]/video-scripts`：短影音腳本與分鏡
- `/projects/[id]/viral-analysis`：爆款影片分析
- `/projects/[id]/crowdfunding`：嘖嘖募資頁架構與案例拆解
- `/kols`：KOL 分析
- `/settings`：平台設定與模型切換

## Reference-Locked 參考素材鎖定

素材生成不只依靠文字 prompt。使用者可以針對主商品、人物、動物、道具、場景上傳多張參考圖，並標註用途、角度與備註，降低 AI 生成素材時主商品跑掉的機率。

支援用途範例：

- 主商品正面
- 主商品側面
- 商品細節特寫
- Logo / 包裝文字
- 使用情境
- 手持比例
- 配角外觀
- 場景道具

相關檔案：

- `components/reference-asset-manager.tsx`
- `app/api/projects/[id]/reference-assets/route.ts`
- `lib/services/reference-asset-service.ts`
- `lib/image-generation.ts`
- `lib/ai/providers/openai-image.ts`

## 嘖嘖募資頁規劃

「募資頁」模組可用於群眾募資頁面企劃。

功能：

- 輸入嘖嘖案例網址
- Playwright 擷取案例頁文字、圖片與截圖
- AI 拆解案例頁面架構、圖片策略、文案公式與轉換設計
- 將案例模板套用到目前產品
- 產生嘖嘖募資頁段落架構
- 產生每段頁面圖需求與 AI 生圖 prompt
- 產生首屏、痛點、解決方案、功能、方案、FAQ 文案
- 產生 AI 預測轉換評分

新增資料表：

- `CrowdfundingCaseAnalysis`
- `CrowdfundingPagePlan`

新增 API：

- `GET /api/projects/[id]/crowdfunding/cases`
- `POST /api/projects/[id]/crowdfunding/cases`
- `GET /api/projects/[id]/crowdfunding/plans`
- `POST /api/projects/[id]/crowdfunding/plans`

相關檔案：

- `app/projects/[id]/crowdfunding/page.tsx`
- `components/crowdfunding-client.tsx`
- `lib/services/crowdfunding-service.ts`
- `lib/prompts/crowdfunding.ts`
- `lib/crowdfunding-fallbacks.ts`

## 環境變數

請建立 `.env` 或 `.env.local`：

```env
DATABASE_URL="postgresql://postgres:postgres@localhost:5432/ad_creative_intelligence?schema=public"
AUTH_SECRET=""
ADMIN_EMAIL=""
ADMIN_PASSWORD=""

OPENAI_API_KEY=""
OPENAI_MODEL="gpt-5.5"
OPENAI_VISION_MODEL="gpt-4o-mini"
OPENAI_IMAGE_MODEL="gpt-image-1"
OPENAI_IMAGE_MAX_RETRIES="4"
OPENAI_IMAGE_REFERENCE_LIMIT="3"
OPENAI_IMAGE_REFERENCE_MAX_WIDTH="1400"
OPENAI_IMAGE_REFERENCE_QUALITY="80"
OPENAI_TRANSCRIBE_MODEL="gpt-4o-mini-transcribe"

ELEVENLABS_API_KEY=""
ELEVENLABS_VOICE_ID_MALE=""
ELEVENLABS_VOICE_ID_FEMALE=""

FAL_API_KEY=""
FAL_KEY=""
FAL_FLUX_LORA_TRAINING_ENDPOINT="fal-ai/flux-lora-fast-training"

FFMPEG_PATH=""
MAX_UPLOAD_MB="200"
UPLOAD_IMAGE_MAX_WIDTH="1800"
UPLOAD_IMAGE_QUALITY="82"
VISION_IMAGE_MAX_WIDTH="1200"
VISION_IMAGE_QUALITY="76"
STORAGE_PROVIDER="local"
JOB_AUTO_START="true"

VIDEO_PROVIDER="kling"
KLING_API_KEY=""
KLING_API_BASE_URL="https://api.klingai.com"
KLING_IMAGE_TO_VIDEO_PATH="/v1/videos/image2video"
KLING_TASK_STATUS_PATH="/v1/videos/image2video/{taskId}"
KLING_MODEL="kling-v1-6"
KLING_MODE="std"
KLING_CFG_SCALE="0.5"
KLING_TIMEOUT_MS="600000"
KLING_POLL_INTERVAL_MS="8000"
```

## 本機啟動

```bash
docker compose up -d
pnpm install
pnpm prisma migrate dev
pnpm dev
```

開啟：

```text
http://127.0.0.1:3100
```

## Render 部署

Render Web Service 建議設定：

- Environment：Docker
- Region：Singapore，與資料庫同區
- Persistent Disk mount path：`/app/public/uploads`
- Persistent Disk size：建議從 10GB 開始
- Start command：使用 Dockerfile 內的 CMD
- `DATABASE_URL`：使用 Render Postgres 的 Internal Database URL

Render Environment Variables 至少需要：

```env
DATABASE_URL=""
AUTH_SECRET=""
ADMIN_EMAIL=""
ADMIN_PASSWORD=""
OPENAI_API_KEY=""
ELEVENLABS_API_KEY=""
ELEVENLABS_VOICE_ID_MALE=""
ELEVENLABS_VOICE_ID_FEMALE=""
FFMPEG_PATH="ffmpeg"
STORAGE_PROVIDER="local"
JOB_AUTO_START="true"
```

## 登入保護

正式環境請設定：

```env
AUTH_SECRET="至少 32 字元以上的隨機字串"
ADMIN_EMAIL="管理員 email"
ADMIN_PASSWORD="管理員密碼"
```

`AUTH_SECRET` 用於簽發登入 cookie，`ADMIN_EMAIL` 與 `ADMIN_PASSWORD` 是目前的簡易管理員帳密。

## 圖片與素材生成穩定性

Render Starter 只有 512MB RAM，若一次上傳多張高解析產品圖並立即產生素材，可能造成服務記憶體不足，瀏覽器會看到 `502 Bad Gateway`。

目前系統已加入保護：

- 上傳圖片會自動壓縮成較小的 JPG
- Vision 分析會使用縮小圖
- OpenAI Images 參考圖預設最多取 3 張
- 送入 OpenAI Images 前會再壓縮參考圖

可調整的環境變數：

```env
UPLOAD_IMAGE_MAX_WIDTH="1800"
UPLOAD_IMAGE_QUALITY="82"
VISION_IMAGE_MAX_WIDTH="1200"
VISION_IMAGE_QUALITY="76"
OPENAI_IMAGE_REFERENCE_LIMIT="3"
OPENAI_IMAGE_REFERENCE_MAX_WIDTH="1400"
OPENAI_IMAGE_REFERENCE_QUALITY="80"
```

如果仍然出現 `502 Bad Gateway`：

1. 先到 Render Logs 檢查是否有 `out of memory`、`Killed`、`JavaScript heap out of memory`。
2. 把 `OPENAI_IMAGE_REFERENCE_LIMIT` 暫時降到 `1`。
3. 重新上傳已壓縮後的產品圖。
4. 若仍不穩，Render 方案需升級到 Standard 2GB RAM。

## 產品 LoRA 訓練

產品專案內的 `/projects/[id]/lora-models` 可用 fal.ai FLUX LoRA 訓練產品模型。

使用流程：

1. 先上傳 15-30 張產品圖片，至少 4 張。
2. 進入「產品模型」頁。
3. 設定 trigger word，例如 `ubpet_c41_litterbox`。
4. 選取訓練圖片。
5. 按「開始 fal LoRA 訓練」。
6. 訓練送出後，按「同步狀態」查詢 fal 訓練結果。

訓練完成後會保存：

- fal request id
- trigger word
- diffusers LoRA URL
- config file URL
- debug preprocessed output URL

Render 需要設定：

```env
FAL_API_KEY="你的 fal key"
FAL_KEY="你的 fal key"
FAL_FLUX_LORA_TRAINING_ENDPOINT="fal-ai/flux-lora-fast-training"
```

## 上傳檔案

Render Web Service 必須新增 Persistent Disk：

```text
Mount path: /app/public/uploads
Size: 10 GB
```

所有新上傳檔案會透過 `/api/files/...` 讀取，不會直接暴露 public uploads 路徑。若舊檔案是在沒有 Persistent Disk 前上傳，Render 重新部署後可能已不存在，需要重新上傳。

## 測試

```bash
pnpm build
```
