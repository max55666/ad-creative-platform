"use client";

import { Loader2, Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { FieldNote } from "@/components/field-note";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

type Option = {
  id: string;
  name?: string;
  productName?: string;
};

export function CompetitorForm({ brands, projects }: { brands: Option[]; projects: Option[] }) {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setLoading(true);
    setError("");

    const payload = {
      name: form.get("name"),
      websiteUrl: form.get("websiteUrl"),
      productUrl: form.get("productUrl"),
      brandId: form.get("brandId"),
      projectId: form.get("projectId"),
      industry: form.get("industry"),
      targetMarket: form.get("targetMarket"),
      priceRange: form.get("priceRange"),
      tags: form.get("tags"),
      description: form.get("description"),
      analyze: true
    };

    try {
      const response = await fetch("/api/competitors", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.message || "建立競品分析失敗");
      router.push(`/competitors/${data.competitor.id}`);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "建立競品分析失敗");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>新增競品分析</CardTitle>
        <CardDescription>
          貼上競品網站或商品頁，系統會擷取頁面資料並整理定位、受眾、訊息、Landing Page 與可反打角度。
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="grid gap-5">
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="競品名稱" name="name" placeholder="例如：某某智慧保溫杯" required note="AI 會用它判斷品牌與競品定位，是必填欄位。" />
            <Field label="產業類別" name="industry" placeholder="例如：寵物用品、保健食品、3C 配件" note="會影響 AI 選擇比較基準與常見痛點。" />
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <Field label="競品官網 URL" name="websiteUrl" type="url" placeholder="https://..." note="若可擷取成功，會大幅影響 AI 對品牌定位與頁面結構的判讀。" />
            <Field label="競品商品頁 URL" name="productUrl" type="url" placeholder="https://..." note="最重要的外部資料來源，會用來擷取商品文案、圖片與頁面截圖。" />
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <div className="grid gap-2">
              <Label htmlFor="brandId">對應品牌</Label>
              <Select id="brandId" name="brandId" defaultValue="">
                <option value="">不指定品牌</option>
                {brands.map((brand) => (
                  <option key={brand.id} value={brand.id}>
                    {brand.name}
                  </option>
                ))}
              </Select>
              <FieldNote impact="high">會把 Brand Brain 納入比較，協助找出「我們可以反打哪裡」。</FieldNote>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="projectId">對應產品專案</Label>
              <Select id="projectId" name="projectId" defaultValue="">
                <option value="">不指定產品</option>
                {projects.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.productName}
                  </option>
                ))}
              </Select>
              <FieldNote impact="high">會把我方產品分析一起帶入，讓 AI 產出更貼近可執行的素材角度。</FieldNote>
            </div>
          </div>

          <div className="grid gap-4 md:grid-cols-3">
            <Field label="目標市場" name="targetMarket" placeholder="例如：台灣、香港、日本" note="會影響受眾與廣告語氣判斷。" />
            <Field label="價格帶" name="priceRange" placeholder="例如：NT$990-1,990" impact="medium" note="協助判斷競品價格訊號與消費疑慮。" />
            <Field label="標籤" name="tags" placeholder="募資, 寵物, 高單價" impact="medium" note="可用逗號、頓號或換行分隔，會影響分類與搜尋。" />
          </div>

          <div className="grid gap-2">
            <Label htmlFor="description">你已知的競品補充</Label>
            <Textarea id="description" name="description" placeholder="例如：主打自動清潔、募資平台熱賣、客單價較高、常用素人開箱素材..." />
            <FieldNote impact="high">如果網站擷取不到完整資訊，這段會成為 AI 判讀競品策略的主要依據。</FieldNote>
          </div>

          {error ? <p className="rounded-md border border-destructive/25 bg-destructive/5 px-3 py-2 text-sm text-destructive">{error}</p> : null}

          <div className="flex justify-end">
            <Button type="submit" disabled={loading}>
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
              {loading ? "建立並分析中" : "建立競品分析"}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

function Field({
  label,
  name,
  placeholder,
  note,
  type = "text",
  required = false,
  impact = "high"
}: {
  label: string;
  name: string;
  placeholder?: string;
  note: string;
  type?: string;
  required?: boolean;
  impact?: "high" | "medium" | "none";
}) {
  return (
    <div className="grid gap-2">
      <Label htmlFor={name}>{label}</Label>
      <Input id={name} name={name} type={type} placeholder={placeholder} required={required} />
      <FieldNote impact={impact}>{note}</FieldNote>
    </div>
  );
}
