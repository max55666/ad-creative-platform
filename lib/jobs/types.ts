export const JOB_TYPES = {
  STATIC_CREATIVE_IMAGE: "static_creative_image",
  STORYBOARD_IMAGES: "storyboard_images",
  VOICEOVER: "voiceover",
  RENDER_VIDEO: "render_video",
  EXTRACT_AUDIO: "extract_audio",
  EXTRACT_FRAMES: "extract_frames",
  PROCESS_IMAGE: "process_image",
  SCRAPE_PRODUCT: "scrape_product",
  VIRAL_ANALYSIS: "viral_analysis",
  PRODUCT_LORA_TRAINING: "product_lora_training"
} as const;

export type JobType = (typeof JOB_TYPES)[keyof typeof JOB_TYPES];

export type JobContext = {
  jobId: string;
  projectId?: string | null;
  userId?: string | null;
  input: any;
  progress: (progress: number) => Promise<void>;
};
