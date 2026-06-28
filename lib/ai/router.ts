import { runOpenAIJsonPrompt, transcribeWithOpenAI } from "@/lib/ai/providers/openai";
import { generateOpenAIImage } from "@/lib/ai/providers/openai-image";
import { generateElevenLabsSpeech } from "@/lib/ai/providers/elevenlabs";
import { generateKlingVideoClip } from "@/lib/ai/providers/kling";
import {
  ImageGenerationRequest,
  JsonPromptRequest,
  VideoClipGenerationRequest,
  VoiceoverRequest
} from "@/lib/ai/types";
import { getSystemSettings } from "@/lib/settings";

export const aiRouter = {
  runJsonPrompt<T>(request: JsonPromptRequest<T>) {
    return runOpenAIJsonPrompt(request);
  },

  generateImage(request: ImageGenerationRequest) {
    return generateOpenAIImage(request);
  },

  transcribeAudio(filePath: string) {
    return transcribeWithOpenAI(filePath);
  },

  generateVoiceover(request: VoiceoverRequest) {
    return generateElevenLabsSpeech(request);
  },

  async generateVideoClip(request: VideoClipGenerationRequest) {
    const settings = await getSystemSettings();
    const provider = settings.providers.video.provider || process.env.VIDEO_PROVIDER || "kling";
    if (provider !== "kling") {
      throw new Error(
        `目前影片供應商設定為 ${provider}，此供應商尚未接入 API。請切回 Kling，或複製即夢/外部平台提示詞手動生成影片後再上傳回系統合成。`
      );
    }
    return generateKlingVideoClip(request);
  }
};
