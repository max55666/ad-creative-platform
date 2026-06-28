export type CrowdfundingCasePromptInput = {
  sourceUrl?: string | null;
  platform?: string;
  title?: string | null;
  notes?: string | null;
  project?: unknown;
  latestAnalysis?: unknown;
  scrapedPage?: {
    url: string;
    title?: string;
    text?: string;
    images?: unknown[];
    screenshotUrl?: string;
    error?: string;
  } | null;
};

export type CrowdfundingPagePromptInput = {
  mode: "from_product" | "benchmark_case" | "hybrid";
  targetPlatform: "zeczec" | "generic";
  objective?: string | null;
  tone?: string | null;
  project: unknown;
  latestAnalysis?: unknown;
  caseAnalysis?: unknown;
};

const jsonInstruction = "只輸出有效 JSON，不要 Markdown，不要程式碼區塊。若資料不足，請在 assumptions 或 dataGaps 中說明。";

export function crowdfundingCaseAnalysisPrompt(input: CrowdfundingCasePromptInput) {
  return `
你是台灣群眾募資頁面策略顧問，熟悉嘖嘖募資頁、電商轉換頁與廣告素材企劃。
請拆解輸入的募資案例頁面，重點不是摘要，而是找出可複製的頁面架構、說服順序、圖片策略與轉換設計。

輸入資料：
${JSON.stringify(input, null, 2)}

${jsonInstruction}

請輸出以下 JSON：
{
  "summary": {
    "caseName": "案例名稱",
    "platform": "zeczec",
    "productCategory": "產品類別",
    "oneLinePositioning": "一句話定位",
    "likelyAudience": "可能受眾",
    "mainPromise": "主承諾",
    "assumptions": ["資料不足時的推論"]
  },
  "structure": {
    "aboveTheFold": {
      "headlineRole": "首屏標題扮演的角色",
      "heroVisualType": "首屏主視覺類型",
      "ctaPlacement": "CTA 位置與目的",
      "trustSignals": ["首屏信任元素"]
    },
    "sectionOrder": [
      {
        "order": 1,
        "sectionName": "段落名稱",
        "purpose": "這段在說服流程中的功能",
        "keyMessage": "主要訊息",
        "imageType": "圖片或影片類型",
        "ctaRole": "這段是否推動 CTA"
      }
    ],
    "pageRhythm": "頁面節奏與情緒推進",
    "mobileConsiderations": ["手機版注意事項"]
  },
  "visualStrategy": {
    "imageTypes": ["使用的圖片類型"],
    "heroStyle": "主視覺風格",
    "proofVisuals": ["證明型圖片或圖表"],
    "comparisonVisuals": ["比較型圖片"],
    "lifestyleVisuals": ["情境圖"],
    "designNotes": ["設計特徵"]
  },
  "copywriting": {
    "headlinePatterns": ["標題公式"],
    "painPointPatterns": ["痛點鋪陳方式"],
    "proofPatterns": ["佐證說法"],
    "ctaPatterns": ["CTA 寫法"],
    "faqPatterns": ["FAQ 常見處理方式"]
  },
  "conversionInsights": {
    "whyItMayConvert": ["可能有效原因"],
    "trustBuilders": ["信任建立元素"],
    "frictionReducers": ["降低疑慮設計"],
    "riskPoints": ["可能弱點"],
    "score": {
      "total": 0,
      "aboveTheFold": 0,
      "clarity": 0,
      "proof": 0,
      "visualPersuasion": 0,
      "cta": 0
    }
  },
  "reusableTemplate": {
    "templateName": "可複製模板名稱",
    "bestFitProducts": ["適合套用的產品類型"],
    "pageBlueprint": ["可複製段落架構"],
    "doNotCopy": ["不建議照抄的地方"],
    "adaptationRules": ["套用到其他產品時的改寫規則"]
  },
  "nextSteps": ["下一步建議"]
}
`;
}

export function crowdfundingPagePlanPrompt(input: CrowdfundingPagePromptInput) {
  return `
你是群眾募資頁企劃總監。請根據我方產品資料與可選的對標案例，產生一份可交給文案、設計、美術與網頁工程師執行的募資頁規劃。

重要要求：
- 目標平台以嘖嘖募資頁為主。
- 不要只寫摘要，要輸出完整頁面架構。
- 每個頁面段落都要說明目的、文案、圖片需求與 CTA。
- 圖片需求要能銜接 AI 生圖或設計師製圖。
- 若有對標案例，保留其說服邏輯與頁面節奏，但文案必須改成我方產品，不可照抄。
- 請加入 AI 預測評分，並標示這只是預測。

輸入資料：
${JSON.stringify(input, null, 2)}

${jsonInstruction}

請輸出以下 JSON：
{
  "title": "募資頁企劃名稱",
  "strategy": {
    "bigIdea": "Campaign Big Idea",
    "oneLinePromise": "一句話承諾",
    "coreMessage": "核心訊息",
    "targetAudience": "主要受眾",
    "positioning": "頁面定位",
    "benchmarkLogic": "若有對標案例，說明套用了什麼邏輯"
  },
  "hero": {
    "headline": "首屏主標",
    "subHeadline": "首屏副標",
    "visualDirection": "首屏主視覺構圖",
    "trustSignals": ["首屏信任元素"],
    "cta": "首屏 CTA"
  },
  "pageSections": [
    {
      "order": 1,
      "sectionName": "段落名稱",
      "purpose": "這段的說服目的",
      "headline": "段落標題",
      "body": "段落文案",
      "visualBrief": "圖片/影片需求",
      "imagePrompt": "給 AI 生圖或美術參考的提示詞",
      "designNotes": "設計與手機版注意事項",
      "cta": "本段 CTA 或空字串"
    }
  ],
  "imageBriefs": [
    {
      "assetName": "圖片名稱",
      "section": "對應段落",
      "priority": "high | medium | low",
      "ratio": "16:9 | 4:5 | 1:1 | long-page",
      "purpose": "圖片用途",
      "composition": "構圖說明",
      "mainCopy": "圖上主文案",
      "subCopy": "圖上副文案",
      "referenceAssets": ["需要參考的產品圖或物件"],
      "prompt": "AI 生圖提示詞",
      "avoid": "不要出現什麼"
    }
  ],
  "copywriting": {
    "openingStory": "開場故事",
    "painPointCopy": "痛點文案",
    "solutionCopy": "解決方案文案",
    "featureBullets": ["功能賣點"],
    "proofCopy": "佐證文案",
    "socialProofCopy": "見證/評價文案",
    "closingCta": "結尾 CTA"
  },
  "rewardStrategy": {
    "priceFraming": "價格與早鳥方案呈現方式",
    "rewardTiers": [
      {
        "name": "方案名稱",
        "angle": "方案訴求",
        "copy": "方案文案"
      }
    ],
    "urgencyNotes": ["限時或限量設計"]
  },
  "faq": [
    {
      "question": "FAQ 問題",
      "answer": "FAQ 回答"
    }
  ],
  "conversionScore": {
    "label": "AI 預測，僅供參考",
    "totalScore": 0,
    "aboveTheFold": 0,
    "clarity": 0,
    "painPoint": 0,
    "proof": 0,
    "visualPersuasion": 0,
    "rewardClarity": 0,
    "cta": 0,
    "strengths": ["優點"],
    "weaknesses": ["缺點"],
    "suggestions": ["修改建議"]
  },
  "executionPlan": {
    "designPriority": ["先做哪些圖"],
    "copyPriority": ["先寫哪些文案"],
    "testingIdeas": ["可 A/B 測試項目"]
  }
}
`;
}
