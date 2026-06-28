import type { ProductPromptInput } from "@/lib/prompts";
import { normalizeVideoScriptForSave, productLabel } from "@/lib/video-script-utils";

export function fallbackProductAnalysis(input: ProductPromptInput) {
  const product = productLabel(input);

  return {
    productSummary: {
      oneLine: `${product} 的定位應聚焦在明確使用情境與可感知的解決方案。`,
      category: "待確認品類",
      positioning: input.targetMarket ? `面向 ${input.targetMarket} 的效率與體驗升級產品` : "面向高意圖消費者的生活解決方案",
      keyFacts: [
        input.productDescription || "目前產品介紹不足，建議補齊功能、規格與真實使用場景。",
        input.price ? `售價：${input.price}` : "售價尚未提供，需補齊價格帶與促銷策略。"
      ],
      assumptions: ["此為未連線 OpenAI 時的本機草稿分析。"]
    },
    targetAudience: {
      primary: {
        name: "重視效率與成果的主力消費者",
        ageRange: "25-44",
        genderSkew: "依產品品類調整",
        incomePower: "中等以上，願意為明確改善付費",
        useCases: [input.mainUseCase || "日常高頻使用場景", "送禮或自用升級", "問題明顯時的即時解決"],
        purchaseMotivations: ["降低麻煩", "節省時間", "提升生活品質"],
        purchaseBarriers: ["不知道是否真的有效", "擔心價格不值得", "缺少真實使用證明"],
        interestTags: ["網購", "生活風格", "實用好物", "開箱評測"],
        adTargetingTags: {
          facebookInstagram: ["Online shopping", "Engaged shoppers", "Lifestyle", "Home improvement"],
          tiktok: ["開箱", "生活好物", "實用推薦", "省時技巧"]
        }
      },
      secondary: [
        {
          name: "被內容種草的潛在消費者",
          ageRange: "18-34",
          genderSkew: "不限",
          incomePower: "中等",
          useCases: ["社群看到推薦", "促銷檔期下單", "送禮需求"],
          purchaseMotivations: ["新鮮感", "社交證明", "限時優惠"],
          purchaseBarriers: ["衝動後猶豫", "需要更多評價"],
          interestTags: ["短影音", "開箱", "優惠"],
          adTargetingTags: {
            facebookInstagram: ["Deals", "Shopping", "Video viewers"],
            tiktok: ["短影音購物", "開箱推薦", "生活技巧"]
          }
        }
      ]
    },
    painPoints: {
      functional: ["現有做法不夠方便", "需要花時間比較", "效果不穩定或難判斷"],
      emotional: ["怕買錯", "不想再踩雷", "希望快速找到適合自己的選擇"],
      scenario: [input.mainUseCase || "日常生活中需要更方便的解法", "送禮或升級需求出現時"],
      decisionBarriers: ["缺少真實使用證明", "價格合理性不足", "與競品差異不清楚"]
    },
    sellingPoints: {
      core: ["把抽象價值轉成可視化成果", "用情境展示產品如何解決痛點"],
      functional: ["使用流程更簡單", "降低決策成本", "適合高頻場景"],
      emotional: ["買得安心", "提升生活品質", "讓使用者覺得自己做了聰明選擇"],
      scenario: ["日常高頻場景", "送禮場景", "問題發生當下的解決場景"],
      competitorDifferences: [input.competitors ? `需對比競品：${input.competitors}` : "建議補齊競品資料後強化差異"],
      mainClaims: ["讓日常更方便", "用真實情境看懂差異", "適合想快速解決問題的人"],
      avoidClaims: ["沒有證據時避免保證效果", "避免過度誇大或絕對化用語"]
    },
    adAngles: [
      { angle: "痛點型", audience: "已意識到問題的高意圖受眾", message: "先放大日常不便，再給出產品解法", risk: "痛點不能過度恐嚇" },
      { angle: "Before / After", audience: "需要快速理解效果者", message: "用視覺對比降低理解成本", risk: "需避免誇大差異" },
      { angle: "使用場景型", audience: "尚未意識到需求者", message: "讓消費者先看見使用時機", risk: "場景需貼近真實生活" },
      { angle: "評價見證型", audience: "猶豫中的消費者", message: "用真實感與口碑降低不信任", risk: "避免假評價感" },
      { angle: "促銷型", audience: "價格敏感與臨門一腳受眾", message: "用優惠與保障推動行動", risk: "不要只靠折扣溝通" }
    ],
    nextSteps: ["補齊產品價格與賣點", "拍攝 3 個真實使用場景", "先測 5 組平面素材與 5 組短影音 Hook"]
  };
}

