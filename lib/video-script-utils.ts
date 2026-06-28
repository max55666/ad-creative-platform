import type { ProductPromptInput } from "@/lib/prompts";

type ScriptMeta = {
  title?: string | null;
  platform?: string | null;
  duration?: string | null;
  style?: string | null;
};

export type SceneObject = {
  label?: string;
  referenceKey?: string;
  role?: string;
  reason?: string;
};

export type StoryboardShot = {
  time?: string;
  scene?: string;
  visual?: string;
  caption?: string;
  voiceover?: string;
  purpose?: string;
  subject?: string;
  action?: string;
  composition?: string;
  cameraMovement?: string;
  emotion?: string;
  setting?: string;
  lighting?: string;
  productPlacement?: string;
  props?: string[];
  safeArea?: string;
  sceneObjects?: SceneObject[];
  requiredReferenceKeys?: string[];
  imagePrompt?: string;
  motionPrompt?: string;
  jimengPrompt?: string;
  jimengPromptEn?: string;
  negativePrompt?: string;
  imageUrl?: string;
  imageSource?: string;
  imageLocked?: boolean;
  uploadedAt?: string;
};

export function productLabel(input: Pick<ProductPromptInput, "productName" | "productDescription">) {
  return input.productName || input.productDescription || "主商品";
}

export function normalizeVideoScriptForSave({
  project,
  script
}: {
  project: ProductPromptInput;
  script: any;
}) {
  const storyboard = Array.isArray(script.storyboard) ? script.storyboard : [];
  const normalizedStoryboard: StoryboardShot[] = storyboard.map((shot: StoryboardShot, index: number) =>
    normalizeStoryboardShot({ project, script, shot, index })
  );
  const captions = Array.isArray(script.captions)
    ? script.captions
    : normalizedStoryboard.map((shot) => shot.caption).filter(Boolean);
  const voiceover = Array.isArray(script.voiceover)
    ? script.voiceover
    : normalizedStoryboard.map((shot) => shot.voiceover).filter(Boolean);

  return {
    ...script,
    title: script.title || `${productLabel(project)} 短影音腳本`,
    platform: script.platform || "TikTok / Reels / Shorts",
    duration: script.duration || "30秒",
    style: script.style || "痛點",
    hook: script.hook || normalizedStoryboard[0]?.caption || "你是不是也遇過這個問題？",
    storyboard: normalizedStoryboard,
    captions,
    voiceover,
    props: Array.isArray(script.props) ? script.props : [],
    requiredObjects: normalizeRequiredObjects(script.requiredObjects, normalizedStoryboard, project),
    bgmSuggestion: script.bgmSuggestion || "節奏明快、前三秒有停頓與強拍的短影音音樂",
    tone: script.tone || "自然、可信、像真實使用者分享",
    cta: script.cta || "了解更多",
    targetAudience: script.targetAudience || project.targetMarket || "目標消費者"
  };
}

export function normalizeStoryboardShot({
  project,
  script,
  shot,
  index
}: {
  project: ProductPromptInput;
  script?: ScriptMeta;
  shot: StoryboardShot;
  index: number;
}): StoryboardShot {
  const product = productLabel(project);
  const time = shot.time || `${index * 5}-${(index + 1) * 5}s`;
  const purpose = shot.purpose || inferPurpose(index);
  const scene = shot.scene || shot.visual || `${product} 的短影音分鏡`;
  const visual = shot.visual || scene;
  const subject = shot.subject || "目標受眾在真實生活場景中自然使用產品";
  const action = shot.action || shot.voiceover || shot.caption || "展示產品如何解決問題";
  const composition = shot.composition || inferComposition(index);
  const cameraMovement = shot.cameraMovement || inferCameraMovement(index);
  const emotion = shot.emotion || inferEmotion(index);
  const setting = shot.setting || project.mainUseCase || "台灣日常生活場景";
  const lighting = shot.lighting || "自然光、乾淨、商業攝影質感";
  const productPlacement = shot.productPlacement || "主商品清楚露出，外觀必須與上傳產品圖一致";
  const safeArea = shot.safeArea || "保留上方與下方字幕安全區，不要讓主商品被字幕遮住";
  const negativePrompt = shot.negativePrompt || buildNegativePrompt();
  const sceneObjects = Array.isArray(shot.sceneObjects) && shot.sceneObjects.length
    ? shot.sceneObjects
    : inferSceneObjects(shot, project);
  const requiredReferenceKeys = Array.isArray(shot.requiredReferenceKeys) && shot.requiredReferenceKeys.length
    ? shot.requiredReferenceKeys
    : sceneObjects.map((item) => item.referenceKey).filter(Boolean) as string[];

  const normalized: StoryboardShot = {
    ...shot,
    time,
    scene,
    visual,
    purpose,
    subject,
    action,
    composition,
    cameraMovement,
    emotion,
    setting,
    lighting,
    productPlacement,
    safeArea,
    sceneObjects,
    requiredReferenceKeys,
    negativePrompt
  };

  normalized.imagePrompt = shot.imagePrompt || buildStoryboardImagePrompt({ project, script, shot: normalized, index });
  normalized.motionPrompt = shot.motionPrompt || buildMotionPrompt({ project, script, shot: normalized, index });
  normalized.jimengPrompt = shot.jimengPrompt || buildJimengPrompt({ project, script, shot: normalized, index });
  normalized.jimengPromptEn = shot.jimengPromptEn || buildJimengPromptEn({ project, script, shot: normalized, index });

  return normalized;
}

