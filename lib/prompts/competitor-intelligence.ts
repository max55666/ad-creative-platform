export type CompetitorInput = {
  name: string;
  websiteUrl?: string | null;
  productUrl?: string | null;
  industry?: string | null;
  targetMarket?: string | null;
  description?: string | null;
  priceRange?: string | null;
  tags?: string[];
  brandContext?: unknown;
  projectContext?: unknown;
  scrapedPage?: {
    url: string;
    title?: string;
    text?: string;
    images?: unknown[];
    screenshotUrl?: string;
    error?: string;
  } | null;
};

export const competitorJsonInstruction =
  "只輸出有效 JSON，不要 Markdown，不要註解。若資料不足，請用 assumptions 說明推測依據，不要捏造不可驗證的數字。";

export function competitorIntelligencePrompt(input: CompetitorInput) {
  return `
你是資深競品情報與成效型廣告策略分析師。請根據競品資料、網站內容、品牌與產品背景，產生可供行銷團隊使用的競品分析。

輸入資料：
${JSON.stringify(input, null, 2)}

分析重點：
- 競品定位、產品主張、價格或方案訊號
- Landing Page 架構與說服方式
- 可能受眾、購買動機與購買疑慮
- 競品廣告可能會使用的 Hook、CTA、素材角度
- 我方可以避開或攻擊的空位
- 一鍵套用到我方產品時，可參考與不可照抄的部分

${competitorJsonInstruction}

JSON 格式：
{
  "summary": {
    "oneLine": "一句話描述競品",
    "category": "產品類別",
    "strengthLevel": "high | medium | low",
    "assumptions": ["資料不足與推測依據"]
  },
  "positioning": {
    "marketPosition": "市場定位",
    "mainClaims": ["主訴求"],
    "differentiators": ["差異化"],
    "brandTone": "品牌語氣",
    "visualStyle": "視覺風格"
  },
  "productOffer": {
    "products": ["主要產品或方案"],
    "priceSignals": "價格或促銷訊號",
    "proofPoints": ["證據點"],
    "frictions": ["購買阻力"]
  },
  "audience": {
    "likelyAudience": "可能主要受眾",
    "secondaryAudience": "可能次要受眾",
    "motivations": ["購買動機"],
    "barriers": ["購買疑慮"],
    "interestTags": ["廣告興趣標籤"]
  },
  "messaging": {
    "hooks": ["可能 Hook"],
    "ctaPatterns": ["CTA 模式"],
    "copyPatterns": ["文案套路"],
    "emotionalTriggers": ["情緒觸發"]
  },
  "landingPage": {
    "structure": ["頁面段落結構"],
    "aboveTheFold": "首屏訊息",
    "trustElements": ["信任元素"],
    "weaknesses": ["頁面弱點"]
  },
  "creativeAngles": [
    {
      "angle": "素材角度",
      "whyItWorks": "為什麼可能有效",
      "exampleHook": "可參考 Hook",
      "risk": "照抄風險"
    }
  ],
  "opportunities": {
    "whiteSpace": ["我方可切入空位"],
    "counterMessages": ["可反打訊息"],
    "testsToRun": ["建議測試"]
  },
  "risks": {
    "doNotCopy": ["不建議照抄"],
    "legalOrBrandRisks": ["法規或品牌風險"],
    "dataGaps": ["需要補資料"]
  },
  "nextSteps": ["下一步建議"]
}
`;
}
