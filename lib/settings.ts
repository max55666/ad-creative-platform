import { mkdir, readFile, writeFile } from "fs/promises";
import path from "path";

export type SystemSettings = {
  providers: {
    text: {
      provider: "openai";
      model: string;
      temperature: number;
      fallbackToLocalDraft: boolean;
    };
    image: {
      provider: "openai";
      model: string;
      quality: "low" | "medium" | "high" | "auto";
      defaultAspectRatio: "1:1" | "4:5" | "9:16";
    };
    transcription: {
      provider: "openai";
      model: string;
    };
    voiceover: {
      provider: "elevenlabs";
      model: string;
      defaultLanguage: "zh" | "ja" | "en";
      defaultGender: "female" | "male";
      femaleVoiceId: string;
      maleVoiceId: string;
    };
    video: {
      provider: "kling" | "jimeng_manual" | "runway" | "veo" | "heygen" | "fal";
      model: string;
      defaultMode: "static" | "ai-motion";
      motionStyle: "subtle" | "product-demo" | "scene-action" | "dramatic";
      clipDurationSec: number;
      pollIntervalMs: number;
      timeoutMs: number;
      klingMode: string;
      klingCfgScale: number;
    };
  };
  workflow: {
    autoGenerateStoryboard: boolean;
    autoGenerateVoiceover: boolean;
    keepUploadedStoryboardLocked: boolean;
    allowExternalVideoUpload: boolean;
    generateJimengPrompts: boolean;
    showCostEstimate: boolean;
    maxStoryboardFrames: number;
  };
  output: {
    defaultAspectRatio: "1:1" | "4:5" | "9:16";
    subtitleStyle: "default" | "bold" | "clean" | "bottom-heavy";
    secondsPerImage: number;
  };
  externalPlatforms: {
    jimeng: {
      enabled: boolean;
      defaultPromptLanguage: "zh" | "en" | "both";
      notes: string;
    };
    runway: { enabled: boolean; notes: string };
    veo: { enabled: boolean; notes: string };
    kling: { enabled: boolean; notes: string };
  };
};

const settingsPath = path.join(process.cwd(), "work", "system-settings.json");

export const settingsOptions = {
  textModels: ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1", "gpt-5.5"],
  imageModels: ["gpt-image-1"],
  transcriptionModels: ["gpt-4o-mini-transcribe", "gpt-4o-transcribe", "whisper-1"],
  voiceModels: ["eleven_multilingual_v2", "eleven_turbo_v2_5"],
  videoProviders: ["kling", "jimeng_manual", "runway", "veo", "heygen", "fal"],
  videoModels: ["kling-v1-6", "kling-v2", "jimeng-manual", "runway-gen3", "veo-3", "heygen-v3", "fal-video"],
  aspectRatios: ["9:16", "4:5", "1:1"],
  subtitleStyles: ["default", "bold", "clean", "bottom-heavy"]
} as const;

export const defaultSystemSettings: SystemSettings = {
  providers: {
    text: {
      provider: "openai",
      model: process.env.OPENAI_MODEL || "gpt-4o-mini",
      temperature: 0.4,
      fallbackToLocalDraft: true
    },
    image: {
      provider: "openai",
      model: process.env.OPENAI_IMAGE_MODEL || "gpt-image-1",
      quality: "medium",
      defaultAspectRatio: "9:16"
    },
    transcription: {
      provider: "openai",
      model: process.env.OPENAI_TRANSCRIBE_MODEL || "gpt-4o-mini-transcribe"
    },
    voiceover: {
      provider: "elevenlabs",
      model: process.env.ELEVENLABS_MODEL || "eleven_multilingual_v2",
      defaultLanguage: "zh",
      defaultGender: "female",
      femaleVoiceId: process.env.ELEVENLABS_VOICE_ID_FEMALE || "",
      maleVoiceId: process.env.ELEVENLABS_VOICE_ID_MALE || ""
    },
    video: {
      provider: safeOption(process.env.VIDEO_PROVIDER, settingsOptions.videoProviders, "kling"),
      model: process.env.KLING_MODEL || "kling-v1-6",
      defaultMode: "ai-motion",
      motionStyle: "subtle",
      clipDurationSec: 5,
      pollIntervalMs: Number(process.env.KLING_POLL_INTERVAL_MS || 8000),
      timeoutMs: Number(process.env.KLING_TIMEOUT_MS || 10 * 60 * 1000),
      klingMode: process.env.KLING_MODE || "std",
      klingCfgScale: Number(process.env.KLING_CFG_SCALE || 0.5)
    }
  },
  workflow: {
    autoGenerateStoryboard: true,
    autoGenerateVoiceover: true,
    keepUploadedStoryboardLocked: true,
    allowExternalVideoUpload: true,
    generateJimengPrompts: true,
    showCostEstimate: true,
    maxStoryboardFrames: 5
  },
  output: {
    defaultAspectRatio: "9:16",
    subtitleStyle: "default",
    secondsPerImage: 3
  },
  externalPlatforms: {
    jimeng: {
      enabled: true,
      defaultPromptLanguage: "both",
      notes: "先用半自動流程：複製系統產生的提示詞到即夢，生成圖片或影片後再上傳回系統合成。"
    },
    runway: { enabled: false, notes: "預留 Runway API 串接接口。" },
    veo: { enabled: false, notes: "預留 Google Veo API 串接接口。" },
    kling: { enabled: true, notes: "目前已支援 Kling 圖生影片。" }
  }
};

