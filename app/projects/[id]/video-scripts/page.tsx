import { notFound } from "next/navigation";
import { ProjectNav } from "@/components/project-nav";
import { ReferenceAssetManager } from "@/components/reference-asset-manager";
import { VideoScriptClient } from "@/components/video-script-client";
import { getProjectWithHistory } from "@/lib/projects";
import { getSystemSettings } from "@/lib/settings";

export const dynamic = "force-dynamic";

export default async function VideoScriptsPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const project = await getProjectWithHistory(id);
  if (!project) notFound();
  const settings = await getSystemSettings();

  return (
    <div>
      <ProjectNav projectId={project.id} />
      <div className="mb-5">
        <ReferenceAssetManager
          projectId={project.id}
          initialAssets={JSON.parse(JSON.stringify(project.assets || []))}
          initialRequiredObjects={collectRequiredObjects(project.videoScripts || [])}
        />
      </div>
      <VideoScriptClient
        projectId={project.id}
        initialScripts={JSON.parse(JSON.stringify(project.videoScripts))}
        initialSettings={settings}
      />
    </div>
  );
}

function collectRequiredObjects(scripts: any[]) {
  const map = new Map<string, any>();
  for (const script of scripts) {
    for (const object of toObjects(script.requiredObjects)) {
      const key = normalizeKey(object.referenceKey || object.key || object.name || object.label || "");
      if (!key) continue;
      map.set(key, {
        referenceKey: key,
        label: object.label || object.name || key,
        role: object.role || "reference",
        reason: object.reason || object.usage || "",
        scripts: [...(map.get(key)?.scripts || []), script.title]
      });
    }
  }
  return Array.from(map.values());
}

function toObjects(value: unknown): any[] {
  if (Array.isArray(value)) return value.map((item) => (typeof item === "string" ? { name: item } : item)).filter(Boolean);
  return [];
}

function normalizeKey(value: string) {
  return value.trim().toLowerCase().replace(/[\s/\\]+/g, "_").replace(/[^a-z0-9_\-\u4e00-\u9fa5]+/g, "").slice(0, 64);
}
