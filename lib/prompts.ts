export type ProductPromptInput = {
  productName: string;
  productDescription?: string | null;
  productUrl?: string | null;
  targetMarket?: string | null;
  price?: string | null;
  specs?: string | null;
  mainUseCase?: string | null;
  competitors?: string | null;
  urlContext?: string | null;
  brandContext?: unknown;
  assets?: Array<{
    type: string;
    fileUrl?: string | null;
    content?: string | null;
  }>;
};

export const jsonOnlyInstruction =
  "只輸出可解析的 JSON，不要 Markdown，不要說明文字，不要使用註解。若資料不足，請用合理假設並在 assumptions 欄位說明。";

export function productAnalysisPrompt(input: ProductPromptInput) {
  return `
你是資深電商品牌策略與廣告投放顧問。請根據產品資料輸出完整產品分析，格式必須是 JSON。

產品資料：
${JSON.stringify(input, null, 2)}

${jsonOnlyInstruction}

JSON 格式：
{
  "productSummary": {
    "oneLine": "一句話產品摘要",
    "category": "產品類別",
    "positioning": "市場定位",
    "keyFacts": ["重要事實"],
    "assumptions": ["資料不足時的推論"]
  },
  "targetAudience": {
    "primary": {
      "name": "主要受眾名稱",
      "ageRange": "年齡層",
      "genderSkew": "性別傾向",
      "incomePower": "消費能力",
      "useCases": ["使用情境"],
      "purchaseMotivations": ["購買動機"],
      "purchaseBarriers": ["購買疑慮"],
      "interestTags": ["興趣標籤"],
      "adTargetingTags": {
        "facebookInstagram": ["Meta 可用受眾標籤"],
        "tiktok": ["TikTok 可用受眾標籤"]
      }
    },
    "secondary": []
  },
  "painPoints": {
    "functional": ["功能痛點"],
    "emotional": ["情緒痛點"],
    "scenario": ["場景痛點"],
    "decisionBarriers": ["決策阻礙"]
  },
  "sellingPoints": {
    "core": ["核心賣點"],
    "functional": ["功能型賣點"],
    "emotional": ["情緒型賣點"],
    "scenario": ["場景型賣點"],
    "competitorDifferences": ["競品差異"],
    "mainClaims": ["可主打訴求"],
    "avoidClaims": ["不適合主打的訴求"]
  },
  "adAngles": [
    {
      "angle": "素材角度",
      "audience": "適合受眾",
      "message": "主要溝通訊息",
      "risk": "投放風險"
    }
  ],
  "nextSteps": ["下一步建議"]
}
`;
}

export function audienceAnalysisPrompt(input: ProductPromptInput) {
  return `
你是廣告投放受眾策略師。請根據產品資料拆解可投放受眾，格式必須是 JSON。

產品資料：
${JSON.stringify(input, null, 2)}

${jsonOnlyInstruction}

JSON 格式：
{
  "audienceSegments": [
    {
      "segmentName": "受眾名稱",
      "priority": "high | medium | low",
      "ageRange": "年齡層",
      "genderSkew": "性別傾向",
      "incomePower": "消費能力",
      "lifeContext": "生活狀態",
      "useCases": ["使用情境"],
      "purchaseMotivations": ["購買動機"],
      "purchaseBarriers": ["購買疑慮"],
      "interestTags": ["興趣標籤"],
      "facebookInstagramTags": ["Meta 受眾標籤"],
      "tiktokTags": ["TikTok 受眾標籤"],
      "bestAdMessage": "最適合溝通訊息"
    }
  ]
}
`;
}

export function staticCreativePrompt(context: unknown) {
  return `
你是電商廣告創意總監。請產生至少 5 組平面素材方向，格式必須是 JSON。

輸入資料：
${JSON.stringify(context, null, 2)}

${jsonOnlyInstruction}

JSON 格式：
{
  "suggestions": [
    {
      "title": "素材主題",
      "headline": "主標題",
      "subHeadline": "副標題",
      "visualDirection": "圖片構圖、人物、產品、場景、字卡位置",
      "copywriting": {
        "cardText": ["字卡 1", "字卡 2"],
        "body": "貼文或廣告內文",
        "proof": "佐證內容"
      },
      "cta": "CTA 文案",
      "platform": "Facebook / Instagram / TikTok / LINE / Google Display",
      "targetAudience": "適合受眾",
      "communication": "預期溝通重點"
    }
  ]
}
`;
}

