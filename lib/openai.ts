import { aiRouter } from "@/lib/ai/router";

type JsonPromptOptions<T> = {
  prompt: string;
  fallback: () => T;
  temperature?: number;
};

type JsonPromptResult<T> = {
  data: T;
  source: "openai" | "fallback";
  warning?: string;
  usage?: {
    provider: string;
    model?: string;
    inputTokens?: number;
    outputTokens?: number;
  };
};

export async function runJsonPrompt<T>({
  prompt,
  fallback,
  temperature
}: JsonPromptOptions<T>): Promise<JsonPromptResult<T>> {
  return aiRouter.runJsonPrompt({ prompt, fallback, temperature });
}
