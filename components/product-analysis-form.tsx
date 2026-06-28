"use client";

import { Loader2, UploadCloud, Wand2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import type { ReactNode } from "react";
import { FieldNote } from "@/components/field-note";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

type BrandOption = {
  id: string;
  name: string;
};

type FormState = {
  brandId: string;
  productName: string;
  productDescription: string;
  productUrl: string;
  targetMarket: string;
  price: string;
  specs: string;
  mainUseCase: string;
  competitors: string;
};

const initialState: FormState = {
  brandId: "",
  productName: "",
  productDescription: "",
  productUrl: "",
  targetMarket: "台灣",
  price: "",
  specs: "",
  mainUseCase: "",
  competitors: ""
};

export function ProductAnalysisForm({ brands = [] }: { brands?: BrandOption[] }) {
  const router = useRouter();
  const [form, setForm] = useState<FormState>(initialState);
  const [files, setFiles] = useState<FileList | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError(null);

    try {
      const projectResponse = await fetch("/api/projects", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(form)
      });

      if (!projectResponse.ok) throw new Error("建立產品專案失敗。");
      const { project } = await projectResponse.json();

      if (files?.length) {
        for (const file of Array.from(files)) {
          const formData = new FormData();
          formData.append("file", file);
          formData.append("projectId", project.id);
          formData.append("role", file.type.startsWith("image") ? "product" : "other");
          formData.append("label", form.productName || file.name);
          formData.append("referenceKey", "main_product");
          formData.append("usage", "主商品外觀參考");
          formData.append("viewAngle", "不指定");
          formData.append("notes", "建立產品專案時上傳的主商品圖片，生成素材時需優先鎖定外觀。");
          formData.append("analyze", file.type.startsWith("image") ? "true" : "false");
          const uploadResponse = await fetch("/api/upload", {
            method: "POST",
            body: formData
          });
          if (!uploadResponse.ok) throw new Error(`上傳 ${file.name} 失敗。`);
        }
      }

      await fetch(`/api/projects/${project.id}/analyze`, { method: "POST" });
      router.push(`/projects/${project.id}`);
      router.refresh();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "送出失敗。");
    } finally {
      setLoading(false);
    }
  }

  function updateField(key: keyof FormState, value: string) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>新增產品分析專案</CardTitle>
        <CardDescription>輸入產品資料後，系統會產生產品摘要、受眾、痛點、賣點與素材方向。欄位越完整，AI 初稿越接近可用版本。</CardDescription>
      </CardHeader>
      <CardContent>
        <form className="grid gap-5" onSubmit={handleSubmit}>
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="品牌" note={<FieldNote impact="high">會套用該品牌最新 Brand Brain，影響文案語氣、視覺規則與素材建議。</FieldNote>}>
              <Select value={form.brandId} onChange={(event) => updateField("brandId", event.target.value)}>
                <option value="">不指定品牌</option>
                {brands.map((brand) => (
                  <option key={brand.id} value={brand.id}>
                    {brand.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="產品名稱" required note={<FieldNote impact="high">AI 會用它識別產品主體，也會出現在素材標題、腳本與報告中。</FieldNote>}>
              <Input value={form.productName} onChange={(event) => updateField("productName", event.target.value)} placeholder="例如：智慧貓砂盆" />
            </Field>
            <Field label="售價" note={<FieldNote impact="medium">會影響 AI 對消費能力、購買疑慮、促銷角度與 CTA 的判斷。</FieldNote>}>
              <Input value={form.price} onChange={(event) => updateField("price", event.target.value)} placeholder="例如：NT$4,900" />
            </Field>
            <Field label="目標市場" note={<FieldNote impact="high">會影響語言、文化情境、平台建議與受眾推論。</FieldNote>}>
              <Input value={form.targetMarket} onChange={(event) => updateField("targetMarket", event.target.value)} placeholder="台灣 / 香港 / 日本" />
            </Field>
          </div>

          <Field label="產品介紹" note={<FieldNote impact="high">這是最重要欄位之一。AI 會根據它判斷產品類別、核心賣點、痛點與素材主軸。</FieldNote>}>
            <Textarea value={form.productDescription} onChange={(event) => updateField("productDescription", event.target.value)} placeholder="產品功能、特色、解決什麼問題。" />
          </Field>

          <div className="grid gap-4 md:grid-cols-2">
            <Field label="官網 / 商品頁 URL" note={<FieldNote impact="medium">若系統成功擷取網頁內容，會影響 AI 判讀；若沒有擷取成功，主要作為資料保存。</FieldNote>}>
              <Input value={form.productUrl} onChange={(event) => updateField("productUrl", event.target.value)} placeholder="https://..." />
            </Field>
            <Field label="產品規格" note={<FieldNote impact="high">會影響功能型賣點、消費者疑慮、數據佐證素材與比較型素材。</FieldNote>}>
              <Textarea value={form.specs} onChange={(event) => updateField("specs", event.target.value)} placeholder="尺寸、材質、容量、規格、保固等。" />
            </Field>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <Field label="主要使用場景" note={<FieldNote impact="high">會影響受眾、痛點、影片分鏡、平面構圖與 Hook 的生活情境。</FieldNote>}>
              <Textarea value={form.mainUseCase} onChange={(event) => updateField("mainUseCase", event.target.value)} placeholder="日常、外出、辦公、家庭、送禮等。" />
            </Field>
            <Field label="競品資料 / 競品網址" note={<FieldNote impact="high">會影響差異化、對比型素材、不適合主打的賣點與競品切入角度。</FieldNote>}>
              <Textarea value={form.competitors} onChange={(event) => updateField("competitors", event.target.value)} placeholder="競品名稱、網址、價格、主打賣點。" />
            </Field>
          </div>

          <div className="rounded-lg border border-dashed bg-white p-4">
            <Label className="mb-2 flex items-center gap-2">
              <UploadCloud className="h-4 w-4" />
              產品圖片 / 影片素材
            </Label>
            <Input type="file" accept="image/*,video/*" multiple onChange={(event) => setFiles(event.target.files)} />
            <FieldNote impact="medium" className="mt-2">目前會保存為專案資產；後續生成分鏡、圖片或影片分析時，這些素材可作為 AI 視覺判讀來源。</FieldNote>
          </div>

          {error ? <p className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">{error}</p> : null}

          <Button type="submit" disabled={loading}>
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wand2 className="h-4 w-4" />}
            {loading ? "建立並分析中..." : "建立專案並分析"}
          </Button>
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
