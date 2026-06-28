import { runJsonPrompt } from "@/lib/openai";
import { BrandBrainInput, brandBrainPrompt } from "@/lib/prompts/brand-brain";

export type BrandBrainOutput = {
  summary: Record<string, unknown>;
  positioning: Record<string, unknown>;
  voice: Record<string, unknown>;
  visualIdentity: Record<string, unknown>;
  audience: Record<string, unknown>;
  messaging: Record<string, unknown>;
  guardrails: Record<string, unknown>;
  nextSteps?: unknown[];
};

export async function runBrandBrainAgent(input: BrandBrainInput) {
  return runJsonPrompt<BrandBrainOutput>({
    prompt: brandBrainPrompt(input),
    fallback: () => fallbackBrandBrain(input),
    temperature: 0.35
  });
}

function fallbackBrandBrain(input: BrandBrainInput): BrandBrainOutput {
  const brand = input.name || "品牌";
  const industry = input.industry || "待確認品類";
  const targetMarket = input.targetMarket || "台灣市場";

  return {
    summary: {
      oneLine: `${brand} 是面向 ${targetMarket} 的 ${industry} 品牌，適合以清楚情境與可信證據建立購買信任。`,
      category: industry,
      brandPromise: "降低消費者選擇成本，提供更清楚、安心、容易理解的解決方案。",
      commercialRole: "作為所有產品分析、素材方向與 Campaign 訊息的一致品牌基準。",
      assumptions: ["目前使用本機草稿，請補充品牌官網、代表產品與過往素材後重新生成。"]
    },
    positioning: {
      marketPosition: input.description || `${brand} 應主打明確使用情境與可感知的產品價值。`,
      differentiators: ["清楚解決痛點", "降低購買疑慮", "可用真人情境與實測內容溝通"],
      competitorFrame: "與競品比較時，優先比較使用情境、信任證據、售後或體驗差異，不建議只比價格。",
      valueProposition: "用更直覺、更可信、更貼近日常的方式讓消費者理解產品價值。"
    },
    voice: {
      personality: ["可信", "清楚", "實用", "不過度誇張"],
      tone: input.voiceTone || "像專業但好懂的顧問，用生活化語氣說明價值。",
      copyRules: ["先講情境與痛點，再講產品", "避免空泛形容詞", "每個賣點都要對應一個使用場景"],
      preferredWords: ["實測", "適合", "幫你整理", "差異", "情境", "安心"],
      avoidWords: ["保證", "唯一", "最強", "永久", "零風險"]
    },
    visualIdentity: {
      styleKeywords: input.visualStyle ? [input.visualStyle] : ["乾淨", "生活感", "產品清楚", "高可讀性"],
      compositionRules: ["產品要在前三秒或首屏明確出現", "字卡不可遮住產品重點", "人物情緒要服務痛點"],
      colorDirection: "以品牌主色為重點，不讓背景色搶走商品注意力。",
      imageDos: ["產品使用情境", "Before / After", "真人手部操作", "清楚字卡"],
      imageDonts: ["過度抽象背景", "看不出產品的構圖", "字太小", "過度濾鏡"]
    },
    audience: {
      primary: `${targetMarket} 中正在比較解決方案、需要明確購買理由的消費者。`,
      secondary: "已對同類產品有興趣，但需要評價、證據或優惠推動決策的人。",
      motivations: ["省時間", "少踩雷", "提升生活品質", "解決明確痛點"],
      barriers: ["怕不符合期待", "怕價格不值得", "不確定與競品差異"],
      interestTags: ["網購", "生活風格", "實測評價", "效率工具", industry]
    },
    messaging: {
      coreMessage: `${brand} 幫你把複雜選擇變成清楚、安心、可行的解決方案。`,
      supportingMessages: ["用真實情境說明價值", "用證據降低疑慮", "用清楚 CTA 推動下一步"],
      proofPoints: ["產品規格", "使用前後差異", "評價見證", "實測畫面", "售後承諾"],
      platformAdaptation: {
        meta: "主打明確痛點、利益點與 CTA。",
        tiktok: "以前 3 秒 Hook 和真人情境降低廣告感。",
        reels: "用視覺差異與情緒轉折提升停留。",
        edm: "用清楚分段、優惠與 FAQ 推動點擊。",
        landingPage: "首屏先說明核心價值，接著用痛點、證據、FAQ 完成說服。"
      }
    },
    guardrails: {
      claimLimits: ["不得保證效果", "不得誇大無法驗證的數據", "不得使用絕對化醫療或財務宣稱"],
      brandSafety: ["避免攻擊競品", "避免製造過度焦慮", "避免與品牌形象不符的低俗梗"],
      creativeRisks: ["素材太像硬廣", "產品露出太晚", "字卡難讀", "CTA 不明確"],
      reviewChecklist: ["產品是否清楚", "主訴求是否一致", "CTA 是否明確", "是否符合品牌語氣", "是否有證據支撐"]
    },
    nextSteps: ["補充品牌官網與代表產品", "建立競品清單", "用 Brand Brain 重新生成素材方向"]
  };
}
