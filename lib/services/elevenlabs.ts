import { aiRouter } from "@/lib/ai/router";
import { getStorage } from "@/lib/storage";

export type VoiceLanguage = "zh" | "ja" | "en";
export type VoiceGender = "male" | "female";

export async function generateElevenLabsVoiceover({
  text,
  language,
  gender,
  projectId,
  voiceId
}: {
  text: string;
  language: VoiceLanguage;
  gender: VoiceGender;
  projectId: string;
  voiceId?: string;
}) {
  const result = await aiRouter.generateVoiceover({
    text,
    language,
    gender,
    voiceId,
    projectId
  });

  const fileName = `${Date.now()}-${language}-${gender}.mp3`;
  const stored = await getStorage().put(result.buffer, {
    directory: `voiceovers/${projectId}`,
    fileName,
    contentType: "audio/mpeg"
  });

  return {
    filePath: stored.path || getStorage().getLocalPath(stored.key),
    fileUrl: stored.url,
    voiceId: result.voiceId,
    model: result.model
  };
}
