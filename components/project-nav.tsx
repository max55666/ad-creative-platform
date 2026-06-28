import Link from "next/link";
import { BarChart3, BrainCircuit, FileText, Film, Image, LayoutTemplate, Wand2 } from "lucide-react";
import { Button } from "@/components/ui/button";

export function ProjectNav({ projectId }: { projectId: string }) {
  const items = [
    { href: `/projects/${projectId}`, label: "分析報告", icon: FileText },
    { href: `/projects/${projectId}/static-creatives`, label: "平面素材", icon: Image },
    { href: `/projects/${projectId}/video-scripts`, label: "短影音", icon: Film },
    { href: `/projects/${projectId}/viral-analysis`, label: "爆款分析", icon: BarChart3 },
    { href: `/projects/${projectId}/crowdfunding`, label: "募資頁", icon: LayoutTemplate },
    { href: `/projects/${projectId}/lora-models`, label: "產品模型", icon: BrainCircuit }
  ];

  return (
    <div className="mb-5 flex flex-wrap gap-2">
      {items.map((item) => (
        <Button key={item.href} asChild variant="outline" size="sm">
          <Link href={item.href}>
            <item.icon className="h-4 w-4" />
            {item.label}
          </Link>
        </Button>
      ))}
      <Button asChild size="sm">
        <Link href="/projects/new">
          <Wand2 className="h-4 w-4" />
          新增分析
        </Link>
      </Button>
    </div>
  );
}
