export type JsonPromptRequest<T> = {
  prompt: string;
  fallback: () => T;
  temperature?: number;
  projectId?: string;
  userId?: string;
  jobId?: string;
};

export type JsonPromptResponse<T> = {
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

export type ImageGenerationRequest = {
  prompt: string;
  size: "1024x1024" | "1024x1536" | "1536x1024";
  referenceImagePaths?: string[];
  projectId?: string;
  userId?: string;
  jobId?: string;
};

export type ImageGenerationResponse = {
  buffer: Buffer;
  model: string;
  size: string;
};

export type TranscriptionResponse = {
  text?: string;
  [key: string]: unknown;
};

export type VoiceoverRequest = {
  text: string;
  language: "zh" | "ja" | "en";
  gender: "male" | "female";
  voiceId?: string;
  projectId?: string;
  userId?: string;
  jobId?: string;
};

export type VoiceoverResponse = {
  buffer: Buffer;
  voiceId: string;
  model: string;
};

export type VideoClipGenerationRequest = {
  imagePath: string;
  prompt: string;
  durationSec?: number;
  aspectRatio?: string;
  motionStyle?: string;
  projectId?: string;
  userId?: string;
  jobId?: string;
};

export type VideoClipGenerationResponse = {
  buffer: Buffer;
  provider: string;
  model: string;
  durationSec?: number;
  remoteUrl?: string;
  taskId?: string;
};
