"use client";

import { ImageIcon, Loader2, Plus, RefreshCw, Save, Trash2, UploadCloud } from "lucide-react";
import { ChangeEvent, useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

type Asset = {
  id: string;
  fileUrl?: string | null;
  content?: string | null;
  meta?: Record<string, any> | null;
};

type RequiredObject = {
  referenceKey: string;
  label: string;
  role?: string;
  reason?: string;
  scripts?: string[];
};

type UploadDraft = {
  usage: string;
  viewAngle: string;
  notes: string;
};

const usageOptions = [
  "主商品正面",
  "主商品側面",
  "主商品背面",
  "商品細節特寫",
  "Logo / 包裝文字",
  "使用情境",
  "手持比例",
  "材質與顏色",
  "配角外觀",
  "場景道具"
];

const viewOptions = ["", "正面", "側面", "背面", "45 度角", "俯視", "近拍", "遠景", "手持", "情境中"];

export function ReferenceAssetManager({
  projectId,
  initialAssets,
  initialRequiredObjects
}: {
  projectId: string;
  initialAssets: Asset[];
  initialRequiredObjects?: RequiredObject[];
}) {
  const [assets, setAssets] = useState<Asset[]>(initialAssets || []);
  const [requiredObjects, setRequiredObjects] = useState<RequiredObject[]>(initialRequiredObjects || []);
  const [loading, setLoading] = useState<Record<string, boolean>>({});
  const [message, setMessage] = useState("");
  const [uploadDrafts, setUploadDrafts] = useState<Record<string, UploadDraft>>({});
  const [assetDrafts, setAssetDrafts] = useState<Record<string, UploadDraft>>({});
  const [customLabel, setCustomLabel] = useState("");
  const [customRole, setCustomRole] = useState("reference");

  const assetsByKey = useMemo(() => {
    const map = new Map<string, Asset[]>();
    for (const asset of assets) {
      const key = String(asset.meta?.referenceKey || "");
      if (!key) continue;
      map.set(key, [...(map.get(key) || []), asset]);
    }
    return map;
  }, [assets]);

  const objects = useMemo(() => {
    const map = new Map<string, RequiredObject>();
    const baseObjects = requiredObjects.length
      ? requiredObjects
      : [{ referenceKey: "main_product", label: "主商品", role: "product", reason: "所有素材生成都會優先鎖定主商品外觀。" }];

    for (const object of baseObjects) {
      const key = object.referenceKey || toReferenceKey(object.label);
      if (!key) continue;
      map.set(key, { ...object, referenceKey: key });
    }

    for (const asset of assets) {
      const key = String(asset.meta?.referenceKey || "");
      if (!key || map.has(key)) continue;
      map.set(key, {
        referenceKey: key,
        label: String(asset.meta?.label || key),
        role: String(asset.meta?.role || "reference"),
        reason: "從已上傳參考圖建立的物件群組。"
      });
    }

    return Array.from(map.values());
  }, [assets, requiredObjects]);

  async function refresh() {
    const response = await fetch(`/api/projects/${projectId}/reference-assets`);
    const data = await response.json();
    setAssets(data.assets || []);
    setRequiredObjects(data.requiredObjects || []);
  }

  function draftFor(key: string): UploadDraft {
    return uploadDrafts[key] || { usage: key === "main_product" ? "主商品正面" : "外觀參考", viewAngle: "", notes: "" };
  }

  function updateUploadDraft(key: string, patch: Partial<UploadDraft>) {
    setUploadDrafts((current) => ({ ...current, [key]: { ...draftFor(key), ...patch } }));
  }

  async function uploadForObject(object: RequiredObject, files: File[]) {
    if (!files.length) return;
    const key = object.referenceKey || toReferenceKey(object.label);
    const draft = draftFor(key);
    setLoading((current) => ({ ...current, [key]: true }));
    setMessage("");

    try {
      for (const file of files) {
        const formData = new FormData();
        formData.append("file", file);
        formData.append("projectId", projectId);
        formData.append("role", object.role || "reference");
        formData.append("label", object.label || key);
        formData.append("referenceKey", key);
        formData.append("usage", draft.usage);
        formData.append("viewAngle", draft.viewAngle);
        formData.append("notes", draft.notes);
        formData.append("analyze", "true");

        const response = await fetch("/api/upload", { method: "POST", body: formData });
        const data = await response.json();
        if (!response.ok) throw new Error(data.message || "上傳參考圖失敗");
      }
      await refresh();
      setMessage(`已上傳 ${files.length} 張「${object.label || key}」參考圖。`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "上傳參考圖失敗");
    } finally {
      setLoading((current) => ({ ...current, [key]: false }));
    }
  }

  async function saveAsset(asset: Asset, patch?: Partial<UploadDraft>) {
    const meta = asset.meta || {};
    const draft = { ...draftForAsset(asset), ...patch };
    setLoading((current) => ({ ...current, [asset.id]: true }));
    try {
      const response = await fetch(`/api/projects/${projectId}/reference-assets`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          assetId: asset.id,
          label: meta.label,
          referenceKey: meta.referenceKey,
          role: meta.role,
          usage: draft.usage,
          viewAngle: draft.viewAngle,
          notes: draft.notes,
          analyze: false
        })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.message || "更新註記失敗");
      setAssets((current) => current.map((item) => (item.id === asset.id ? data.asset : item)));
      setMessage("已更新圖片註記。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "更新註記失敗");
    } finally {
      setLoading((current) => ({ ...current, [asset.id]: false }));
    }
  }

  async function reanalyze(assetId: string) {
    setLoading((current) => ({ ...current, [assetId]: true }));
    try {
      const response = await fetch(`/api/projects/${projectId}/reference-assets`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ assetId })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.message || "重新分析失敗");
      setAssets((current) => current.map((asset) => (asset.id === assetId ? data.asset : asset)));
      setMessage("已重新分析參考圖。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "重新分析失敗");
    } finally {
      setLoading((current) => ({ ...current, [assetId]: false }));
    }
  }

  async function deleteAsset(assetId: string) {
    if (!confirm("確定要移除這張參考圖？")) return;
    setLoading((current) => ({ ...current, [assetId]: true }));
    try {
      const response = await fetch(`/api/projects/${projectId}/reference-assets`, {
        method: "DELETE",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ assetId })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.message || "刪除失敗");
      setAssets((current) => current.filter((asset) => asset.id !== assetId));
      setMessage("已移除參考圖。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "刪除失敗");
    } finally {
      setLoading((current) => ({ ...current, [assetId]: false }));
    }
  }

  function addCustomObject() {
    const label = customLabel.trim();
    if (!label) return;
    const referenceKey = toReferenceKey(label);
    setRequiredObjects((current) => {
      if (current.some((item) => item.referenceKey === referenceKey)) return current;
      return [...current, { referenceKey, label, role: customRole, reason: "手動新增，供素材生成鎖定外觀。" }];
    });
    setCustomLabel("");
    setCustomRole("reference");
  }

  function draftForAsset(asset: Asset): UploadDraft {
    const existing = assetDrafts[asset.id];
    if (existing) return existing;
    return {
      usage: String(asset.meta?.usage || "外觀參考"),
      viewAngle: String(asset.meta?.viewAngle || ""),
      notes: String(asset.meta?.notes || "")
    };
  }

  function updateAssetDraft(asset: Asset, patch: Partial<UploadDraft>) {
    setAssetDrafts((current) => ({ ...current, [asset.id]: { ...draftForAsset(asset), ...patch } }));
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2">
              <ImageIcon className="h-4 w-4" />
              參考素材鎖定
            </CardTitle>
            <CardDescription>
              每個物件都可以上傳多張參考圖，並標註用途。AI 生成平面圖、分鏡圖與影片畫面時會優先參考這些圖片，避免主商品或配角跑掉。
            </CardDescription>
          </div>
          <Button type="button" variant="outline" size="sm" onClick={refresh}>
            <RefreshCw className="h-4 w-4" />
            重新整理
          </Button>
        </div>
      </CardHeader>

      <CardContent className="grid gap-4">
        {message ? <p className="rounded-md border bg-muted/50 px-3 py-2 text-sm">{message}</p> : null}

        <div className="grid gap-3 rounded-lg border bg-muted/30 p-3 md:grid-cols-[1fr_180px_auto]">
          <div className="grid gap-1">
            <Label>手動新增需要鎖定的物件</Label>
            <Input value={customLabel} onChange={(event) => setCustomLabel(event.target.value)} placeholder="例如：貓砂盆、藍色收納盒、女性上班族" />
            <p className="text-xs text-muted-foreground">腳本沒有自動列出的物件，也可以在這裡新增後上傳參考圖。</p>
          </div>
          <div className="grid gap-1">
            <Label>物件類型</Label>
            <Select value={customRole} onChange={(event) => setCustomRole(event.target.value)}>
              <option value="reference">道具 / 場景</option>
              <option value="product">主商品</option>
              <option value="person">人物</option>
              <option value="animal">動物</option>
            </Select>
          </div>
          <div className="flex items-end">
            <Button type="button" onClick={addCustomObject} disabled={!customLabel.trim()}>
              <Plus className="h-4 w-4" />
              新增
            </Button>
          </div>
        </div>

        <div className="grid gap-4">
          {objects.map((object) => {
            const key = object.referenceKey;
            const objectAssets = assetsByKey.get(key) || [];
            const draft = draftFor(key);

            return (
              <section key={key} className="grid gap-3 rounded-lg border bg-white p-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="font-medium">{object.label}</p>
                      <Badge>{objectAssets.length} 張參考圖</Badge>
                      <Badge className="bg-white">{object.role || "reference"}</Badge>
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">{key}</p>
                    {object.reason ? <p className="mt-2 text-xs leading-5 text-muted-foreground">{object.reason}</p> : null}
                  </div>
                </div>

                <div className="grid gap-3 rounded-md border bg-muted/20 p-3 md:grid-cols-[180px_140px_1fr_auto]">
                  <div className="grid gap-1">
                    <Label>這次上傳用途</Label>
                    <Select value={draft.usage} onChange={(event) => updateUploadDraft(key, { usage: event.target.value })}>
                      {usageOptions.map((option) => <option key={option} value={option}>{option}</option>)}
                      <option value="外觀參考">外觀參考</option>
                    </Select>
                  </div>
                  <div className="grid gap-1">
                    <Label>角度</Label>
                    <Select value={draft.viewAngle} onChange={(event) => updateUploadDraft(key, { viewAngle: event.target.value })}>
                      {viewOptions.map((option) => <option key={option || "none"} value={option}>{option || "不指定"}</option>)}
                    </Select>
                  </div>
                  <div className="grid gap-1">
                    <Label>補充註記</Label>
                    <Input
                      value={draft.notes}
                      onChange={(event) => updateUploadDraft(key, { notes: event.target.value })}
                      placeholder="例如：只參考外型，不要照抄背景；Logo 位置不可變"
                    />
                  </div>
                  <div className="flex items-end">
                    <label className="inline-flex h-10 cursor-pointer items-center justify-center gap-2 rounded-md border bg-white px-3 text-sm font-medium hover:bg-muted">
                      {loading[key] ? <Loader2 className="h-4 w-4 animate-spin" /> : <UploadCloud className="h-4 w-4" />}
                      上傳多張
                      <input
                        type="file"
                        accept="image/*"
                        multiple
                        className="hidden"
                        disabled={Boolean(loading[key])}
                        onChange={(event: ChangeEvent<HTMLInputElement>) => {
                          const files = Array.from(event.target.files || []);
                          event.target.value = "";
                          uploadForObject(object, files);
                        }}
                      />
                    </label>
                  </div>
                </div>

                {objectAssets.length ? (
                  <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                    {objectAssets.map((asset) => {
                      const draftAsset = draftForAsset(asset);
                      return (
                        <article key={asset.id} className="grid gap-3 rounded-md border bg-white p-3">
                          {asset.fileUrl ? (
                            <div className="overflow-hidden rounded-md border bg-muted">
                              <img src={asset.fileUrl} alt={String(asset.meta?.label || object.label)} className="h-36 w-full object-cover" />
                            </div>
                          ) : null}

                          <div className="grid gap-2">
                            <div className="grid grid-cols-2 gap-2">
                              <div className="grid gap-1">
                                <Label className="text-xs">用途</Label>
                                <Select value={draftAsset.usage} onChange={(event) => updateAssetDraft(asset, { usage: event.target.value })}>
                                  {usageOptions.map((option) => <option key={option} value={option}>{option}</option>)}
                                  <option value="外觀參考">外觀參考</option>
                                </Select>
                              </div>
                              <div className="grid gap-1">
                                <Label className="text-xs">角度</Label>
                                <Select value={draftAsset.viewAngle} onChange={(event) => updateAssetDraft(asset, { viewAngle: event.target.value })}>
                                  {viewOptions.map((option) => <option key={option || "none"} value={option}>{option || "不指定"}</option>)}
                                </Select>
                              </div>
                            </div>
                            <div className="grid gap-1">
                              <Label className="text-xs">註記</Label>
                              <Textarea
                                className="min-h-20"
                                value={draftAsset.notes}
                                onChange={(event) => updateAssetDraft(asset, { notes: event.target.value })}
                                placeholder="告訴 AI 這張圖要參考什麼、不要參考什麼"
                              />
                            </div>
                          </div>

                          {asset.meta?.visualDescription || asset.content ? (
                            <p className="line-clamp-4 rounded-md bg-muted/60 p-2 text-xs leading-5">
                              {asset.meta?.visualDescription || asset.content}
                            </p>
                          ) : null}

                          <div className="flex flex-wrap gap-2">
                            <Button type="button" variant="outline" size="sm" disabled={Boolean(loading[asset.id])} onClick={() => saveAsset(asset)}>
                              <Save className="h-4 w-4" />
                              儲存註記
                            </Button>
                            <Button type="button" variant="outline" size="sm" disabled={Boolean(loading[asset.id])} onClick={() => reanalyze(asset.id)}>
                              {loading[asset.id] ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                              重新分析
                            </Button>
                            <Button type="button" variant="ghost" size="sm" disabled={Boolean(loading[asset.id])} onClick={() => deleteAsset(asset.id)}>
                              <Trash2 className="h-4 w-4" />
                              移除
                            </Button>
                          </div>
                        </article>
                      );
                    })}
                  </div>
                ) : (
                  <p className="rounded-md border border-dashed bg-muted/30 px-3 py-4 text-sm text-muted-foreground">
                    尚未上傳參考圖。建議至少補 2-4 張：正面、側面、細節、使用情境。
                  </p>
                )}
              </section>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}

function toReferenceKey(value: string) {
  return value
    .trim()
    .toLowerCase()
    .replace(/[\s/\\]+/g, "_")
    .replace(/[^a-z0-9_\-\u4e00-\u9fa5]+/g, "")
    .replace(/^_+|_+$/g, "")
    .slice(0, 64);
}
