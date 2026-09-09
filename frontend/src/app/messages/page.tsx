"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Search, Eye, Pencil, Trash2, ArrowDownUp } from "lucide-react";
import { api } from "@/lib/api";
import type { MessageListResponse, Topic } from "@/lib/types";
import { AppHeader } from "@/components/AppHeader";
import { SiBadge } from "@/components/SiBadge";
import { PageLayout } from "@/components/PageLayout";
import { useMe } from "@/lib/useMe";
import { formatCompactNumber, formatFullNumber } from "@/lib/numbers";

const TONE_LABELS: Record<string, string> = {
  positive: "Позитив",
  neutral: "Нейтрал",
  negative: "Негатив",
};

export default function MessagesPage() {
  const [page, setPage] = useState(1);
  const [department, setDepartment] = useState("");
  const [tone, setTone] = useState("");
  const [topicId, setTopicId] = useState<number | "">("");
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState<"created_at" | "updated_at" | "processed_at" | "si" | "views" | "title">("processed_at");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const queryClient = useQueryClient();
  const { data: user } = useMe();

  const { data: topics } = useQuery<Topic[]>({
    queryKey: ["topics"],
    queryFn: async () => (await api.get("/topics")).data,
  });

  const { data, isLoading } = useQuery<MessageListResponse>({
    queryKey: ["messages", page, department, tone, topicId, search, sortBy, sortDir],
    queryFn: async () =>
      (
        await api.get("/messages", {
          params: {
            page,
            page_size: 20,
            department: department || undefined,
            tone: tone || undefined,
            topic_id: topicId || undefined,
            search: search || undefined,
            sort_by: sortBy,
            sort_dir: sortDir,
          },
        })
      ).data,
  });

  async function handleDelete(id: number) {
    if (!confirm("Удалить инфоповод?")) return;
    await api.delete(`/messages/${id}`);
    queryClient.invalidateQueries({ queryKey: ["messages"] });
  }

  const messages = data?.items ?? [];
  const pageSize = data?.page_size ?? 20;
  const total = data?.total ?? 0;
  const hasNextPage = page * pageSize < total;

  return (
    <PageLayout user={user}>
      {/* Header */}
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-lg font-semibold">Публикации</h1>
        <Link
          href="/messages/create"
          className="btn primary"
        >
          <Plus className="h-4 w-4" />
          <span>Создать</span>
        </Link>
      </div>

      {/* Filters */}
      <div className="mb-4 rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative flex-1 min-w-[200px]">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              className="input pl-10"
              placeholder="Поиск по названию..."
              value={search}
              onChange={(e) => {
                setPage(1);
                setSearch(e.target.value);
              }}
            />
          </div>
          <input
            className="w-48"
            placeholder="Контент центр"
            value={department}
            onChange={(e) => {
              setPage(1);
              setDepartment(e.target.value);
            }}
          />
          <select
            className="w-40"
            value={tone}
            onChange={(e) => {
              setPage(1);
              setTone(e.target.value);
            }}
          >
            <option value="">Все тональности</option>
            <option value="positive">Позитив</option>
            <option value="neutral">Нейтрал</option>
            <option value="negative">Негатив</option>
          </select>
          <select
            className="w-48"
            value={topicId}
            onChange={(e) => {
              setPage(1);
              setTopicId(e.target.value ? Number(e.target.value) : "");
            }}
          >
            <option value="">Все темы</option>
            {topics?.map((t) => (
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
          </select>
          <div className="flex items-center gap-2">
            <ArrowDownUp className="h-4 w-4 text-slate-400" />
            <select
              className="w-48"
              value={sortBy}
              onChange={(e) => {
                setPage(1);
                setSortBy(e.target.value as typeof sortBy);
                if (e.target.value === "processed_at") setSortDir("asc");
              }}
            >
              <option value="created_at">Дата создания</option>
              <option value="processed_at">Дата обработки</option>
              <option value="si">SI</option>
              <option value="views">Просмотры</option>
              <option value="updated_at">Дата изменения</option>
              <option value="title">Название</option>
            </select>
            <select
              className="w-36"
              value={sortDir}
              onChange={(e) => {
                setPage(1);
                setSortDir(e.target.value as typeof sortDir);
              }}
            >
              <option value="desc">По убыванию</option>
              <option value="asc">По возрастанию</option>
            </select>
          </div>
        </div>
      </div>

      {/* Table */}
      <div className="rounded-xl border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-800">
        <div className="overflow-x-auto">
          <table className="w-full table-fixed text-sm">
            <thead className="table-header">
              <tr>
                <th className="w-10 table-header">ID</th>
                <th className="min-w-[120px] table-header">Контент центр</th>
                <th className="w-24 table-header">Формат</th>
                <th className="min-w-[200px] max-w-[300px] truncate table-header">Название</th>
                <th className="w-24 table-header">Тональность</th>
                <th className="min-w-[100px] truncate table-header">Темы</th>
                <th className="w-20 table-header">Si</th>
                <th className="w-28 table-header">Обработано</th>
                <th className="w-24 table-header">Просмотры</th>
                <th className="w-24 table-header">Создано</th>
                <th className="w-20 table-header">Действия</th>
              </tr>
            </thead>
            <tbody>
              {isLoading && (
                <tr>
                  <td colSpan={11} className="px-3 py-4 text-center text-slate-400">
                    Загрузка...
                  </td>
                </tr>
              )}
              {!isLoading && messages.length === 0 && (
                <tr>
                  <td colSpan={11} className="px-3 py-4 text-center text-slate-400">
                    Нет данных
                  </td>
                </tr>
              )}
              {messages.map((m) => (
                <tr key={m.id} className="border-t border-slate-200 transition-colors hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800/50">
                  <td className="table-cell">{m.id}</td>
                  <td className="table-cell truncate" title={m.department}>{m.department}</td>
                  <td className="table-cell truncate" title={m.content_format}>{m.content_format}</td>
                  <td className="table-cell">
                    <Link href={`/messages/${m.id}`} className="block truncate text-blue-600 hover:underline dark:text-blue-400">
                      {m.title}
                    </Link>
                  </td>
                  <td className="table-cell">
                    <span className="badge" style={{ backgroundColor: m.tone === "positive" ? "#ecfdf5" : m.tone === "negative" ? "#fef2f2" : "#f8fafc", color: m.tone === "positive" ? "#047857" : m.tone === "negative" ? "#991b1b" : "#475569" }}>
                      {TONE_LABELS[m.tone]}
                    </span>
                  </td>
                  <td className="table-cell truncate" title={m.topics.map((t) => t.name).join(", ")}>
                    {m.topics.map((t) => t.name).join(", ")}
                  </td>
                  <td className="table-cell">
                    <SiBadge value={m.si_total} />
                  </td>
                  <td className="table-cell text-slate-500">
                    {m.last_processed_at ? new Date(m.last_processed_at).toLocaleDateString("ru-RU") : "—"}
                  </td>
                  <td className="table-cell metric-cell" title={formatFullNumber(m.views_total)}>{formatCompactNumber(m.views_total)}</td>
                  <td className="table-cell text-slate-500">{new Date(m.created_at).toLocaleDateString("ru-RU")}</td>
                  <td className="table-cell">
                    <div className="flex gap-1">
                      <Link href={`/messages/${m.id}`} className="rounded p-1 text-slate-500 hover:bg-slate-100 hover:text-blue-600 dark:hover:bg-slate-700 dark:hover:text-blue-400">
                        <Eye className="h-4 w-4" />
                      </Link>
                      <Link href={`/messages/${m.id}/edit`} className="rounded p-1 text-slate-500 hover:bg-slate-100 hover:text-amber-600 dark:hover:bg-slate-700 dark:hover:text-amber-400">
                        <Pencil className="h-4 w-4" />
                      </Link>
                      <button onClick={() => handleDelete(m.id)} className="rounded p-1 text-slate-500 hover:bg-slate-100 hover:text-red-600 dark:hover:bg-slate-700 dark:hover:text-red-400">
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Pagination */}
      <div className="mt-4 flex items-center gap-2">
        <button
          disabled={page === 1}
          onClick={() => setPage((p) => Math.max(1, p - 1))}
          className="btn secondary disabled:opacity-40"
        >
          Назад
        </button>
        <span className="text-sm text-slate-600 dark:text-slate-400">Страница {page}</span>
        <button
          disabled={!hasNextPage}
          onClick={() => setPage((p) => p + 1)}
          className="btn secondary disabled:opacity-40"
        >
          Вперёд
        </button>
      </div>
    </PageLayout>
  );
}
