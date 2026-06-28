"use client";

import { Plus, Trash2, Wand2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { FormEvent, ReactNode, useState } from "react";
import { FieldNote } from "@/components/field-note";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

type ProjectOption = {
  id: string;
  productName: string;
};

type VideoDraft = {
  videoUrl: string;
  title: string;
  sponsoredBrand: string;
  sponsoredProduct: string;
  notes: string;
};

const emptyVideo: VideoDraft = {
  videoUrl: "",
  title: "",
  sponsoredBrand: "",
  sponsoredProduct: "",
  notes: ""
};

export function KolToolClient({ projects }: { projects: ProjectOption[] }) {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [videos, setVideos] = useState<VideoDraft[]>([{ ...emptyVideo }]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");

    const formData = new FormData(event.currentTarget);
    const payload = {
      name: String(formData.get("name") || ""),
      platform: String(formData.get("platform") || ""),
      profileUrl: String(formData.get("profileUrl") || ""),
      description: String(formData.get("description") || ""),
      followerCount: String(formData.get("followerCount") || ""),
      avgViews: String(formData.get("avgViews") || ""),
      avgEngagement: String(formData.get("avgEngagement") || ""),
      tags: String(formData.get("tags") || ""),
      projectId: String(formData.get("projectId") || ""),
      videos: videos.filter((video) => video.videoUrl || video.title || video.notes)
    };

    try {
      const response = await fetch("/api/kols", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.message || "建立 KOL 分析失敗。");
      router.push(`/kols/${data.profile.id}`);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "建立 KOL 分析失敗。");
    } finally {
      setLoading(false);
    }
  }

  function updateVideo(index: number, patch: Partial<VideoDraft>) {
    setVideos((current) => current.map((video, itemIndex) => (itemIndex === index ? { ...video, ...patch } : video)));
  }

  function removeVideo(index: number) {
    setVideos((current) => (current.length === 1 ? [{ ...emptyVideo }] : current.filter((_, itemIndex) => itemIndex !== index)));
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>新增 KOL 分析</CardTitle>
        <CardDescription>貼上 KOL 網址與過往業配影片，系統會分析人設、粉絲輪廓、適合產品與轉換腳本方向。</CardDescription>
      </CardHeader>
      <CardContent>
        <form className="grid gap-5" onSubmit={handleSubmit}>
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="KOL 名稱" note={<FieldNote impact="medium">會出現在分析報告與腳本標題；若不填，AI 仍可分析，但辨識會較不直覺。</FieldNote>}>
              <Input name="name" placeholder="例如：小安生活選物" />
            </Field>
            <Field label="主要平台" note={<FieldNote impact="high">會影響 AI 對影片節奏、腳本格式、字幕密度與 CTA 的判斷。</FieldNote>}>
              <Select name="platform" defaultValue="TikTok">
                <option value="TikTok">TikTok</option>
                <option value="Instagram">Instagram</option>
                <option value="YouTube Shorts">YouTube Shorts</option>
                <option value="Facebook">Facebook</option>
                <option value="小紅書">小紅書</option>
              </Select>
            </Field>
            <Field label="KOL 網址" note={<FieldNote impact="medium">目前主要用於保存與人工開啟查看；若後續接平台擷取，會成為 AI 判讀來源。</FieldNote>}>
              <Input name="profileUrl" placeholder="https://..." required />
            </Field>
            <Field label="指定產品" note={<FieldNote impact="high">會讓 AI 評估 KOL 與該產品的適配度，並產生專屬業配腳本。</FieldNote>}>
              <Select name="projectId" defaultValue="">
                <option value="">先不指定產品</option>
                {projects.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.productName}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="粉絲數" note={<FieldNote impact="medium">會影響 AI 對商業價值、合作形式與投放放大潛力的判斷。</FieldNote>}>
              <Input name="followerCount" placeholder="例如：12.5 萬" />
            </Field>
            <Field label="平均觀看 / 互動" note={<FieldNote impact="medium">會影響 AI 對內容穩定度、粉絲活躍度與業配風險的判斷。</FieldNote>}>
              <div className="grid gap-2 sm:grid-cols-2">
                <Input name="avgViews" placeholder="平均觀看" />
                <Input name="avgEngagement" placeholder="平均互動率" />
              </div>
            </Field>
          </div>

          <Field label="KOL 補充描述" note={<FieldNote impact="high">會影響人設、語氣、粉絲輪廓與腳本自然度。請寫你觀察到的內容風格。</FieldNote>}>
            <Textarea name="description" placeholder="例如：偏生活風格、語氣像朋友推薦，粉絲常問居家、3C、美妝選物。" />
          </Field>

          <Field label="標籤" note={<FieldNote impact="high">會影響 AI 對 KOL 人設、適合產品類型與受眾興趣的推論。</FieldNote>}>
            <Input name="tags" placeholder="生活, 開箱, 省錢, 3C, 美妝" />
          </Field>

          <div className="grid gap-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-sm font-medium">過往業配影片</p>
                <FieldNote impact="high" className="mt-1">這是 KOL 分析最重要的資料之一，會影響 AI 對 Hook、口吻、商業置入方式與可複製腳本的判讀。</FieldNote>
              </div>
              <Button type="button" variant="outline" size="sm" onClick={() => setVideos((current) => [...current, { ...emptyVideo }])}>
                <Plus className="h-4 w-4" />
                新增影片
              </Button>
            </div>

            {videos.map((video, index) => (
              <div key={index} className="grid gap-3 rounded-lg border bg-white p-4">
                <div className="flex items-center justify-between">
                  <p className="text-sm font-medium">影片 {index + 1}</p>
                  <Button type="button" variant="ghost" size="sm" onClick={() => removeVideo(index)} aria-label="移除影片">
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
                <div className="grid gap-3 md:grid-cols-2">
                  <Input placeholder="影片網址：會保存，後續可用於分析來源" value={video.videoUrl} onChange={(event) => updateVideo(index, { videoUrl: event.target.value })} />
                  <Input placeholder="影片標題：會影響 AI 理解影片主題" value={video.title} onChange={(event) => updateVideo(index, { title: event.target.value })} />
                  <Input placeholder="合作品牌：會影響 AI 判斷 KOL 適合品牌類型" value={video.sponsoredBrand} onChange={(event) => updateVideo(index, { sponsoredBrand: event.target.value })} />
                  <Input placeholder="合作產品：會影響 AI 判斷 KOL 適合產品類型" value={video.sponsoredProduct} onChange={(event) => updateVideo(index, { sponsoredProduct: event.target.value })} />
                </div>
                <Textarea
                  placeholder="備註會強烈影響 AI 判讀：請寫 Hook、留言反應、影片節奏、產品露出、是否導購強。"
                  value={video.notes}
                  onChange={(event) => updateVideo(index, { notes: event.target.value })}
                />
              </div>
            ))}
          </div>

          {error ? <p className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{error}</p> : null}

          <div className="flex justify-end">
            <Button type="submit" disabled={loading}>
              <Wand2 className="h-4 w-4" />
              {loading ? "分析中..." : "建立 KOL 分析"}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

function Field({ label, note, children }: { label: string; note?: ReactNode; children: ReactNode }) {
  return (
    <div className="grid gap-2">
      <Label>{label}</Label>
      {children}
      {note}
    </div>
  );
}