export function fallbackStaticCreatives(input: ProductPromptInput) {
  const product = productLabel(input);
  return {
    suggestions: [
      {
        title: "痛點型素材",
        headline: `你是不是也被「${product}」相關問題卡住？`,
        subHeadline: "把日常麻煩變成一個簡單解法",
        visualDirection: "左側放使用前的困擾表情，右側放產品使用後的清楚成果；產品置中偏右，字卡放上方 30%。",
        copywriting: {
          cardText: ["每天都遇到，卻一直忍著？", "一個步驟，把麻煩降到最低"],
          body: `用 ${product} 把高頻痛點變成可被立即理解的解法，適合用短句搭配真實場景圖。`,
          proof: "可加入真實評價、規格或保固資訊降低疑慮。"
        },
        cta: "立即看看解決方案",
        platform: "Facebook / Instagram",
        targetAudience: "已經感受到問題，正在找替代方案的消費者",
        communication: "放大痛點並快速帶出產品作為解方"
      },
      {
        title: "Before / After 素材",
        headline: "使用前後差異，一眼看懂",
        subHeadline: "不要只說好用，直接讓畫面說話",
        visualDirection: "使用 50/50 對比構圖，左邊保留真實瑕疵或困擾，右邊強調清楚、效率或安心。",
        copywriting: {
          cardText: ["Before：費時又不穩", "After：更快、更順、更安心"],
          body: "用前後對比降低理解成本，適合冷受眾第一波測試。",
          proof: "若有數據，可加入時間、步驟或滿意度差異。"
        },
        cta: "看更多使用差異",
        platform: "Instagram / TikTok 圖文 / Google Display",
        targetAudience: "需要視覺證明的冷受眾",
        communication: "可視化成果"
      }
    ]
  };
}

export function fallbackVideoScripts(input: ProductPromptInput) {
  const product = productLabel(input);
  const scripts = [
    {
      title: "痛點解決篇",
      platform: "TikTok / Reels / Shorts",
      duration: "30秒",
      style: "痛點",
      hook: "你是不是每天都遇到這個問題，卻一直忍著？",
      storyboard: [
        { time: "0-3s", scene: "主角在真實場景中露出困擾表情", visual: "人物近景，問題物件或情境清楚出現", caption: "每天都遇到，卻一直忍著？", voiceover: "你是不是也常常遇到這個問題？", purpose: "停滑 Hook" },
        { time: "3-8s", scene: "放大原本做法的麻煩", visual: "手忙腳亂、重複操作或找不到解法", caption: "越急越找不到", voiceover: "以前都用很繞的方式處理，真的很浪費時間。", purpose: "放大痛點" },
        { time: "8-18s", scene: `${product} 登場並解決問題`, visual: "產品操作特寫，讓觀眾看懂使用方式", caption: "換個方式，馬上順很多", voiceover: `後來用了 ${product}，流程變得簡單很多。`, purpose: "產品解法" },
        { time: "18-25s", scene: "展示使用後的差異", visual: "人物表情變輕鬆，成果明確呈現", caption: "差異一眼看懂", voiceover: "最有感的是，不用再一直卡在同一個問題。", purpose: "效果證明" },
        { time: "25-30s", scene: "產品主視覺與 CTA", visual: "乾淨產品畫面，保留字幕空間", caption: "點擊看完整資訊", voiceover: "有同樣需求，可以點進去看。", purpose: "CTA 轉換" }
      ],
      captions: ["每天都遇到，卻一直忍著？", "換個方式，馬上順很多", "點擊看完整資訊"],
      voiceover: ["你是不是也常常遇到這個問題？", `後來用了 ${product}，流程變得簡單很多。`, "有同樣需求，可以點進去看。"],
      props: ["產品本體", "日常使用道具", "手機或桌面小物"],
      bgmSuggestion: "前 3 秒有停滑感，中段節奏明快，結尾乾淨收束",
      tone: "真實、直接、有共鳴",
      cta: "點擊看完整資訊",
      targetAudience: "已經意識到問題的高意圖受眾"
    },
    {
      title: "開箱實測篇",
      platform: "Reels / Shorts / Facebook",
      duration: "30秒",
      style: "開箱",
      hook: `最近很多人問 ${product} 到底值不值得買，我直接實測。`,
      storyboard: [
        { time: "0-3s", scene: "桌面開箱，產品包裝入鏡", visual: "俯拍產品盒與手部拆封", caption: "真的值得買嗎？", voiceover: `今天直接實測 ${product}。`, purpose: "建立期待" },
        { time: "3-10s", scene: "展示重點規格與外觀", visual: "手持產品近拍，細節清楚", caption: "先看重點", voiceover: "先看做工、尺寸和實際使用方式。", purpose: "降低資訊不確定" },
        { time: "10-22s", scene: "真實場景使用", visual: "產品在情境中被使用，成果清楚", caption: "實測最有感的是...", voiceover: "我覺得最有感的是它把流程變簡單。", purpose: "展示體驗" },
        { time: "22-30s", scene: "總結適合誰", visual: "產品主圖搭配三點重點", caption: "適合：想省時 / 怕麻煩 / 重視品質", voiceover: "如果你也有同樣困擾，可以看商品頁。", purpose: "CTA 轉換" }
      ],
      captions: ["真的值得買嗎？", "實測最有感的是...", "適合：想省時 / 怕麻煩 / 重視品質"],
      voiceover: [`今天直接實測 ${product}。`, "我覺得最有感的是它把流程變簡單。", "可以看商品頁。"],
      props: ["產品包裝", "桌面", "實測場景道具"],
      bgmSuggestion: "清楚、輕快、像真實開箱評測",
      tone: "客觀、可信、像朋友分享",
      cta: "看商品頁完整資訊",
      targetAudience: "猶豫中的理性比較型受眾"
    }
  ].map((script) => normalizeVideoScriptForSave({ project: input, script }));

  return { scripts };
}

