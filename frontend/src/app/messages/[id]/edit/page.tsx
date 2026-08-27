"use client";

import { useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { MessageDetail, Tone, Topic } from "@/lib/types";
import { PageLayout } from "@/components/PageLayout";
import { useMe } from "@/lib/useMe";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { LinkChipsInput } from "@/components/LinkChipsInput";
import { TopicMultiSelect } from "@/components/TopicMultiSelect";
import { TONE_CONFIG } from "@/lib/theme";

export default function EditMessagePage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const messageId = Number(params.id);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { data: user } = useMe();

  const [department, setDepartment] = useState("");
  const [tone, setTone] = useState<Tone>("neutral");
  const [title, setTitle] = useState("");
  const [contentFormat, setContentFormat] = useState("");
  const [topicIds, setTopicIds] = useState<number[]>([]);
  const [links, setLinks] = useState<string[]>([]);
  const [originalLinkIds, setOriginalLinkIds] = useState<Map<string, number>>(new Map());
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [uploadMessage, setUploadMessage] = useState<string | null>(null);

  const { data: message } = useQuery<MessageDetail>({
    queryKey: ["message", messageId],
    queryFn: async () => (await api.get(`/messages/${messageId}`)).data,
  });
  const { data: departments } = useQuery<string[]>({
    queryKey: ["content-centers"],
    queryFn: async () => (await api.get("/content-centers")).data,
  });
  const { data: formats } = useQuery<string[]>({
    queryKey: ["content-formats"],
    queryFn: async () => (await api.get("/content-formats")).data,
  });
  const { data: topics } = useQuery<Topic[]>({
    queryKey: ["topics"],
    queryFn: async () => (await api.get("/topics")).data,
  });

  useEffect(() => {
    if (!message) return;
    setDepartment(message.department);
    setTone(message.tone);
    setTitle(message.title);
    setContentFormat(message.content_format);
    setTopicIds(message.topics.map((t) => t.id));
    setLinks(message.links.map((l) => l.url_raw));
    setOriginalLinkIds(new Map(message.links.map((l) => [l.url_raw, l.id])));
  }, [message]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const linkIdsRemove = Array.from(originalLinkIds.entries())
        .filter(([url]) => !links.includes(url))
        .map(([, id]) => id);
      const linksAdd = links.filter((url) => !originalLinkIds.has(url));

      await api.patch(`/messages/${messageId}`, {
        department,
        tone,
        title,
        content_format: contentFormat,
        topic_ids: topicIds,
        links_add: linksAdd,
        link_ids_remove: linkIdsRemove,
      });
      router.push(`/messages/${messageId}`);
    } catch {
      setError("Не удалось сохранить изменения");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleFileUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadMessage(null);
    const formData = new FormData();
    formData.append("file", file);
    try {
      await api.post(`/messages/${messageId}/links/upload`, formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setUploadMessage("Файл загружен, ссылки добавлены.");
      router.refresh();
    } catch {
      setUploadMessage("Не удалось загрузить файл.");
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  if (!message) {
    return (
      <PageLayout user={user}>
        <p className="text-sm text-slate-500">Загрузка...</p>
      </PageLayout>
    );
  }

  return (
    <PageLayout user={user}>
      <div className="mb-4">
        <Link href={`/messages/${messageId}`} className="inline-flex items-center gap-2 text-sm text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-200">
          <ArrowLeft className="h-4 w-4" />
          Назад
        </Link>
        <h1 className="text-lg font-semibold">Редактировать публикацию #{messageId}</h1>
      </div>

      <form onSubmit={handleSubmit} className="mx-auto max-w-2xl space-y-6">
        {/* Basic info */}
        <div className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-800">
          <h2 className="section-heading">Основная информация</h2>
          <div className="space-y-4">
            <div className="space-y-1">
              <label className="text-sm font-medium text-slate-700 dark:text-slate-300">Контент центр</label>
              <select className="select" value={department} onChange={(e) => setDepartment(e.target.value)} required>
                {departments?.map((d) => (
                  <option key={d} value={d}>{d}</option>
                ))}
              </select>
            </div>

            <div className="space-y-1">
              <label className="text-sm font-medium text-slate-700 dark:text-slate-300">Тональность</label>
              <div className="flex gap-3">
                {(["positive", "neutral", "negative"] as Tone[]).map((t) => (
                  <label key={t} className="flex cursor-pointer items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm transition-colors hover:bg-slate-50 has-[:checked]:border-brand has-[:checked]:bg-brand/5 dark:border-slate-700 dark:hover:bg-slate-800">
                    <input type="radio" name="tone" checked={tone === t} onChange={() => setTone(t)} className="accent-brand" />
                    {TONE_CONFIG[t].label}
                  </label>
                ))}
              </div>
            </div>

            <div className="space-y-1">
              <label className="text-sm font-medium text-slate-700 dark:text-slate-300">Название</label>
              <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} required />
            </div>

            <div className="space-y-1">
              <label className="text-sm font-medium text-slate-700 dark:text-slate-300">Формат контента</label>
              <select className="select" value={contentFormat} onChange={(e) => setContentFormat(e.target.value)} required>
                {formats?.map((f) => (
                  <option key={f} value={f}>{f}</option>
                ))}
              </select>
            </div>
          </div>
        </div>

        {/* Topics */}
        <div className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-800">
          <h2 className="section-heading">Темы</h2>
          <TopicMultiSelect topics={topics ?? []} selectedIds={topicIds} onChange={setTopicIds} />
        </div>

        {/* Links */}
        <div className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-800">
          <h2 className="section-heading">Ссылки</h2>
          <LinkChipsInput links={links} onChange={setLinks} />
        </div>

        {/* File upload */}
        <div className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-800">
          <h2 className="section-heading">Загрузить файл со ссылками</h2>
          <p className="mb-3 text-sm text-slate-500">xlsx или csv — ссылки будут добавлены автоматически.</p>
          <input ref={fileInputRef} type="file" accept=".xlsx,.csv" onChange={handleFileUpload} />
          {uploadMessage && <p className="mt-2 text-sm text-emerald-600 dark:text-emerald-400">{uploadMessage}</p>}
        </div>

        {error && (
          <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-400">
            {error}
          </p>
        )}

        <div className="flex justify-end">
          <button type="submit" disabled={submitting} className="btn primary">
            {submitting ? "Сохранение..." : "Сохранить"}
          </button>
        </div>
      </form>
    </PageLayout>
  );
}