export function videoScriptPrompt(context: unknown) {
  return `
你是資深短影音廣告導演、電商行銷策略師與 AI 影片提示詞工程師。
請根據產品資料產生至少 5 組可拍攝、可交給 AI 影片平台使用的短影音廣告腳本。

重要要求：
- 每組腳本需有清楚 Hook、分鏡、字卡、口白、道具、BGM、CTA。
- 每個分鏡都要足夠細，讓美術人員、OpenAI Images、即夢 AI、Kling 或 Runway 看得懂。
- 每個分鏡必須包含 imagePrompt、motionPrompt、jimengPrompt、jimengPromptEn、negativePrompt。
- jimengPrompt 請用中文條列，適合直接複製到即夢 AI 圖生影片。
- jimengPromptEn 請用英文，適合外部 AI 影片平台。
- 不要在圖像提示詞要求生成可讀中文字，字幕會由系統後製。
- 請避免醫療、功效、保證性誇大語句，除非產品資料有明確證據。

輸入資料：
${JSON.stringify(context, null, 2)}

${jsonOnlyInstruction}

JSON 格式：
{
  "scripts": [
    {
      "title": "影片主題",
      "platform": "TikTok / Reels / Shorts / Facebook",
      "duration": "15秒 / 30秒 / 60秒",
      "style": "搞笑 / 痛點 / 開箱 / 情境劇 / 專家推薦 / 素人分享",
      "hook": "開頭 3 秒 Hook",
      "storyboard": [
        {
          "time": "0-3s",
          "purpose": "停滑 Hook / 放大痛點 / 產品解法 / 效果證明 / CTA",
          "scene": "這一段發生什麼事",
          "visual": "畫面描述",
          "subject": "畫面主體，例如人物、產品、手部、場景",
          "action": "人物或產品正在做什麼",
          "composition": "構圖，例如近景、中景、俯拍、左右對比、產品置中",
          "cameraMovement": "鏡頭運動，例如輕微推近、手持感、平移、定鏡",
          "emotion": "情緒氛圍",
          "setting": "場景細節",
          "lighting": "光線風格",
          "productPlacement": "產品露出方式與位置",
          "caption": "本段字卡",
          "voiceover": "本段口白",
          "props": ["道具"],
          "safeArea": "字幕安全區與畫面留白",
          "imagePrompt": "給 AI 生分鏡圖的英文提示詞，不要可讀文字",
          "motionPrompt": "給圖生影片模型的英文動態提示詞",
          "jimengPrompt": "給即夢 AI 的中文圖生影片提示詞",
          "jimengPromptEn": "給外部 AI 影片平台的英文提示詞",
          "negativePrompt": "負面提示詞"
        }
      ],
      "captions": ["整支影片字卡"],
      "voiceover": ["整支影片口白"],
      "props": ["拍攝道具"],
      "bgmSuggestion": "背景音樂風格",
      "tone": "語調建議",
      "cta": "CTA",
      "targetAudience": "適合投放受眾"
    }
  ]
}
`;
}

export function viralVideoAnalysisPrompt(context: unknown) {
  return `
你是爆款短影音廣告分析師。請拆解上傳影片的結構、節奏、字卡、口白、產品露出與可複製模板，格式必須是 JSON。

輸入資料：
${JSON.stringify(context, null, 2)}

${jsonOnlyInstruction}

JSON 格式：
{
  "videoLength": "影片長度",
  "openingHook": "開頭 Hook",
  "segmentBreakdown": [
    {
      "time": "0-3s",
      "visual": "畫面",
      "caption": "字卡",
      "voiceover": "口白",
      "tone": "語調",
      "function": "段落功能",
      "pace": "節奏"
    }
  ],
  "structureAnalysis": {
    "framework": "腳本框架",
    "rhythm": "剪輯節奏",
    "productExposure": "產品露出方式",
    "ctaDesign": "CTA 設計"
  },
  "captionAnalysis": {
    "captionRole": "字卡功能",
    "copyPatterns": ["字卡句型"],
    "improvements": ["可優化處"]
  },
  "voiceAnalysis": {
    "voiceStyle": "口白風格",
    "scriptPatterns": ["口白句型"],
    "tone": "語氣"
  },
  "musicAnalysis": {
    "bgmType": "音樂類型",
    "beatStrategy": "節拍策略",
    "editingTempo": "剪輯速度"
  },
  "emotionAnalysis": {
    "painPoint": "痛點",
    "emotionalBuild": "情緒鋪陳",
    "desireTrigger": "慾望觸發"
  },
  "viralReason": {
    "hypotheses": ["可能爆紅原因"],
    "replicableElements": ["可複製元素"],
    "risks": ["套用風險"]
  },
  "reusableTemplate": {
    "templateName": "模板名稱",
    "steps": ["步驟"],
    "bestFitProducts": ["適合產品"],
    "fillInTheBlankScript": "可套用腳本"
  },
  "rewrittenScripts": [
    {
      "title": "改寫後腳本",
      "hook": "Hook",
      "storyboard": [],
      "cta": "CTA"
    }
  ]
}
`;
}

export function templateRewritePrompt(context: unknown) {
  return `
你是短影音廣告改寫顧問。請將爆款影片模板改寫成目前產品可用的腳本，格式必須是 JSON。

輸入資料：
${JSON.stringify(context, null, 2)}

${jsonOnlyInstruction}

JSON 格式：
{
  "rewrites": [
    {
      "title": "改寫腳本名稱",
      "targetAudience": "目標受眾",
      "duration": "15秒 / 30秒 / 60秒",
      "hook": "開頭 3 秒 Hook",
      "storyboard": [
        {
          "time": "0-3s",
          "visual": "畫面",
          "caption": "字卡",
          "voiceover": "口白",
          "purpose": "段落功能"
        }
      ],
      "cta": "CTA",
      "notes": ["執行注意事項"]
    }
  ]
}
`;
}
