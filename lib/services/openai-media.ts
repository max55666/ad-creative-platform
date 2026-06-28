import { aiRouter } from "@/lib/ai/router";

export async function transcribeAudioFile(filePath: string) {
  return aiRouter.transcribeAudio(filePath);
}