export function fallbackViralAnalysis(input: ProductPromptInput & { videoUrl?: string; transcript?: string }) {
  const product = productLabel(input);

  return {
    videoLength: "尚未取得精準長度，建議用 FFmpeg / ffprobe 補齊。",
    openingHook: "前 3 秒應使用高痛點畫面或反差句，快速讓目標受眾停下來。",
    segmentBreakdown: [
      { time: "0-3s", visual: "高痛點畫面或誇張反應", caption: "你是不是也遇過？", voiceover: "先丟出受眾熟悉的困擾。", tone: "快速、直接", function: "停滑 Hook", pace: "每 0.5-1 秒切一次" },
      { time: "3-8s", visual: "呈現 Before 狀態", caption: "以前：麻煩 / 慢 / 不穩", voiceover: "描述原本問題造成的成本。", tone: "共鳴", function: "放大痛點", pace: "快切細節" },
      { time: "8-18s", visual: "產品登場與實際操作", caption: product, voiceover: "用產品展示解法，不只講功能。", tone: "清楚、有信心", function: "建立解法", pace: "操作鏡頭保留 1-2 秒" },
      { time: "18-25s", visual: "成果或評價", caption: "差異一眼看懂", voiceover: "用前後差異或一句心得收斂。", tone: "肯定", function: "證明", pace: "節奏稍慢讓觀眾看懂" },
      { time: "25-30s", visual: "產品主圖與優惠/保障", caption: "點擊了解", voiceover: "給出低門檻下一步。", tone: "明確", function: "CTA", pace: "穩定收尾" }
    ],
    structureAnalysis: {
      framework: "痛點 Hook -> Before -> 產品解法 -> 成果證明 -> CTA",
      rhythm: "前段快、中段清楚展示、結尾穩定收斂",
      productExposure: "產品最好在 8 秒內第一次清楚露出",
      ctaDesign: "用低門檻 CTA，例如看更多、領優惠、查看規格"
    },
    captionAnalysis: {
      captionRole: "讓靜音觀看者也能理解痛點與成果",
      copyPatterns: ["你是不是也...", "以前都...", "後來換成...", "差異是..."],
      improvements: ["每段字卡控制在 12 字內", "避免塞太多資訊"]
    },
    voiceAnalysis: {
      voiceStyle: "像素人分享，可信度高於硬廣",
      scriptPatterns: ["問題句開頭", "個人經驗轉折", "低壓 CTA"],
      tone: "自然、真實、有節奏"
    },
    musicAnalysis: {
      bgmType: "輕快、節奏明確的短影音音樂",
      beatStrategy: "Hook 與轉場卡在重拍",
      editingTempo: "前 8 秒快切，展示段稍慢"
    },
    emotionAnalysis: {
      painPoint: "讓觀眾覺得這就是我",
      emotionalBuild: "困擾 -> 理解 -> 解法 -> 安心",
      desireTrigger: "省時、省麻煩、買得安心"
    },
    viralReason: {
      hypotheses: ["痛點夠生活化", "前 3 秒有反差", "產品解法清楚"],
      replicableElements: ["痛點句型", "Before / After", "素人口吻"],
      risks: ["過度演出會降低信任", "產品露出太晚會影響轉換"]
    },
    reusableTemplate: {
      templateName: "痛點解決短影音模板",
      steps: ["提出痛點", "放大原本麻煩", "產品登場", "展示結果", "CTA"],
      bestFitProducts: ["高頻使用產品", "生活解決方案", "功能差異可視化產品"],
      fillInTheBlankScript: `你是不是也常遇到［痛點］？以前我都［舊做法］，後來用了 ${product}，才發現可以［成果］。`
    },
    rewrittenScripts: [
      {
        title: `${product} 痛點解決篇`,
        hook: "你是不是也每天被這個小問題卡住？",
        storyboard: [
          { time: "0-3s", visual: "痛點特寫", caption: "每天都遇到？", voiceover: "你是不是也常常遇到這個？", purpose: "停滑" },
          { time: "3-10s", visual: "Before 狀態", caption: "以前真的很麻煩", voiceover: "以前我都用很繞的方式處理。", purpose: "共鳴" },
          { time: "10-22s", visual: "產品操作與成果", caption: product, voiceover: "後來改用這個，流程簡單很多。", purpose: "展示" },
          { time: "22-30s", visual: "產品主圖與 CTA", caption: "點擊看完整資訊", voiceover: "有同樣需求可以點進去看。", purpose: "轉換" }
        ],
        cta: "點擊看完整資訊"
      }
    ]
  };
}
