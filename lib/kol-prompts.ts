export type KolVideoInput = {
  videoUrl?: string | null;
  fileUrl?: string | null;
  title?: string | null;
  sponsoredBrand?: string | null;
  sponsoredProduct?: string | null;
  notes?: string | null;
};

export type KolProductInput = {
  id?: string;
  productName?: string | null;
  productDescription?: string | null;
  productUrl?: string | null;
  targetMarket?: string | null;
  price?: string | null;
  specs?: string | null;
  mainUseCase?: string | null;
  competitors?: string | null;
};

export type KolAnalysisInput = {
  name: string;
  platform: string;
  profileUrl: string;
  description?: string | null;
  followerCount?: string | null;
  avgViews?: string | null;
  avgEngagement?: string | null;
  tags?: string[];
  videos?: KolVideoInput[];
  product?: KolProductInput | null;
};

export type KolScriptInput = KolAnalysisInput & {
  latestAnalysis?: unknown;
  objective?: string;
  duration?: string;
  platformTarget?: string;
  style?: string;
};

const jsonInstruction =
  "只輸出有效 JSON，不要 Markdown，不要註解。若資料不足，請用 assumptions 說明推測依據，不要捏造具體數據。";

export function kolAnalysisPrompt(input: KolAnalysisInput) {
  return `
你是資深 KOL 商務與成效型廣告策略顧問。請根據 KOL 網址、過往業配影片與指定產品資料，分析這位 KOL 的商業合作價值。

輸入資料：
${JSON.stringify(input, null, 2)}

分析重點：
- KOL 人設、語氣、內容風格、可信任感來源
- 粉絲輪廓、消費能力、興趣、可能痛點
- 過往業配影片常用結構、Hook、CTA、產品露出方式
- 適合合作的產品類型與不適合類型
- 若有指定產品，評估適配度、轉換潛力、風險與建議合作形式

${jsonInstruction}

JSON 格式：
{
  "kolSummary": {
    "oneLine": "一句話描述這位 KOL 的商業定位",
    "platformRole": "在平台上的角色",
    "commercialPotential": "high | medium | low",
    "assumptions": ["資料不足處與推測依據"]
  },
  "persona": {
    "personaTags": ["人設標籤"],
    "voiceTone": "說話語氣",
    "trustSource": "粉絲為什麼會相信他",
    "contentPromise": "粉絲追蹤他的主要期待",
    "redFlags": ["合作時要注意的形象風險"]
  },
  "contentStyle": {
    "formats": ["常見影片形式"],
    "visualStyle": "畫面風格",
    "editingPace": "剪輯節奏",
    "hookPatterns": ["常用 Hook"],
    "ctaPatterns": ["常用 CTA"],
    "brandIntegrationStyle": "商品通常如何自然置入"
  },
  "audienceProfile": {
    "primaryAudience": "主要粉絲輪廓",
    "secondaryAudience": "次要粉絲輪廓",
    "ageRange": "推測年齡層",
    "genderSkew": "性別傾向",
    "incomePower": "消費能力",
    "interests": ["興趣標籤"],
    "purchaseTriggers": ["會被什麼打動"],
    "purchaseBarriers": ["會猶豫什麼"]
  },
  "sponsoredVideoInsights": {
    "observedPatterns": ["從業配影片看出的模式"],
    "bestPerformingAngles": ["可能最適合的業配角度"],
    "weaknesses": ["業配內容可能弱點"],
    "recommendedDisclosureStyle": "業配揭露方式建議"
  },
  "suitableProducts": [
    {
      "category": "適合產品類型",
      "reason": "適合原因",
      "bestAngle": "建議主打角度"
    }
  ],
  "brandFit": {
    "bestBrandTypes": ["最適合品牌類型"],
    "avoidBrandTypes": ["不建議合作品牌類型"],
    "collaborationFormats": ["短影音業配 / 直播 / 團購 / 白名單投放等"]
  },
  "productFit": {
    "score": 0,
    "fitReasons": ["若有指定產品，說明適配原因"],
    "risks": ["轉換或形象風險"],
    "conversionPotential": "high | medium | low",
    "bestCollaborationFormat": "最推薦合作形式",
    "adWhitelistingPotential": "是否適合拿來投放廣告"
  },
  "riskAssessment": {
    "brandSafety": "品牌安全性",
    "messageMismatch": "人設與產品訊息落差",
    "creativeRisks": ["素材製作風險"],
    "mitigation": ["降低風險做法"]
  },
  "recommendations": [
    {
      "priority": "high | medium | low",
      "action": "下一步建議",
      "reason": "原因"
    }
  ]
}
`;
}

export function kolScriptPrompt(input: KolScriptInput) {
  return `
你是以轉換成效為核心的 KOL 短影音廣告編劇。請根據 KOL 人設、粉絲輪廓、過往業配風格與指定產品，產生 3 組可拍攝、可投放、可交給 KOL 的專屬業配腳本。

輸入資料：
${JSON.stringify(input, null, 2)}

要求：
- 腳本要像這位 KOL 會自然說出的內容，不要像品牌硬廣。
- 以轉換為主，但要保留 KOL 的可信任感。
- 每組都要包含 Hook、分鏡、字卡、口白、產品露出、CTA、投放注意事項。
- 若產品資料不足，先用可替換欄位標示，不要捏造不能驗證的數字。

${jsonInstruction}

JSON 格式：
{
  "scripts": [
    {
      "title": "腳本名稱",
      "platform": "TikTok / Reels / Shorts / Facebook",
      "objective": "轉換目標",
      "duration": "30秒",
      "hook": "前 3 秒 Hook",
      "storyline": [
        {
          "time": "0-3s",
          "purpose": "段落功能",
          "scene": "畫面內容",
          "kolAction": "KOL 動作與表情",
          "productPlacement": "產品如何露出",
          "conversionLogic": "這段如何推動轉換"
        }
      ],
      "shotList": [
        {
          "shot": "鏡號",
          "composition": "構圖",
          "cameraMovement": "鏡頭運動",
          "visualNotes": "拍攝細節",
          "props": ["道具"],
          "editingNotes": "剪輯提醒"
        }
      ],
      "captions": [
        {
          "time": "0-3s",
          "text": "字卡文字",
          "style": "字卡樣式"
        }
      ],
      "voiceover": [
        {
          "time": "0-3s",
          "text": "口白內容",
          "tone": "語調"
        }
      ],
      "cta": "CTA",
      "adUsageNotes": {
        "bestAudience": "適合投放受眾",
        "recommendedOffer": "建議促銷或轉換鉤子",
        "whitelistingNotes": "白名單投放注意事項",
        "variantsToTest": ["可 A/B test 的變體"]
      }
    }
  ]
}
`;
}