function normalizeRequiredObjects(requiredObjects: unknown, storyboard: StoryboardShot[], project: ProductPromptInput) {
  const items = new Map<string, SceneObject>();
  items.set("main_product", {
    label: project.productName || "主商品",
    referenceKey: "main_product",
    role: "product",
    reason: "所有素材都必須鎖定主商品外觀。"
  });

  if (Array.isArray(requiredObjects)) {
    for (const object of requiredObjects) {
      const item = typeof object === "string" ? { label: object, referenceKey: object } : object as SceneObject & { key?: string; name?: string; usage?: string };
      const key = normalizeObjectKey(item.referenceKey || item.key || item.name || item.label || "");
      if (!key) continue;
      items.set(key, {
        label: item.label || item.name || key,
        referenceKey: key,
        role: item.role || "reference",
        reason: item.reason || item.usage || "腳本中會出現，建議上傳參考圖避免生成跑掉。"
      });
    }
  }

  for (const shot of storyboard) {
    for (const object of shot.sceneObjects || []) {
      const key = normalizeObjectKey(object.referenceKey || object.label || "");
      if (!key || items.has(key)) continue;
      items.set(key, {
        label: object.label || key,
        referenceKey: key,
        role: object.role || "reference",
        reason: object.reason || shot.purpose || "分鏡中會出現，建議上傳參考圖。"
      });
    }
  }

  return Array.from(items.values());
}

export function buildStoryboardImagePrompt({
  project,
  script,
  shot,
  index
}: {
  project: ProductPromptInput;
  script?: ScriptMeta;
  shot: StoryboardShot;
  index: number;
}) {
  return [
    "Create one vertical 9:16 storyboard still for an ecommerce short video ad.",
    "Photorealistic commercial video still, modern Taiwan lifestyle, natural acting, clean composition.",
    "No readable text, no watermark, no random logo. Leave safe blank space for captions.",
    "Strict product/reference lock: preserve the uploaded main product and every referenced object. Do not replace them with generic substitutes.",
    `Product: ${productLabel(project)}.`,
    project.productDescription ? `Product description: ${project.productDescription}.` : "",
    project.price ? `Price: ${project.price}.` : "",
    project.targetMarket ? `Target market: ${project.targetMarket}.` : "",
    script?.title ? `Video title: ${script.title}.` : "",
    script?.style ? `Creative style: ${script.style}.` : "",
    `Shot ${index + 1}, time ${shot.time}.`,
    `Purpose: ${shot.purpose}.`,
    `Scene: ${shot.scene}.`,
    `Main subject: ${shot.subject}.`,
    `Scene objects that need reference consistency: ${formatSceneObjects(shot.sceneObjects)}.`,
    `Required reference keys: ${(shot.requiredReferenceKeys || []).join(", ")}.`,
    `Action: ${shot.action}.`,
    `Composition: ${shot.composition}.`,
    `Emotion: ${shot.emotion}.`,
    `Setting: ${shot.setting}.`,
    `Lighting: ${shot.lighting}.`,
    `Product placement: ${shot.productPlacement}.`,
    `Caption safe area: ${shot.safeArea}.`,
    `Avoid: ${shot.negativePrompt}.`
  ].filter(Boolean).join("\n");
}

export function buildMotionPrompt({
  project,
  script,
  shot,
  index
}: {
  project: ProductPromptInput;
  script?: ScriptMeta;
  shot: StoryboardShot;
  index: number;
}) {
  return [
    `Product video ad shot ${index + 1}.`,
    `Product: ${productLabel(project)}.`,
    script?.style ? `Ad style: ${script.style}.` : "",
    `Scene: ${shot.scene}.`,
    `Action: ${shot.action}.`,
    `Camera movement: ${shot.cameraMovement}.`,
    `Emotion: ${shot.emotion}.`,
    `Product placement: ${shot.productPlacement}.`,
    `Reference keys to preserve: ${(shot.requiredReferenceKeys || []).join(", ")}.`,
    "Create smooth realistic motion, keep product appearance consistent, avoid flicker and distorted hands.",
    "Do not generate readable subtitles or extra logos because captions will be added later."
  ].filter(Boolean).join("\n");
}

