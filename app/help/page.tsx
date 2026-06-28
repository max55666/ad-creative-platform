import Link from "next/link";
import { ArrowRight, Boxes, Building2, CheckCircle2, CircleHelp, Film, Settings, Sparkles, UserRound } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

const quickSteps = [
  {
    title: "1. 先建立品牌",
    description: "輸入品牌定位、語氣、視覺風格，建立 Brand Brain。之後產出的素材會比較一致。",
    href: "/brands",
    action: "前往品牌中心",
    icon: Building2
  },
  {
    title: "2. 再建立產品專案",
    description: "輸入產品介紹、售價、使用場景、競品資料，讓系統產生受眾、痛點與賣點分析。",
    href: "/projects/new",
    action: "新增產品分析",
    icon: Boxes
  },
  {
    title: "3. 產生素材方向",
    description: "進入產品專案後，可產生平面素材、短影音腳本、分鏡圖、配音與影片合成。",
    href: "/",
    action: "回 Dashboard 找專案",
    icon: Sparkles
  },
  {
    title: "4. 分析 KOL 或爆款素材",
    description: "需要做業配或參考競品影片時，可用 KOL 工具與爆款分析拆解可複製的腳本結構。",
    href: "/kols",
    action: "前往 KOL 工具",
    icon: UserRound
  }
];

const featureCards = [
  {
    title: "品牌中心",
    badge: "先做",
    description: "建立品牌腦，讓廣告圖、影片腳本、KOL 腳本使用同一套品牌語氣與視覺規則。",
    examples: ["品牌定位", "品牌語氣", "視覺規則", "素材檢查清單"]
  },
  {
    title: "產品分析",
    badge: "每天用",
    description: "把一個產品轉成行銷可用的分析報告，包含受眾、痛點、賣點與素材方向。",
    examples: ["目標受眾", "購買疑慮", "核心賣點", "素材角度"]
  },
  {
    title: "平面素材",
    badge: "給設計",
    description: "產生多組平面廣告方向，包含標題、副標、構圖、字卡、CTA 與模擬圖。",
    examples: ["痛點型", "Before / After", "評價見證", "促銷型"]
  },
  {
    title: "影片腳本",
    badge: "給拍攝",
    description: "產生短影音腳本、分鏡、字卡、口白、配音，並可合成影片草稿。",
    examples: ["Hook", "分鏡", "口白", "字幕", "CTA"]
  },
  {
    title: "爆款分析",
    badge: "拆解參考",
    description: "上傳參考影片，拆解 Hook、節奏、字卡、口白、音樂、CTA 與可複製模板。",
    examples: ["影片結構", "爆點推測", "可複製模板", "改寫腳本"]
  },
  {
    title: "KOL 工具",
    badge: "業配",
    description: "貼上 KOL 網址與過往業配影片，分析人設、粉絲輪廓與適合的產品合作方式。",
    examples: ["KOL 人設", "粉絲輪廓", "產品適配度", "專屬腳本"]
  }
];

const dailyWorkflows = [
  {
    title: "我要幫新產品想素材",
    steps: ["建立或選擇品牌", "新增產品分析專案", "確認受眾與痛點", "產生平面素材與影片腳本", "挑 3-5 組交給設計或剪輯"]
  },
  {
    title: "我要拆解競品或爆款影片",
    steps: ["進入產品專案", "打開爆款分析", "上傳參考影片", "看 Hook、節奏、CTA、爆點", "改寫成我方產品版本"]
  },
  {
    title: "我要找 KOL 做業配",
    steps: ["進入 KOL 工具", "貼 KOL 網址", "補過往業配影片或備註", "選擇指定產品", "產生 KOL 專屬腳本"]
  },
  {
    title: "我要確認 AI 設定",
    steps: ["進入設定", "確認 OpenAI、圖片模型、配音、影片供應商", "API Key 不要貼到公開文件", "生成失敗時先看錯誤訊息"]
  }
];

const tips = [
  "欄位下方的「影響 AI 判讀」代表這個欄位會進入 AI 分析，填得越清楚，生成內容越準。",
  "「部分影響」通常代表它會影響輸出格式、視覺構圖、配音或影片節奏，但不一定改變產品核心分析。",
  "「不影響 AI 判讀」通常是系統設定、顯示控制或備註資料，主要影響操作流程，不會改變 AI 對產品的理解。",
  "AI 產出的內容是初稿，不是最終投放結論。上線前仍需要行銷人員檢查品牌語氣、法規與產品事實。",
  "產品資料越完整，分析越準。至少建議提供產品介紹、售價、使用場景、競品資料與官網網址。",
  "素材不要只產一組。建議每次至少保留 3 個 Hook、3 種受眾角度、2 種 CTA 做測試。",
  "影片合成草稿主要用來確認節奏與腳本，不等於正式可投放素材。",
  "如果看到本機草稿，代表 AI API 暫時沒有成功回應，內容可先看，但建議修正 API 或重新生成。"
];

