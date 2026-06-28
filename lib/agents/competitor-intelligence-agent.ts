import { runJsonPrompt } from "@/lib/openai";
import { CompetitorInput, competitorIntelligencePrompt } from "@/lib/prompts/competitor-intelligence";

export type CompetitorAnalysisOutput = {
  summary: Record<string, unknown>;
  positioning: Record<string, unknown>;
  productOffer: Record<string, unknown>;
  audience: Record<string, unknown>;
  messaging: Record<string, unknown>;
  landingPage: Record<string, unknown>;
  creativeAngles: unknown[];
  opportunities: Record<string, unknown>;
  risks: Record<string, unknown>;
  nextSteps?: unknown[];
};

export async function runCompetitorIntelligenceAgent(input: CompetitorInput) {
  return runJsonPrompt<CompetitorAnalysisOutput>({
    prompt: competitorIntelligencePrompt(input),
    fallback: () => fallbackCompetitorAnalysis(input),
    temperature: 0.35
  });
}

function fallbackCompetitorAnalysis(input: CompetitorInput): CompetitorAnalysisOutput {
  const name = input.name || "競品";
  const category = input.industry || "待確認品類";
  const market = input.targetMarket || "目標市場待確認";

  return {
    summary: {
      oneLine: `${name} 是 ${category} 中可作為定位、素材角度與 Landing Page 結構參考的競品。`,
      category,
      strengthLevel: "medium",
      assumptions: ["目前使用本機草稿，請補充競品網址、商品頁或頁面截圖後重新分析。"]
    },
    positioning: {
      marketPosition: `${name} 可能主打 ${market} 中已有明確需求的消費者。`,
      mainClaims: ["解決明確痛點", "降低選擇成本", "提供可信賴的購買理由"],
      differentiators: ["需透過競品頁面與廣告案例進一步確認"],
      brandTone: "偏實用與銷售導向",
      visualStyle: "產品清楚、利益點明確、CTA 直接"
    },
    productOffer: {
      products: [input.description || "競品主力產品待補充"],
      priceSignals: input.priceRange || "尚未提供價格訊號",
      proofPoints: ["規格", "評價", "使用情境", "保固或優惠"],
      frictions: ["價格疑慮", "與替代品差異不明", "是否真的符合需求"]
    },
    audience: {
      likelyAudience: `${market} 中正在比較同類解決方案的消費者。`,
      secondaryAudience: "已被痛點觸發、但需要更多證據才下單的人。",
      motivations: ["省時間", "少踩雷", "提升效率或生活品質"],
      barriers: ["怕效果不符期待", "怕價格不值得", "不確定差異"],
      interestTags: ["網購", "生活風格", category, "評價比較"]
    },
    messaging: {
      hooks: ["你是不是也遇過這個問題？", "買之前先看這幾點", "用過才知道差在哪"],
      ctaPatterns: ["立即查看", "看更多評價", "領取優惠", "了解規格"],
      copyPatterns: ["痛點開場", "解法展示", "證據支撐", "低壓 CTA"],
      emotionalTriggers: ["怕踩雷", "想省時間", "想變得更安心"]
    },
    landingPage: {
      structure: ["首屏主張", "痛點描述", "產品解法", "證據與評價", "FAQ", "CTA"],
      aboveTheFold: "需要確認首屏是否清楚呈現產品、利益點與 CTA。",
      trustElements: ["評價", "媒體或認證", "保固", "退換貨承諾"],
      weaknesses: ["若證據不足，容易變成空泛銷售頁。"]
    },
    creativeAngles: [
      {
        angle: "痛點解法",
        whyItWorks: "能快速讓受眾自我對號入座。",
        exampleHook: "你是不是也被這個問題困擾很久？",
        risk: "不要照抄競品文案，應改成我方產品的真實場景。"
      },
      {
        angle: "比較避坑",
        whyItWorks: "適合攔截正在比較方案的人。",
        exampleHook: "買之前先看這三個差異。",
        risk: "避免直接攻擊競品或做無法驗證的比較。"
      }
    ],
    opportunities: {
      whiteSpace: ["用更具體的使用情境切入", "補強真實評價與證據", "做更清楚的規格比較"],
      counterMessages: ["不只便宜，更要適合", "不只功能多，而是更好理解"],
      testsToRun: ["痛點 Hook", "Before / After", "比較型素材", "評價見證素材"]
    },
    risks: {
      doNotCopy: ["競品品牌語氣", "競品視覺識別", "未驗證的數字宣稱"],
      legalOrBrandRisks: ["比較廣告需避免不實或貶低競品"],
      dataGaps: ["缺少競品頁面內容", "缺少實際廣告案例", "缺少價格與評價資料"]
    },
    nextSteps: ["補充競品商品頁", "上傳競品廣告案例", "把有效角度改寫成我方產品素材"]
  };
}
