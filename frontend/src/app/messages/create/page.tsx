"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Tone, Topic } from "@/lib/types";
import { PageLayout } from "@/components/PageLayout";
import { useMe } from "@/lib/useMe";
import { ArrowLeft, Upload } from "lucide-react";
import Link from "next/link";
import { LinkChipsInput } from "@/components/LinkChipsInput";
import { TopicMultiSelect } from "@/components/TopicMultiSelect";
import { TONE_CONFIG } from "@/lib/theme";

export default function CreateMessagePage() {
  const router = useRouter();
  const { data: user } = useMe();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [department, setDepartment] = useState("");
  const [tone, setTone] = useState<Tone>("neutral");
  const [title, setTitle] = useState("");
  const [contentFormat, setContentFormat] = useState("");
  const [topicIds, setTopicIds] = useState<number[]>([]);
  const [links, setLinks] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [uploadMessage, setUploadMessage] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [submitting, setSubmitting] = useState(false);

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

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (links.length > 10_000) {
      setError("Превышен лимит 10 000 ссылок");
      return;
    }
    setSubmitting(true);
    try {
      const { data } = await api.post("/messages", {
        department,
        tone,
        title,
        content_format: contentFormat,
        topic_ids: topicIds,
        links,
      });
      router.push(`/messages/${data.id}`);
    } catch {
      setError("Не удалось создать инфоповод");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleFileUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setError(null);
    setUploadMessage(null);
    setUploading(true);
    const formData = new FormData();
    formData.append("file", file);
    try {
      const { data } = await api.post<{ links: string[]; added: number; skipped: number }>("/messages/links/parse", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setLinks((current) => {
        const seen = new Set(current);
        return [...current, ...data.links.filter((link) => {
          if (seen.has(link)) return false;
          seen.add(link);
          return true;
        })];
      });
      setUploadMessage(`Добавлено ссылок: ${data.added}. Пропущено: ${data.skipped}.`);
    } catch {
      setUploadMessage("Не удалось загрузить файл.");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  return (
    <PageLayout user={user}>
      <div className="mb-4">
        <Link href="/messages" className="inline-flex items-center gap-2 text-sm text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-200">
          <ArrowLeft className="h-4 w-4" />
          Назад к публикациям
        </Link>
        <h1 className="text-lg font-semibold">Создать публикацию</h1>
      </div>

      <form onSubmit={handleSubmit} className="mx-auto max-w-2xl space-y-6">
        {/* Basic info */}
        <div className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-800">
          <h2 className="section-heading">Основная информация</h2>
          <div className="space-y-4">
            <div className="space-y-1">
              <label className="text-sm font-medium text-slate-700 dark:text-slate-300">Контент центр</label>
              <select
                className="select"
                value={department}
                onChange={(e) => setDepartment(e.target.value)}
                required
              >
                <option value="" disabled>Выберите...</option>
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
                    <input
                      type="radio"
                      name="tone"
                      checked={tone === t}
                      onChange={() => setTone(t)}
                      className="accent-brand"
                    />
                    {TONE_CONFIG[t].label}
                  </label>
                ))}
              </div>
            </div>

            <div className="space-y-1">
              <label className="text-sm font-medium text-slate-700 dark:text-slate-300">Название</label>
              <input
                className="input"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                required
              />
            </div>

            <div className="space-y-1">
              <label className="text-sm font-medium text-slate-700 dark:text-slate-300">Формат контента</label>
              <select
                className="select"
                value={contentFormat}
                onChange={(e) => setContentFormat(e.target.value)}
                required
              >
                <option value="" disabled>Выберите...</option>
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
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <label className="btn secondary cursor-pointer">
              <Upload className="h-4 w-4" />
              {uploading ? "Загрузка..." : "Импорт xlsx/csv"}
              <input ref={fileInputRef} type="file" accept=".xlsx,.csv" onChange={handleFileUpload} className="hidden" disabled={uploading} />
            </label>
            {uploadMessage && <span className="text-sm text-slate-500">{uploadMessage}</span>}
          </div>
        </div>

        {error && (
          <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-400">
            {error}
          </p>
        )}

        <div className="flex justify-end">
          <button type="submit" disabled={submitting} className="btn primary">
            {submitting ? "Создание..." : "Создать"}
          </button>
        </div>
      </form>
    </PageLayout>
  );
}
