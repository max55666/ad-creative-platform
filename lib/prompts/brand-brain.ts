export type BrandBrainInput = {
  name: string;
  websiteUrl?: string | null;
  industry?: string | null;
  targetMarket?: string | null;
  description?: string | null;
  voiceTone?: string | null;
  visualStyle?: string | null;
  products?: Array<{
    productName: string;
    productDescription?: string | null;
    targetMarket?: string | null;
    price?: string | null;
    mainUseCase?: string | null;
  }>;
};

export const brandBrainJsonInstruction =
  "只輸出有效 JSON，不要 Markdown，不要註解。若資料不足，請用 assumptions 說明推測依據，不要捏造不可驗證的數字。";

export function brandBrainPrompt(input: BrandBrainInput) {
  return `
你是資深品牌策略顧問與成效型廣告策略顧問。請根據品牌資料建立 Brand Brain，讓後續產品分析、廣告素材、KOL 腳本、Campaign Builder 都能維持一致品牌風格。

品牌資料：
${JSON.stringify(input, null, 2)}

請分析：
- 品牌一句話定位
- 品牌個性與語氣
- 視覺風格方向
- 主要受眾與購買動機
- 核心訊息與可長期複用的主張
- 廣告與內容製作時應避免的語氣、宣稱、視覺錯誤
- 可套用到 Meta / TikTok / Reels / EDM / Landing Page 的品牌規則

${brandBrainJsonInstruction}

JSON 格式：
{
  "summary": {
    "oneLine": "一句話描述品牌",
    "category": "品牌類別",
    "brandPromise": "品牌承諾",
    "commercialRole": "在廣告投放中的角色",
    "assumptions": ["資料不足處與推測依據"]
  },
  "positioning": {
    "marketPosition": "市場定位",
    "differentiators": ["差異化"],
    "competitorFrame": "與競品比較時的語境",
    "valueProposition": "核心價值主張"
  },
  "voice": {
    "personality": ["品牌個性標籤"],
    "tone": "語氣",
    "copyRules": ["文案規則"],
    "preferredWords": ["適合用字"],
    "avoidWords": ["避免用字"]
  },
  "visualIdentity": {
    "styleKeywords": ["視覺風格標籤"],
    "compositionRules": ["構圖規則"],
    "colorDirection": "色彩方向",
    "imageDos": ["應該拍什麼"],
    "imageDonts": ["避免什麼畫面"]
  },
  "audience": {
    "primary": "主要受眾",
    "secondary": "次要受眾",
    "motivations": ["購買動機"],
    "barriers": ["購買疑慮"],
    "interestTags": ["投放興趣標籤"]
  },
  "messaging": {
    "coreMessage": "核心訊息",
    "supportingMessages": ["輔助訊息"],
    "proofPoints": ["可支撐主張的證據"],
    "platformAdaptation": {
      "meta": "Meta 廣告訊息規則",
      "tiktok": "TikTok 訊息規則",
      "reels": "Reels 訊息規則",
      "edm": "EDM 訊息規則",
      "landingPage": "Landing Page 訊息規則"
    }
  },
  "guardrails": {
    "claimLimits": ["不能誇大的宣稱"],
    "brandSafety": ["品牌安全注意事項"],
    "creativeRisks": ["素材風險"],
    "reviewChecklist": ["素材產出前檢查清單"]
  },
  "nextSteps": ["下一步建議"]
}
`;
}