export default function HelpPage() {
  return (
    <div className="grid gap-6">
      <section className="grid gap-4 md:grid-cols-[1.2fr_0.8fr] md:items-end">
        <div>
          <div className="mb-3 flex items-center gap-2">
            <CircleHelp className="h-5 w-5 text-primary" />
            <Badge>新人快速上手</Badge>
          </div>
          <h1 className="text-2xl font-semibold tracking-normal">這套工具怎麼用？</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
            這是一套給行銷、廣告投手、品牌與電商團隊使用的素材生成與分析工具。你不用一開始就懂所有功能，照下面流程走就可以開始工作。
          </p>
        </div>
        <div className="flex flex-wrap gap-2 md:justify-end">
          <Button asChild>
            <Link href="/brands">
              <Building2 className="h-4 w-4" />
              從品牌開始
            </Link>
          </Button>
          <Button asChild variant="outline">
            <Link href="/projects/new">
              <Boxes className="h-4 w-4" />
              新增產品
            </Link>
          </Button>
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {quickSteps.map((step) => (
          <Card key={step.title}>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <step.icon className="h-4 w-4" />
                {step.title}
              </CardTitle>
              <CardDescription>{step.description}</CardDescription>
            </CardHeader>
            <CardContent>
              <Button asChild variant="outline" size="sm">
                <Link href={step.href}>
                  {step.action}
                  <ArrowRight className="h-4 w-4" />
                </Link>
              </Button>
            </CardContent>
          </Card>
        ))}
      </section>

      <section className="grid gap-4">
        <div>
          <h2 className="text-lg font-semibold">每個功能是幹嘛的</h2>
          <p className="mt-1 text-sm text-muted-foreground">你可以把它想成從品牌策略到素材執行的一條工作線。</p>
        </div>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {featureCards.map((feature) => (
            <Card key={feature.title}>
              <CardHeader>
                <div className="flex items-start justify-between gap-3">
                  <CardTitle>{feature.title}</CardTitle>
                  <Badge>{feature.badge}</Badge>
                </div>
                <CardDescription>{feature.description}</CardDescription>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-2">
                {feature.examples.map((item) => (
                  <Badge key={item}>{item}</Badge>
                ))}
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      <section className="grid gap-4">
        <div>
          <h2 className="text-lg font-semibold">常見工作情境</h2>
          <p className="mt-1 text-sm text-muted-foreground">不知道下一步要做什麼時，先找最接近你手上的任務。</p>
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          {dailyWorkflows.map((workflow) => (
            <Card key={workflow.title}>
              <CardHeader>
                <CardTitle>{workflow.title}</CardTitle>
              </CardHeader>
              <CardContent>
                <ol className="grid gap-2 text-sm leading-6">
                  {workflow.steps.map((step, index) => (
                    <li key={step} className="flex gap-3 rounded-md bg-muted/50 px-3 py-2">
                      <span className="font-semibold text-primary">{index + 1}</span>
                      <span>{step}</span>
                    </li>
                  ))}
                </ol>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-[0.8fr_1.2fr]">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Settings className="h-4 w-4" />
              如果功能不能用
            </CardTitle>
            <CardDescription>先從這幾件事檢查，通常最快。</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 text-sm leading-6">
            <p>1. 進入設定，確認 OpenAI API Key、ElevenLabs、影片供應商是否填好。</p>
            <p>2. 如果影片分析失敗，確認 FFmpeg 是否安裝，且 `FFMPEG_PATH` 是否正確。</p>
            <p>3. 如果畫面怪怪的，先重新整理頁面，或確認本機服務是否在 `127.0.0.1:3100`。</p>
            <Button asChild variant="outline" size="sm">
              <Link href="/settings">
                前往設定
                <ArrowRight className="h-4 w-4" />
              </Link>
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4" />
              使用注意事項
            </CardTitle>
            <CardDescription>這些是新人最容易忽略的地方。</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-2">
            {tips.map((tip) => (
              <div key={tip} className="rounded-md border bg-white p-3 text-sm leading-6">
                {tip}
              </div>
            ))}
          </CardContent>
        </Card>
      </section>

      <section className="rounded-lg border bg-primary px-5 py-4 text-primary-foreground">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div>
            <h2 className="font-semibold">最簡單的開始方式</h2>
            <p className="mt-1 text-sm opacity-90">如果你今天剛到職，先建立一個品牌，再新增一個產品專案，接著生成 5 組平面素材與 5 組影片腳本。</p>
          </div>
          <Button asChild variant="secondary">
            <Link href="/brands">
              開始建立品牌
              <ArrowRight className="h-4 w-4" />
            </Link>
          </Button>
        </div>
      </section>
    </div>
  );
}
