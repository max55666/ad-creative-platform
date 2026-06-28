export function fallbackCrowdfundingCaseAnalysis(input: any) {
  const title = input.title || input.scrapedPage?.title || "嘖嘖募資案例";
  return {
    summary: {
      caseName: title,
      platform: input.platform || "zeczec",
      productCategory: "待確認品類",
      oneLinePositioning: "以明確痛點開場，透過情境、功能與信任元素推動贊助。",
      likelyAudience: "對此品類已有需求、但仍需要被說服的早鳥消費者。",
      mainPromise: "讓消費者用更簡單的方式解決日常問題。",
      assumptions: ["AI 目前使用本機草稿，建議補充完整案例頁內容後重新分析。"]
    },
    structure: {
      aboveTheFold: {
        headlineRole: "快速說明產品能解決什麼問題。",
        heroVisualType: "產品情境主視覺",
        ctaPlacement: "首屏與方案區重複出現",
        trustSignals: ["募資進度", "早鳥方案", "媒體或使用者背書"]
      },
      sectionOrder: [
        { order: 1, sectionName: "首屏承諾", purpose: "建立第一印象", keyMessage: "產品核心價值", imageType: "Hero 情境圖", ctaRole: "導向贊助" },
        { order: 2, sectionName: "痛點鋪陳", purpose: "讓讀者感覺這跟自己有關", keyMessage: "現有做法很麻煩", imageType: "Before 情境圖", ctaRole: "不急著成交" },
        { order: 3, sectionName: "解決方案", purpose: "介紹產品如何解決問題", keyMessage: "用產品帶來更好結果", imageType: "產品功能圖", ctaRole: "建立購買理由" },
        { order: 4, sectionName: "功能與規格", purpose: "降低疑慮", keyMessage: "功能、材質、尺寸、使用步驟", imageType: "資訊圖表", ctaRole: "推動方案區" },
        { order: 5, sectionName: "方案與 FAQ", purpose: "完成轉換", keyMessage: "早鳥優惠與常見問題", imageType: "方案圖卡", ctaRole: "強 CTA" }
      ],
      pageRhythm: "先情緒共鳴，再功能佐證，最後用方案與 FAQ 收斂。",
      mobileConsiderations: ["標題短", "圖中文字少", "CTA 區塊清楚"]
    },
    visualStrategy: {
      imageTypes: ["Hero 情境圖", "痛點圖", "產品功能圖", "使用步驟圖", "比較圖", "方案圖"],
      heroStyle: "產品清楚露出，搭配真實使用情境。",
      proofVisuals: ["規格表", "測試數據", "使用前後比較"],
      comparisonVisuals: ["傳統方式 vs 新方式"],
      lifestyleVisuals: ["家庭、辦公、日常使用場景"],
      designNotes: ["保留手機閱讀安全區", "每段只傳達一個重點"]
    },
    copywriting: {
      headlinePatterns: ["不是更複雜，而是更省事", "每天都會遇到的問題，終於有解法"],
      painPointPatterns: ["你是不是也遇過...", "麻煩不是偶爾，是每天都在發生"],
      proofPatterns: ["用步驟、數據、比較圖降低疑慮"],
      ctaPatterns: ["立即查看早鳥方案", "搶先支持計畫"],
      faqPatterns: ["配送、保固、規格、適用情境"]
    },
    conversionInsights: {
      whyItMayConvert: ["痛點清楚", "圖片有情境", "方案區明確"],
      trustBuilders: ["規格", "FAQ", "使用情境"],
      frictionReducers: ["比較圖", "保固說明", "退換貨說明"],
      riskPoints: ["若主商品露出不清楚，轉換會下降"],
      score: { total: 70, aboveTheFold: 70, clarity: 72, proof: 65, visualPersuasion: 68, cta: 70 }
    },
    reusableTemplate: {
      templateName: "痛點到解決方案型募資頁",
      bestFitProducts: ["生活用品", "寵物用品", "3C 小家電", "新奇工具"],
      pageBlueprint: ["首屏承諾", "痛點", "解決方案", "功能", "情境", "比較", "方案", "FAQ"],
      doNotCopy: ["不要照抄案例文案或品牌視覺"],
      adaptationRules: ["保留說服順序，改寫成自家產品的痛點、證據與情境"]
    },
    nextSteps: ["補上案例網址重新分析", "選擇此模板套用到我方產品"]
  };
}

