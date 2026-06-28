import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { fallbackVideoScripts } from "@/lib/fallbacks";
import { runJsonPrompt } from "@/lib/openai";
import { videoScriptPrompt } from "@/lib/prompts";
import { normalizeVideoScriptForSave } from "@/lib/video-script-utils";

type Params = {
  params: Promise<{ id: string }>;
};

export async function GET(_request: NextRequest, { params }: Params) {
  const { id } = await params;
  const scripts = await prisma.videoScript.findMany({
    where: { projectId: id },
    orderBy: { createdAt: "desc" }
  });

  return NextResponse.json({ scripts });
}

export async function POST(request: NextRequest, { params }: Params) {
  const { id } = await params;
  const body = await request.json().catch(() => ({}));
  const project = await prisma.project.findUnique({
    where: { id },
    include: {
      assets: true,
      analyses: { orderBy: { createdAt: "desc" }, take: 1 }
    }
  });

  if (!project) {
    return NextResponse.json({ message: "Project not found" }, { status: 404 });
  }

  const context = {
    project,
    latestAnalysis: project.analyses[0] || null,
    referenceRules: [
      "Every script must include requiredObjects: all people, animals, products, appliances and props that need reference images.",
      "Always include the main product as { label: project.productName, referenceKey: 'main_product', role: 'product' }.",
      "Every storyboard shot must include sceneObjects and requiredReferenceKeys.",
      "imagePrompt and motionPrompt must explicitly preserve uploaded reference images and avoid generic substitutes.",
      "If the script contains a female office worker, cat, air purifier, robot vacuum, pet feeder, phone, bag, or other visible object, list it in requiredObjects."
    ],
    requiredObjectSchema: {
      requiredObjects: [
        { label: "主商品", referenceKey: "main_product", role: "product", reason: "所有畫面都必須和上傳產品圖一致" },
        { label: "女性上班族", referenceKey: "female_office_worker", role: "person", reason: "腳本人物固定形象" },
        { label: "貓咪", referenceKey: "cat", role: "animal", reason: "腳本動物固定外觀" },
        { label: "掃地機器人", referenceKey: "robot_vacuum", role: "reference", reason: "畫面道具固定外觀" }
      ],
      storyboardShotFields: {
        sceneObjects: [{ label: "主商品", referenceKey: "main_product", role: "product", reason: "本鏡會露出主商品" }],
        requiredReferenceKeys: ["main_product"]
      }
    },
    options: {
      platform: body.platform || "TikTok / Reels / Shorts",
      duration: body.duration || "30秒",
      style: body.style || "痛點"
    }
  };

  const result = await runJsonPrompt({
    prompt: videoScriptPrompt(context),
    fallback: () => fallbackVideoScripts(project)
  });

  const fallbackScripts = fallbackVideoScripts(project).scripts;
  const aiScripts = Array.isArray((result.data as any).scripts)
    ? (result.data as any).scripts
    : [];
  const scripts = [...aiScripts, ...fallbackScripts]
    .slice(0, Math.max(5, aiScripts.length))
    .map((item: any) => normalizeVideoScriptForSave({ project, script: item }));

  const created = await prisma.$transaction(
    scripts.slice(0, 8).map((item: any) =>
      prisma.videoScript.create({
        data: {
          projectId: id,
          title: item.title,
          platform: item.platform || context.options.platform,
          duration: item.duration || context.options.duration,
          style: item.style || context.options.style,
          hook: item.hook,
          storyboard: item.storyboard,
          voiceover: item.voiceover,
          captions: item.captions,
          bgmSuggestion: item.bgmSuggestion,
          tone: item.tone || null,
          props: item.props || [],
          requiredObjects: item.requiredObjects || [],
          cta: item.cta,
          targetAudience: item.targetAudience || null,
          imageStatus: "pending",
          source: result.source
        }
      })
    )
  );

  return NextResponse.json({ scripts: created, source: result.source, warning: result.warning });
}
