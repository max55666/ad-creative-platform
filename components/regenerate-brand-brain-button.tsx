"use client";

import { RefreshCw } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";

export function RegenerateBrandBrainButton({ brandId }: { brandId: string }) {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleRegenerate() {
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`/api/brands/${brandId}/brain`, { method: "POST" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.message || "重新生成 Brand Brain 失敗。");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "重新生成 Brand Brain 失敗。");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="grid gap-2">
      <Button type="button" onClick={handleRegenerate} disabled={loading}>
        <RefreshCw className="h-4 w-4" />
        {loading ? "生成中..." : "重新生成 Brand Brain"}
      </Button>
      {error ? <p className="text-sm text-destructive">{error}</p> : null}
    </div>
  );
}
