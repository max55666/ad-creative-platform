"use client";

import { RefreshCw } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";

export function RegenerateCompetitorAnalysisButton({ competitorId }: { competitorId: string }) {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleClick() {
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`/api/competitors/${competitorId}/analyze`, { method: "POST" });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.message || "重新分析失敗");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "重新分析失敗");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="grid gap-2">
      <Button type="button" variant="outline" onClick={handleClick} disabled={loading}>
        <RefreshCw className={loading ? "h-4 w-4 animate-spin" : "h-4 w-4"} />
        {loading ? "分析中" : "重新分析"}
      </Button>
      {error ? <p className="text-xs text-destructive">{error}</p> : null}
    </div>
  );
}
