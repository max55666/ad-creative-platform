-- AlterTable
ALTER TABLE "StaticCreativeSuggestion" ADD COLUMN     "imagePrompt" TEXT,
ADD COLUMN     "imageStatus" TEXT,
ADD COLUMN     "previewImageUrl" TEXT;

-- AlterTable
ALTER TABLE "VideoScript" ADD COLUMN     "imageStatus" TEXT,
ADD COLUMN     "storyboardImages" JSONB;