export async function getSystemSettings(): Promise<SystemSettings> {
  try {
    const raw = await readFile(settingsPath, "utf8");
    return sanitizeSettings(mergeSettings(defaultSystemSettings, JSON.parse(raw)));
  } catch {
    return defaultSystemSettings;
  }
}

export async function saveSystemSettings(settings: Partial<SystemSettings>) {
  const current = await getSystemSettings();
  const next = sanitizeSettings(mergeSettings(current, settings));
  await mkdir(path.dirname(settingsPath), { recursive: true });
  await writeFile(settingsPath, JSON.stringify(next, null, 2), "utf8");
  return next;
}

export function mergeSettings<T>(base: T, override: any): T {
  if (!override || typeof override !== "object" || Array.isArray(override)) return base;
  const result: any = { ...(base as any) };
  for (const [key, value] of Object.entries(override)) {
    if (!(key in result)) continue;
    if (value && typeof value === "object" && !Array.isArray(value) && result[key] && typeof result[key] === "object") {
      result[key] = mergeSettings(result[key], value);
    } else {
      result[key] = value;
    }
  }
  return result;
}

function sanitizeSettings(settings: SystemSettings): SystemSettings {
  return {
    ...settings,
    providers: {
      ...settings.providers,
      text: {
        ...settings.providers.text,
        provider: "openai",
        model: nonEmpty(settings.providers.text.model, defaultSystemSettings.providers.text.model),
        temperature: clampNumber(settings.providers.text.temperature, 0, 2, 0.4),
        fallbackToLocalDraft: Boolean(settings.providers.text.fallbackToLocalDraft)
      },
      image: {
        ...settings.providers.image,
        provider: "openai",
        model: nonEmpty(settings.providers.image.model, defaultSystemSettings.providers.image.model),
        quality: safeOption(settings.providers.image.quality, ["low", "medium", "high", "auto"] as const, "medium"),
        defaultAspectRatio: safeOption(settings.providers.image.defaultAspectRatio, settingsOptions.aspectRatios, "9:16")
      },
      transcription: {
        provider: "openai",
        model: nonEmpty(settings.providers.transcription.model, defaultSystemSettings.providers.transcription.model)
      },
      voiceover: {
        ...settings.providers.voiceover,
        provider: "elevenlabs",
        model: nonEmpty(settings.providers.voiceover.model, defaultSystemSettings.providers.voiceover.model),
        defaultLanguage: safeOption(settings.providers.voiceover.defaultLanguage, ["zh", "ja", "en"] as const, "zh"),
        defaultGender: safeOption(settings.providers.voiceover.defaultGender, ["female", "male"] as const, "female"),
        femaleVoiceId: String(settings.providers.voiceover.femaleVoiceId || ""),
        maleVoiceId: String(settings.providers.voiceover.maleVoiceId || "")
      },
      video: {
        ...settings.providers.video,
        provider: safeOption(settings.providers.video.provider, settingsOptions.videoProviders, "kling"),
        model: nonEmpty(settings.providers.video.model, defaultSystemSettings.providers.video.model),
        defaultMode: safeOption(settings.providers.video.defaultMode, ["static", "ai-motion"] as const, "ai-motion"),
        motionStyle: safeOption(settings.providers.video.motionStyle, ["subtle", "product-demo", "scene-action", "dramatic"] as const, "subtle"),
        clipDurationSec: clampNumber(settings.providers.video.clipDurationSec, 3, 10, 5),
        pollIntervalMs: clampNumber(settings.providers.video.pollIntervalMs, 2000, 60000, 8000),
        timeoutMs: clampNumber(settings.providers.video.timeoutMs, 60000, 30 * 60 * 1000, 10 * 60 * 1000),
        klingMode: nonEmpty(settings.providers.video.klingMode, "std"),
        klingCfgScale: clampNumber(settings.providers.video.klingCfgScale, 0, 1, 0.5)
      }
    },
    workflow: {
      autoGenerateStoryboard: Boolean(settings.workflow.autoGenerateStoryboard),
      autoGenerateVoiceover: Boolean(settings.workflow.autoGenerateVoiceover),
      keepUploadedStoryboardLocked: Boolean(settings.workflow.keepUploadedStoryboardLocked),
      allowExternalVideoUpload: Boolean(settings.workflow.allowExternalVideoUpload),
      generateJimengPrompts: Boolean(settings.workflow.generateJimengPrompts),
      showCostEstimate: Boolean(settings.workflow.showCostEstimate),
      maxStoryboardFrames: clampNumber(settings.workflow.maxStoryboardFrames, 1, 8, 5)
    },
    output: {
      defaultAspectRatio: safeOption(settings.output.defaultAspectRatio, settingsOptions.aspectRatios, "9:16"),
      subtitleStyle: safeOption(settings.output.subtitleStyle, settingsOptions.subtitleStyles, "default"),
      secondsPerImage: clampNumber(settings.output.secondsPerImage, 1, 10, 3)
    }
  };
}

function nonEmpty(value: unknown, fallback: string) {
  return typeof value === "string" && value.trim() ? value.trim() : fallback;
}

function clampNumber(value: unknown, min: number, max: number, fallback: number) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.min(Math.max(number, min), max);
}

function safeOption<T extends readonly string[]>(value: unknown, options: T, fallback: T[number]) {
  return options.includes(String(value)) ? String(value) as T[number] : fallback;
}
