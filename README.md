# 廣告素材生成與爆款素材分析平台

給電商、品牌方、廣告投手與行銷團隊使用的內部工具。平台可管理產品分析專案，產生平面素材、影片腳本、分鏡圖、配音、影片合成、爆款影片拆解、KOL 分析，並支援參考素材鎖定，降低 AI 生成素材時主商品跑掉的機率。

## 技術棧

- Next.js App Router
- Tailwind CSS + shadcn/ui 風格元件
- PostgreSQL + Prisma
- OpenAI API / OpenAI Images / OpenAI Vision / OpenAI 語音轉文字
- ElevenLabs 配音
- FFmpeg 影片處理
- Sharp 圖片處理
- Playwright 商品頁與案例頁擷取
- 本機 Storage Layer，預留 S3 / R2

## 主要頁面

- `/`：Dashboard
- `/help`：新進行銷人員使用說明
- `/brands`：品牌中心 / Brand Brain
- `/competitors`：競品情報
- `/projects/new`：新增產品分析專案
- `/projects/[id]`：產品分析報告
- `/projects/[id]/static-creatives`：平面素材建議與 AI 生成圖
- `/projects/[id]/video-scripts`：短影音腳本、分鏡、配音、影片合成
- `/projects/[id]/viral-analysis`：爆款影片分析
- `/projects/[id]/crowdfunding`：嘖嘖募資頁案例拆解與頁面規劃
- `/kols`：KOL 分析工具
- `/settings`：模型、供應商與流程設定

## Reference-Locked 參考素材鎖定

素材生成不只依靠文字 prompt。使用者可以針對主商品、人物、動物、道具、場景上傳多張參考圖，並標註用途、角度與備註。

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

新增「募資頁」模組，可用於群眾募資頁面企劃。

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
OPENAI_API_KEY=""
OPENAI_MODEL="gpt-5.5"
OPENAI_VISION_MODEL="gpt-4o-mini"
OPENAI_IMAGE_MODEL="gpt-image-1"
OPENAI_IMAGE_MAX_RETRIES="4"
OPENAI_TRANSCRIBE_MODEL="gpt-4o-mini-transcribe"
ELEVENLABS_API_KEY=""
ELEVENLABS_VOICE_ID_MALE=""
ELEVENLABS_VOICE_ID_FEMALE=""
FFMPEG_PATH=""
MAX_UPLOAD_MB="200"
STORAGE_PROVIDER="local"
JOB_AUTO_START="true"
VIDEO_PROVIDER="kling"
KLING_API_KEY=""
KLING_API_BASE_URL=""
KLING_IMAGE_TO_VIDEO_PATH=""
KLING_TASK_STATUS_PATH=""
```

## 啟動方式

```bash
docker compose up -d
pnpm install
pnpm prisma migrate dev
pnpm dev
```

本機網址：

```text
http://127.0.0.1:3100
```

## Render 部署

本專案已包含：

- `Dockerfile`
- `.dockerignore`
- `render.yaml`

Render 建議設定：

- Environment：Docker
- Persistent Disk mount path：`/app/public/uploads`
- Start command：使用 Dockerfile 預設 CMD
- `DATABASE_URL`：使用 Render Postgres 的 Internal Database URL

必要環境變數：

```env
DATABASE_URL=""
OPENAI_API_KEY=""
OPENAI_MODEL="gpt-5.5"
OPENAI_VISION_MODEL="gpt-4o-mini"
OPENAI_IMAGE_MODEL="gpt-image-1"
OPENAI_IMAGE_MAX_RETRIES="4"
OPENAI_TRANSCRIBE_MODEL="gpt-4o-mini-transcribe"
ELEVENLABS_API_KEY=""
ELEVENLABS_VOICE_ID_MALE=""
ELEVENLABS_VOICE_ID_FEMALE=""
FFMPEG_PATH="ffmpeg"
MAX_UPLOAD_MB="200"
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

Docker 啟動時會自動執行：

```bash
pnpm prisma migrate deploy
pnpm start
```

## 測試

```bash
pnpm build
```
