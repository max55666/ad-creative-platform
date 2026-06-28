import type { KolAnalysisInput, KolScriptInput } from "@/lib/kol-prompts";

function kolName(input: KolAnalysisInput) {
  return input.name?.trim() || "這位 KOL";
}

function productName(input: KolAnalysisInput) {
  return input.product?.productName?.trim() || "指定產品";
}

export function fallbackKolAnalysis(input: KolAnalysisInput) {
  const name = kolName(input);
  const product = productName(input);
  const hasProduct = Boolean(input.product?.productName);

  return {
    kolSummary: {
      oneLine: `${name} 適合用「真實使用情境 + 個人觀點」包裝業配內容。`,
      platformRole: `${input.platform || "社群平台"} 上的內容型創作者`,
      commercialPotential: "medium",
      assumptions: ["目前僅根據使用者提供的網址、文字與影片備註推估，尚未串接平台公開數據抓取。"]
    },
    persona: {
      personaTags: input.tags?.length ? input.tags : ["生活型", "可親近", "實測分享"],
      voiceTone: "自然、口語、像朋友推薦，不適合過度品牌腔。",
      trustSource: "粉絲通常會相信 KOL 的日常經驗、踩雷提醒與實際使用前後差異。",
      contentPromise: "幫粉絲節省選擇成本，提供更直覺的購買判斷。",
      redFlags: ["避免誇大保證效果", "避免口吻突然變成硬性銷售"]
    },
    contentStyle: {
      formats: ["痛點開場", "情境示範", "開箱實測", "使用前後比較"],
      visualStyle: "以真人出鏡、近距離產品操作、日常場景為主。",
      editingPace: "前 3 秒快切抓注意力，中段用 2-3 個證據點支撐，結尾快速 CTA。",
      hookPatterns: ["你是不是也遇過...", "我本來不相信，結果...", "這個問題我終於找到解法"],
      ctaPatterns: ["我把連結放這裡", "先看規格再決定", "有需要可以先收藏"],
      brandIntegrationStyle: "先講生活問題，再讓產品作為自然解法出現。"
    },
    audienceProfile: {
      primaryAudience: "正在尋找實用解法、願意被真實體驗說服的粉絲。",
      secondaryAudience: "對同類產品有興趣但尚未決策、需要降低踩雷風險的人。",
      ageRange: "20-40",
      genderSkew: "依 KOL 類型調整，初步以中性或女性略高推估。",
      incomePower: "中等以上，會為便利、效率、質感或安心感付費。",
      interests: ["生活風格", "網購", "實測評價", "效率工具", "居家/美妝/3C 可依產品調整"],
      purchaseTriggers: ["真實使用差異", "明確痛點被說中", "限時優惠", "KOL 親身背書"],
      purchaseBarriers: ["怕業配不真實", "怕效果不如預期", "價格與替代品比較"]
    },
    sponsoredVideoInsights: {
      observedPatterns: input.videos?.length
        ? input.videos.map((video) => video.notes || video.title || video.videoUrl || "業配影片樣本")
        : ["尚未提供足夠過往業配影片，先以生活型 KOL 常見業配結構推估。"],
      bestPerformingAngles: ["痛點解法", "真實開箱", "前後對比", "踩雷避坑"],
      weaknesses: ["若只有產品功能介紹，轉換力會偏弱", "若缺少個人情境，容易像品牌素材"],
      recommendedDisclosureStyle: "一開始可自然揭露合作，但用『我實際試了...』降低業配距離感。"
    },
    suitableProducts: [
      { category: "高頻日常用品", reason: "容易放入真實生活情境", bestAngle: "每天都會遇到的小麻煩" },
      { category: "有明顯前後差異的產品", reason: "適合短影音快速展示價值", bestAngle: "Before / After" },
      { category: "需要信任背書的產品", reason: "KOL 個人經驗能降低購買疑慮", bestAngle: "實測與避坑" }
    ],
    brandFit: {
      bestBrandTypes: ["需要真人情境示範的品牌", "可用口碑降低疑慮的電商品牌", "有清楚使用場景的新產品"],
      avoidBrandTypes: ["高度醫療宣稱", "無法驗證效果但要求強力保證", "與 KOL 人設衝突的奢華硬廣"],
      collaborationFormats: ["短影音業配", "素材白名單投放", "團購導購", "開箱實測"]
    },
    productFit: {
      score: hasProduct ? 72 : 0,
      fitReasons: hasProduct
        ? [`${product} 可以透過 KOL 的日常情境與實測語氣降低陌生感。`, "若能提供具體使用前後差異，會更適合投放。"]
        : ["尚未指定產品，請選擇產品後再評估適配度。"],
      risks: hasProduct ? ["產品賣點若太抽象，腳本需要補強具體情境與證據。"] : ["缺少產品資訊。"],
      conversionPotential: hasProduct ? "medium" : "low",
      bestCollaborationFormat: hasProduct ? "30 秒情境實測短影音 + 白名單投放" : "先建立 KOL 屬性，再指定產品",
      adWhitelistingPotential: hasProduct ? "適合，但需產出 3-5 個 Hook 版本測試。" : "待產品確認後評估。"
    },
    riskAssessment: {
      brandSafety: "medium",
      messageMismatch: "需確認產品主張是否符合 KOL 平常語氣。",
      creativeRisks: ["口白太品牌化會降低信任", "CTA 太急可能造成粉絲反感"],
      mitigation: ["保留 KOL 第一人稱經驗", "用實測證據支撐賣點", "CTA 改成低壓力導購"]
    },
    recommendations: [
      { priority: "high", action: "先補 3-5 支過往業配影片連結與備註。", reason: "可更準確抓出 KOL 的真實腳本節奏。" },
      { priority: "high", action: "指定一個產品並生成 KOL 專屬腳本。", reason: "能直接評估轉換角度與投放可行性。" },
      { priority: "medium", action: "準備優惠、實測證據與 FAQ。", reason: "提高腳本可信度與廣告轉換率。" }
    ]
  };
}

