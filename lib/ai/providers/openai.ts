import { createReadStream } from "fs";
import OpenAI from "openai";
import { jsonOnlyInstruction } from "@/lib/prompts";
import { JsonPromptRequest, JsonPromptResponse, TranscriptionResponse } from "@/lib/ai/types";
import { getSystemSettings } from "@/lib/settings";

let client: OpenAI | null = null;

export function getOpenAIClient() {
  if (!process.env.OPENAI_API_KEY) return null;
  if (!client) client = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });
  return client;
}

export async function runOpenAIJsonPrompt<T>({
  prompt,
  fallback,
  temperature
}: JsonPromptRequest<T>): Promise<JsonPromptResponse<T>> {
  const openai = getOpenAIClient();
  const settings = await getSystemSettings();
  const model = settings.providers.text.model || process.env.OPENAI_MODEL || "gpt-4o-mini";
  const effectiveTemperature = temperature ?? settings.providers.text.temperature;

  if (!openai) {
    if (!settings.providers.text.fallbackToLocalDraft) {
      throw new Error("OPENAI_API_KEY is not configured and local draft fallback is disabled.");
    }
    return {
      data: fallback(),
      source: "fallback",
      warning: "OPENAI_API_KEY is not configured; returned local draft output."
    };
  }

  try {
    const { completion } = await createJsonCompletion({
      openai,
      model,
      prompt,
      temperature: effectiveTemperature
    });

    const content = completion.choices[0]?.message?.content;
    if (!content) throw new Error("OpenAI returned an empty response.");

    return {
      data: JSON.parse(content) as T,
      source: "openai",
      usage: {
        provider: "openai",
        model,
        inputTokens: completion.usage?.prompt_tokens,
        outputTokens: completion.usage?.completion_tokens
      }
    };
  } catch (error) {
    if (!settings.providers.text.fallbackToLocalDraft) throw error;
    return {
      data: fallback(),
      source: "fallback",
      warning: error instanceof Error ? error.message : "OpenAI request failed.",
      usage: { provider: "openai", model }
    };
  }
}

async function createJsonCompletion({
  openai,
  model,
  prompt,
  temperature
}: {
  openai: OpenAI;
  model: string;
  prompt: string;
  temperature?: number;
}) {
  const request = {
    model,
    ...(temperature == null ? {} : { temperature }),
    response_format: { type: "json_object" as const },
    messages: [
      { role: "system" as const, content: jsonOnlyInstruction },
      { role: "user" as const, content: prompt }
    ]
  };

  try {
    return {
      completion: await openai.chat.completions.create(request),
      retriedWithoutTemperature: false
    };
  } catch (error) {
    if (!isUnsupportedTemperatureError(error) || temperature == null) throw error;

    return {
      completion: await openai.chat.completions.create({
        model,
        response_format: { type: "json_object" },
        messages: request.messages
      }),
      retriedWithoutTemperature: true
    };
  }
}

function isUnsupportedTemperatureError(error: unknown) {
  if (!(error instanceof Error)) return false;
  return /temperature/i.test(error.message) && /unsupported|does not support|only the default/i.test(error.message);
}

export async function transcribeWithOpenAI(filePath: string): Promise<TranscriptionResponse> {
  const openai = getOpenAIClient();
  if (!openai) throw new Error("OPENAI_API_KEY is not configured.");
  const settings = await getSystemSettings();

  const transcription = await openai.audio.transcriptions.create({
    file: createReadStream(filePath),
    model: settings.providers.transcription.model || process.env.OPENAI_TRANSCRIBE_MODEL || "gpt-4o-mini-transcribe",
    response_format: "verbose_json"
  });

  return transcription as unknown as TranscriptionResponse;
}