export function fallbackCrowdfundingPagePlan(input: any) {
  const project = input.project || {};
  const productName = project.productName || "主商品";
  return {
    title: `${productName} 嘖嘖募資頁規劃`,
    strategy: {
      bigIdea: `把 ${productName} 變成一個容易理解、值得早鳥支持的日常解決方案。`,
      oneLinePromise: `用 ${productName} 解決消費者每天反覆遇到的麻煩。`,
      coreMessage: "先讓使用者感覺痛點真實，再用產品功能與情境圖建立信任。",
      targetAudience: project.targetMarket || "台灣早鳥消費者",
      positioning: "生活解決方案型募資頁",
      benchmarkLogic: input.caseAnalysis ? "套用對標案例的段落節奏，但改寫為我方產品。" : "從產品資料直接建立募資頁架構。"
    },
    hero: {
      headline: `${productName}，讓每天的小麻煩變簡單`,
      subHeadline: project.productDescription || "為日常使用情境設計的群眾募資新品。",
      visualDirection: "首屏使用真實情境圖，主商品放在畫面中心，旁邊呈現使用前後差異。",
      trustSignals: ["早鳥優惠", "產品規格", "使用情境"],
      cta: "立即查看早鳥方案"
    },
    pageSections: [
      {
        order: 1,
        sectionName: "首屏主承諾",
        purpose: "快速讓讀者知道產品解決什麼問題",
        headline: `${productName}，把麻煩留在昨天`,
        body: "用一句清楚承諾搭配產品主視覺，讓使用者在 3 秒內理解價值。",
        visualBrief: "產品清楚露出，搭配使用情境與簡短字卡。",
        imagePrompt: `Create a crowdfunding hero image for ${productName}, clear product focus, realistic lifestyle setting, premium ecommerce lighting, no extra logos.`,
        designNotes: "手機版首屏要看得到產品、主標與 CTA。",
        cta: "支持計畫"
      },
      {
        order: 2,
        sectionName: "痛點共鳴",
        purpose: "讓讀者覺得這是自己的問題",
        headline: "你是不是也常常遇到這些狀況？",
        body: "用 3 個具體日常情境描述麻煩，不要只講抽象缺點。",
        visualBrief: "Before 情境圖，呈現沒有產品時的困擾。",
        imagePrompt: `Show realistic before scenarios for ${productName}'s target users, clear pain point, documentary ecommerce style.`,
        designNotes: "每個痛點用一張圖卡，不要塞太多文字。",
        cta: ""
      },
      {
        order: 3,
        sectionName: "產品解決方案",
        purpose: "把產品定位成更好的做法",
        headline: `${productName} 的解法`,
        body: "說明產品如何把原本麻煩的流程變簡單。",
        visualBrief: "產品功能示意圖與使用步驟圖。",
        imagePrompt: `Product solution diagram for ${productName}, show 3 simple steps, clean crowdfunding page layout.`,
        designNotes: "步驟最多 3-4 個，避免讀者滑走。",
        cta: "看早鳥優惠"
      },
      {
        order: 4,
        sectionName: "功能與證據",
        purpose: "降低購買疑慮",
        headline: "不只好看，也真的好用",
        body: "整理規格、材質、尺寸、測試或比較，讓支持理由更具體。",
        visualBrief: "規格圖、比較表、細節特寫。",
        imagePrompt: `Detailed product feature infographic for ${productName}, clean labels, premium product closeups.`,
        designNotes: "規格資訊要清楚分層。",
        cta: ""
      },
      {
        order: 5,
        sectionName: "方案與 FAQ",
        purpose: "完成轉換",
        headline: "選擇最適合你的早鳥方案",
        body: "用簡單方案命名、優惠理由與 FAQ 降低最後疑慮。",
        visualBrief: "方案卡、配送與保固 FAQ 圖卡。",
        imagePrompt: `Crowdfunding reward tier cards for ${productName}, clean ecommerce layout, readable hierarchy.`,
        designNotes: "方案差異要一眼看懂。",
        cta: "立即支持"
      }
    ],
    imageBriefs: [
      {
        assetName: "首屏 Hero 圖",
        section: "首屏主承諾",
        priority: "high",
        ratio: "16:9",
        purpose: "建立第一印象",
        composition: "主商品置中，右側或下方放短標題。",
        mainCopy: `${productName}，讓每天的小麻煩變簡單`,
        subCopy: "限時早鳥募資中",
        referenceAssets: ["main_product"],
        prompt: `Hero image for ${productName}, preserve uploaded main product reference, realistic lifestyle crowdfunding visual.`,
        avoid: "不要改變產品外觀，不要生成錯誤 Logo"
      }
    ],
    copywriting: {
      openingStory: "從一個每天都會發生的小麻煩切入，讓讀者先點頭。",
      painPointCopy: "不是你不夠細心，而是現有工具本來就不夠順手。",
      solutionCopy: `${productName} 把流程變簡單，讓你少花時間處理重複問題。`,
      featureBullets: ["更直覺", "更省時", "更適合日常使用"],
      proofCopy: "用規格、使用步驟與比較圖證明價值。",
      socialProofCopy: "適合加入使用者評價、KOL 開箱或測試回饋。",
      closingCta: "現在支持，搶先用早鳥價格入手。"
    },
    rewardStrategy: {
      priceFraming: "先呈現早鳥省多少，再說明適合誰。",
      rewardTiers: [
        { name: "超早鳥單入組", angle: "最低入手門檻", copy: "適合第一次嘗試的支持者。" },
        { name: "雙入分享組", angle: "提升客單價", copy: "適合家庭或朋友一起使用。" }
      ],
      urgencyNotes: ["限量名額", "倒數時間", "募資限定優惠"]
    },
    faq: [
      { question: "什麼時候出貨？", answer: "請依實際生產排程填寫，建議說明預估月份與風險。" },
      { question: "有保固嗎？", answer: "請補上保固時間、適用範圍與客服方式。" }
    ],
    conversionScore: {
      label: "AI 預測，僅供參考",
      totalScore: 72,
      aboveTheFold: 72,
      clarity: 74,
      painPoint: 70,
      proof: 68,
      visualPersuasion: 72,
      rewardClarity: 70,
      cta: 74,
      strengths: ["架構完整", "痛點到解決方案清楚"],
      weaknesses: ["仍需補充真實規格與證據"],
      suggestions: ["補上產品細節圖", "補上比較表", "補上早鳥方案"]
    },
    executionPlan: {
      designPriority: ["首屏 Hero", "痛點圖", "功能圖", "方案圖"],
      copyPriority: ["首屏標題", "痛點段落", "方案文案"],
      testingIdeas: ["首屏標題 A/B", "痛點順序 A/B", "早鳥方案命名 A/B"]
    }
  };
}
