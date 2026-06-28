"use client";

import { FormEvent, useState } from "react";
import type { ReactNode } from "react";
import { useRouter } from "next/navigation";
import { Wand2 } from "lucide-react";
import { FieldNote } from "@/components/field-note";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

export function BrandForm() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");

    const formData = new FormData(event.currentTarget);
    const payload = {
      name: String(formData.get("name") || ""),
      websiteUrl: String(formData.get("websiteUrl") || ""),
      industry: String(formData.get("industry") || ""),
      targetMarket: String(formData.get("targetMarket") || ""),
      description: String(formData.get("description") || ""),
      voiceTone: String(formData.get("voiceTone") || ""),
      visualStyle: String(formData.get("visualStyle") || ""),
      generateBrain: true
    };

    try {
      const response = await fetch("/api/brands", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.message || "建立品牌失敗。");
      router.push(`/brands/${data.brand.id}`);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "建立品牌失敗。");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>建立 Brand Brain</CardTitle>
        <CardDescription>輸入品牌基礎資料，系統會產生品牌定位、語氣、視覺規則與素材檢查清單。</CardDescription>
      </CardHeader>
      <CardContent>
        <form className="grid gap-5" onSubmit={handleSubmit}>
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="品牌名稱" required note={<FieldNote impact="high">AI 會用它作為品牌識別與報告主體，請填正式名稱或團隊慣用名稱。</FieldNote>}>
              <Input name="name" placeholder="例如：AMOS" required />
            </Field>
            <Field label="品牌官網" note={<FieldNote impact="medium">目前主要作為品牌資料參考與團隊辨識；若後續接網頁擷取，會影響 AI 對品牌的理解。</FieldNote>}>
              <Input name="websiteUrl" placeholder="https://..." />
            </Field>
            <Field label="產業 / 品類" note={<FieldNote impact="high">會影響 AI 判斷競品語境、受眾、視覺風格與素材常見套路。</FieldNote>}>
              <Input name="industry" placeholder="例如：寵物用品、3C、保健、美妝" />
            </Field>
            <Field label="目標市場" note={<FieldNote impact="high">會影響語言、文化情境、受眾消費能力與平台建議。</FieldNote>}>
              <Input name="targetMarket" placeholder="例如：台灣、香港、日本" />
            </Field>
          </div>

          <Field label="品牌介紹" note={<FieldNote impact="high">AI 會根據這段推論品牌定位、品牌承諾、核心訊息與素材禁忌，建議寫清楚一點。</FieldNote>}>
            <Textarea name="description" placeholder="品牌理念、主要產品、希望消費者記住什麼。" />
          </Field>

          <div className="grid gap-4 md:grid-cols-2">
            <Field label="品牌語氣" note={<FieldNote impact="high">會直接影響文案風格、KOL 腳本語氣、影片口白與 Landing Page 說法。</FieldNote>}>
              <Textarea name="voiceTone" placeholder="例如：專業但好懂、像朋友推薦、理性實測。" />
            </Field>
            <Field label="視覺風格" note={<FieldNote impact="high">會影響平面素材構圖、分鏡圖、圖片提示詞與影片畫面建議。</FieldNote>}>
              <Textarea name="visualStyle" placeholder="例如：乾淨、生活感、明亮、產品清楚、字卡大。" />
            </Field>
          </div>

          {error ? <p className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{error}</p> : null}

          <div className="flex justify-end">
            <Button type="submit" disabled={loading}>
              <Wand2 className="h-4 w-4" />
              {loading ? "生成中..." : "建立並生成 Brand Brain"}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

function Field({
  label,
  required,
  note,
  children
}: {
  label: string;
  required?: boolean;
  note?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="grid gap-2">
      <Label>
        {label}
        {required ? <span className="ml-1 text-destructive">*</span> : null}
      </Label>
      {children}
      {note}
    </div>
  );
}