export function buildJimengPrompt({
  project,
  script,
  shot,
  index
}: {
  project: ProductPromptInput;
  script?: ScriptMeta;
  shot: StoryboardShot;
  index: number;
}) {
  return [
    "影片類型：電商短影音廣告",
    "畫面比例：9:16",
    "片段長度：5 秒",
    `分鏡：第 ${index + 1} 鏡，${shot.time}`,
    `主商品：${productLabel(project)}，必須與上傳產品參考圖一致`,
    `需要一致的參考物件：${formatSceneObjects(shot.sceneObjects)}`,
    script?.style ? `廣告風格：${script.style}` : "",
    `畫面目的：${shot.purpose}`,
    `畫面主體：${shot.subject}`,
    `場景：${shot.setting}`,
    `動作：${shot.action}`,
    `構圖：${shot.composition}`,
    `鏡頭：${shot.cameraMovement}`,
    `情緒：${shot.emotion}`,
    `燈光：${shot.lighting}`,
    `商品露出：${shot.productPlacement}`,
    `字幕安全區：${shot.safeArea}`,
    `避免：${shot.negativePrompt}`
  ].filter(Boolean).join("\n");
}

export function buildJimengPromptEn({
  project,
  script,
  shot,
  index
}: {
  project: ProductPromptInput;
  script?: ScriptMeta;
  shot: StoryboardShot;
  index: number;
}) {
  return [
    "Video type: ecommerce short-form ad.",
    "Aspect ratio: 9:16.",
    "Clip length: 5 seconds.",
    `Shot: ${index + 1}, ${shot.time}.`,
    `Product: ${productLabel(project)}. Preserve the uploaded product reference image exactly.`,
    `Reference objects to preserve: ${formatSceneObjects(shot.sceneObjects)}.`,
    script?.style ? `Ad style: ${script.style}.` : "",
    `Purpose: ${shot.purpose}.`,
    `Main subject: ${shot.subject}.`,
    `Setting: ${shot.setting}.`,
    `Action: ${shot.action}.`,
    `Composition: ${shot.composition}.`,
    `Camera movement: ${shot.cameraMovement}.`,
    `Emotion: ${shot.emotion}.`,
    `Lighting: ${shot.lighting}.`,
    `Product visibility: ${shot.productPlacement}.`,
    `Caption safe area: ${shot.safeArea}.`,
    `Avoid: ${shot.negativePrompt}.`
  ].filter(Boolean).join("\n");
}

export function buildNegativePrompt() {
  return "不要亂碼文字、不要額外 Logo、不要浮水印、不要產品外觀變形、不要把主商品換成不同產品、不要扭曲手指、不要不自然臉部、不要多餘肢體、不要錯誤透視、不要低解析模糊";
}

function inferSceneObjects(shot: StoryboardShot, project: ProductPromptInput): SceneObject[] {
  const text = [shot.scene, shot.visual, shot.subject, shot.action, shot.productPlacement].filter(Boolean).join(" ");
  const objects: SceneObject[] = [
    {
      label: project.productName || "主商品",
      referenceKey: "main_product",
      role: "product",
      reason: "主商品必須和上傳產品圖一致。"
    }
  ];
  const candidates = [
    { pattern: /貓|cat/i, label: "貓咪", key: "cat", role: "animal" },
    { pattern: /女性|女生|上班族|woman|female/i, label: "女性上班族", key: "female_office_worker", role: "person" },
    { pattern: /空氣清淨機|air purifier/i, label: "空氣清淨機", key: "air_purifier", role: "reference" },
    { pattern: /掃地機器人|掃地機|robot vacuum/i, label: "掃地機器人", key: "robot_vacuum", role: "reference" },
    { pattern: /餵食器|自動餵食|feeder/i, label: "寵物自動餵食器", key: "pet_feeder", role: "reference" }
  ];
  for (const candidate of candidates) {
    if (candidate.pattern.test(text)) {
      objects.push({
        label: candidate.label,
        referenceKey: candidate.key,
        role: candidate.role,
        reason: "分鏡畫面中會出現，建議上傳參考圖。"
      });
    }
  }
  return objects;
}

function inferPurpose(index: number) {
  return ["開場 Hook", "放大痛點", "產品解法", "效果證明", "CTA"][index] || "情節推進";
}

function inferComposition(index: number) {
  return ["主體置中、臉部與產品清楚露出", "中近景呈現困擾情境", "產品特寫與使用手勢", "Before / After 對比構圖", "產品與 CTA 留白構圖"][index] || "清楚呈現主體與商品";
}

function inferCameraMovement(index: number) {
  return ["快速推近到主體表情", "手持跟拍生活動作", "緩慢推近產品特寫", "左右對比切換", "穩定鏡頭收在產品"][index] || "自然短影音鏡頭";
}

function inferEmotion(index: number) {
  return ["困擾、好奇", "焦慮、想解決", "安心、理解", "信任、看到差異", "期待、想了解更多"][index] || "自然可信";
}

function formatSceneObjects(objects?: SceneObject[]) {
  if (!objects?.length) return "main_product";
  return objects.map((object) => `${object.label || object.referenceKey} (${object.referenceKey || "reference"})`).join(", ");
}

function normalizeObjectKey(value: string) {
  return value.trim().toLowerCase().replace(/[\s/\\]+/g, "_").replace(/[^a-z0-9_\-\u4e00-\u9fa5]+/g, "").slice(0, 64);
}
