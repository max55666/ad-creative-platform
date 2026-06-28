import { VoiceoverRequest, VoiceoverResponse } from "@/lib/ai/types";
import { getSystemSettings } from "@/lib/settings";

export async function generateElevenLabsSpeech({
  text,
  language,
  gender,
  voiceId
}: VoiceoverRequest): Promise<VoiceoverResponse> {
  const apiKey = process.env.ELEVENLABS_API_KEY;
  if (!apiKey) throw new Error("ELEVENLABS_API_KEY is not configured.");
  const settings = await getSystemSettings();

  const selectedVoiceId =
    voiceId ||
    (gender === "male" ? settings.providers.voiceover.maleVoiceId : settings.providers.voiceover.femaleVoiceId) ||
    (gender === "male" ? process.env.ELEVENLABS_VOICE_ID_MALE : process.env.ELEVENLABS_VOICE_ID_FEMALE) ||
    process.env.ELEVENLABS_VOICE_ID ||
    (await findElevenLabsVoiceId({ apiKey, gender }));

  if (!selectedVoiceId) throw new Error("No ElevenLabs voice is available for this API key.");

  const model = settings.providers.voiceover.model || "eleven_multilingual_v2";
  const response = await fetch(`https://api.elevenlabs.io/v1/text-to-speech/${selectedVoiceId}`, {
    method: "POST",
    headers: {
      "xi-api-key": apiKey,
      "content-type": "application/json",
      accept: "audio/mpeg"
    },
    body: JSON.stringify({
      text,
      model_id: model,
      voice_settings: {
        stability: 0.45,
        similarity_boost: 0.8,
        style: 0.2,
        use_speaker_boost: true
      }
    })
  });

  if (!response.ok) {
    throw new Error(`ElevenLabs request failed: ${response.status} ${await response.text()}`);
  }

  return {
    buffer: Buffer.from(await response.arrayBuffer()),
    voiceId: selectedVoiceId,
    model
  };
}

async function findElevenLabsVoiceId({
  apiKey,
  gender
}: {
  apiKey: string;
  gender: "male" | "female";
}) {
  const response = await fetch("https://api.elevenlabs.io/v1/voices", {
    headers: { "xi-api-key": apiKey }
  });

  if (!response.ok) {
    throw new Error(`ElevenLabs voices request failed: ${response.status} ${await response.text()}`);
  }

  const data = await response.json();
  const voices = Array.isArray(data.voices) ? data.voices : [];
  const preferred = voices.find((voice: any) => {
    const labels = voice?.labels || {};
    return String(labels.gender || "").toLowerCase() === gender;
  });

  return preferred?.voice_id || voices[0]?.voice_id || "";
}
