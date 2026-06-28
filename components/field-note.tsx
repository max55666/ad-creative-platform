import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

type Impact = "high" | "medium" | "none";

const impactLabels: Record<Impact, string> = {
  high: "影響 AI 判讀",
  medium: "部分影響",
  none: "不影響 AI 判讀"
};

const impactClasses: Record<Impact, string> = {
  high: "border-emerald-200 bg-emerald-50 text-emerald-800",
  medium: "border-amber-200 bg-amber-50 text-amber-800",
  none: "border-slate-200 bg-slate-50 text-slate-600"
};

export function FieldNote({
  impact,
  children,
  className
}: {
  impact: Impact;
  children: ReactNode;
  className?: string;
}) {
  return (
    <p className={cn("text-xs leading-5 text-muted-foreground", className)}>
      <span className={cn("mr-2 inline-flex rounded border px-1.5 py-0.5 text-[11px] font-medium", impactClasses[impact])}>
        {impactLabels[impact]}
      </span>
      {children}
    </p>
  );
}