export function fallbackKolScripts(input: KolScriptInput) {
  const name = kolName(input);
  const product = productName(input);
  const platform = input.platformTarget || input.platform || "TikTok / Reels / Shorts";
  const duration = input.duration || "30秒";

  return {
    scripts: [
      {
        title: `${name} 痛點實測導購腳本`,
        platform,
        objective: input.objective || "導購轉換",
        duration,
        hook: `你是不是也一直覺得 ${product} 這類東西很難選？我這次直接實測給你看。`,
        storyline: [
          {
            time: "0-3s",
            purpose: "痛點 Hook",
            scene: "KOL 面對鏡頭，手上拿著產品或問題情境道具。",
            kolAction: "皺眉、停頓一下，用像聊天的語氣說出粉絲常見困擾。",
            productPlacement: "產品先不要完整介紹，只露出局部。",
            conversionLogic: "先讓受眾覺得『這就是我的問題』。"
          },
          {
            time: "3-10s",
            purpose: "建立真實情境",
            scene: "展示沒有產品時的不便或選擇困難。",
            kolAction: "用第一人稱說明自己以前怎麼踩雷。",
            productPlacement: "產品出現在桌面或手邊，還不硬推。",
            conversionLogic: "降低業配感，建立個人經驗。"
          },
          {
            time: "10-22s",
            purpose: "產品成為解法",
            scene: "KOL 實際使用產品，展示 2-3 個最能感知的差異。",
            kolAction: "邊操作邊講感受，語氣保留真實限制。",
            productPlacement: "產品完整露出，搭配特寫。",
            conversionLogic: "用可見差異取代抽象賣點。"
          },
          {
            time: "22-30s",
            purpose: "低壓力 CTA",
            scene: "KOL 回到鏡頭前，給出適合與不適合的人。",
            kolAction: "用朋友推薦語氣收尾。",
            productPlacement: "畫面角落保留產品與優惠字卡。",
            conversionLogic: "降低被推銷感，提高點擊意願。"
          }
        ],
        shotList: [
          {
            shot: "1",
            composition: "中近景真人出鏡，字幕放下方安全區。",
            cameraMovement: "手持微晃或固定鏡頭，保留真實感。",
            visualNotes: "背景保持日常，不要太像棚拍。",
            props: ["產品", "日常使用道具"],
            editingNotes: "前 3 秒加快節奏，字卡要大。"
          },
          {
            shot: "2",
            composition: "產品特寫 + 手部操作。",
            cameraMovement: "輕微推近。",
            visualNotes: "拍出使用細節與前後差異。",
            props: ["產品包裝", "使用場景物件"],
            editingNotes: "每個賣點不超過 4 秒。"
          }
        ],
        captions: [
          { time: "0-3s", text: "這類產品真的很容易買錯", style: "大字卡，白字黑底或品牌色底" },
          { time: "10-22s", text: "我最有感的是這 3 點", style: "條列式重點字卡" },
          { time: "22-30s", text: "適合：想省時間、少踩雷的人", style: "清楚列出適合受眾" }
        ],
        voiceover: [
          { time: "0-3s", text: `你是不是也一直覺得 ${product} 這類東西很難選？`, tone: "像朋友吐槽，語速快" },
          { time: "3-10s", text: "我以前真的買過不適合的，所以這次我直接實測給你看。", tone: "真誠、降低業配感" },
          { time: "10-22s", text: "我最有感的是這幾個地方，第一個是...", tone: "具體、有證據感" },
          { time: "22-30s", text: "如果你也有同樣需求，可以先看我整理的連結和優惠。", tone: "低壓力 CTA" }
        ],
        cta: "點連結看規格與優惠，先確認適不適合你。",
        adUsageNotes: {
          bestAudience: "已看過同類產品、正在比較方案的中高意圖受眾。",
          recommendedOffer: "首購優惠、限時折扣、免運或組合包。",
          whitelistingNotes: "建議保留 KOL 名稱與真人開場，投放時測試痛點 Hook 與實測 Hook。",
          variantsToTest: ["痛點 Hook", "踩雷 Hook", "Before / After Hook"]
        }
      },
      {
        title: `${name} Before / After 轉換腳本`,
        platform,
        objective: input.objective || "導購轉換",
        duration,
        hook: `我用 ${product} 前後最大的差別，不是你以為的那個。`,
        storyline: [
          {
            time: "0-3s",
            purpose: "反直覺 Hook",
            scene: "畫面直接切 Before / After 對比。",
            kolAction: "用一句話挑戰既有認知。",
            productPlacement: "產品放在 After 畫面中自然出現。",
            conversionLogic: "用差異吸引停留。"
          },
          {
            time: "3-12s",
            purpose: "展示 Before 問題",
            scene: "重現粉絲常見困擾。",
            kolAction: "用自身經驗描述問題。",
            productPlacement: "暫時不講產品，先鋪痛點。",
            conversionLogic: "提高需求感。"
          },
          {
            time: "12-24s",
            purpose: "展示 After 與證據",
            scene: "產品使用流程與結果特寫。",
            kolAction: "說明自己最在意的判斷標準。",
            productPlacement: "產品包裝、功能、使用結果完整露出。",
            conversionLogic: "給出購買理由。"
          },
          {
            time: "24-30s",
            purpose: "適合誰 + CTA",
            scene: "列出適合族群。",
            kolAction: "提醒粉絲先確認需求。",
            productPlacement: "產品與優惠資訊同框。",
            conversionLogic: "讓受眾自我篩選並點擊。"
          }
        ],
        shotList: [
          {
            shot: "1",
            composition: "左右分割或上下對比畫面。",
            cameraMovement: "快速切換 Before 與 After。",
            visualNotes: "差異要一眼看懂。",
            props: ["Before 狀態道具", "產品", "After 結果"],
            editingNotes: "開場 1 秒內出現對比。"
          }
        ],
        captions: [
          { time: "0-3s", text: "前後差別最明顯的是這裡", style: "強對比字卡" },
          { time: "12-24s", text: "不是業配話術，我看這 3 點", style: "檢查清單字卡" }
        ],
        voiceover: [
          { time: "0-3s", text: `我用 ${product} 前後最大的差別，不是你以為的那個。`, tone: "帶懸念" },
          { time: "12-24s", text: "我自己會看這三件事，第一是...", tone: "理性分析" }
        ],
        cta: "我把適合的人、規格和優惠整理在連結裡。",
        adUsageNotes: {
          bestAudience: "對產品有需求但需要被證據說服的人。",
          recommendedOffer: "比較表、限時優惠、試用或保固。",
          whitelistingNotes: "適合做廣告冷受眾第一波測試。",
          variantsToTest: ["前後對比畫面", "KOL 反直覺開場", "適合/不適合名單"]
        }
      },
      {
        title: `${name} 避坑清單腳本`,
        platform,
        objective: input.objective || "導購轉換",
        duration,
        hook: `買 ${product} 之前，先確認你有沒有避開這幾個坑。`,
        storyline: [
          {
            time: "0-3s",
            purpose: "避坑 Hook",
            scene: "KOL 拿著產品與錯誤示範道具。",
            kolAction: "直接提醒粉絲不要急著買。",
            productPlacement: "產品以比較對象方式出現。",
            conversionLogic: "用保護粉絲的姿態建立信任。"
          },
          {
            time: "3-18s",
            purpose: "列出購買判斷標準",
            scene: "逐條展示 3 個挑選標準。",
            kolAction: "每點講一句自身經驗。",
            productPlacement: "用產品對應每個判斷標準。",
            conversionLogic: "把產品賣點轉成購買準則。"
          },
          {
            time: "18-30s",
            purpose: "產品推薦與 CTA",
            scene: "說明為什麼這次選它。",
            kolAction: "保留一點客觀限制，不過度誇張。",
            productPlacement: "產品完整露出，搭配連結字卡。",
            conversionLogic: "降低業配防備，導向點擊。"
          }
        ],
        shotList: [
          {
            shot: "1",
            composition: "KOL 直視鏡頭，中景。",
            cameraMovement: "固定鏡頭搭配快速 jump cut。",
            visualNotes: "用手勢比 1、2、3，讓節奏清楚。",
            props: ["產品", "比較清單", "錯誤示範道具"],
            editingNotes: "每個坑用不同字卡顏色標示。"
          }
        ],
        captions: [
          { time: "0-3s", text: "先不要急著買，避開這 3 個坑", style: "警示型字卡" },
          { time: "3-18s", text: "坑 1 / 坑 2 / 坑 3", style: "編號清單" }
        ],
        voiceover: [
          { time: "0-3s", text: `買 ${product} 之前，先確認你有沒有避開這幾個坑。`, tone: "提醒、保護粉絲" },
          { time: "18-30s", text: "我這次會選它，是因為它剛好避開我最在意的幾件事。", tone: "真實推薦" }
        ],
        cta: "需要比較表的人，我放在連結裡。",
        adUsageNotes: {
          bestAudience: "怕踩雷、會看評價才下單的人。",
          recommendedOffer: "比較表、FAQ、保固或退換貨承諾。",
          whitelistingNotes: "適合再行銷與高意圖受眾。",
          variantsToTest: ["三個坑", "三個挑選標準", "不適合誰"]
        }
      }
    ]
  };
}
