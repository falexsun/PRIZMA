"use client";

import { useState, useMemo } from "react";
import { useParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { MessageDetail, Platform } from "@/lib/types";
import { useMessageSocket } from "@/lib/useMessageSocket";
import { AppHeader } from "@/components/AppHeader";
import { SiBadge } from "@/components/SiBadge";
import { PageLayout } from "@/components/PageLayout";
import { useMe } from "@/lib/useMe";
import {
  ArrowLeft,
  RefreshCw,
  ThumbsUp,
  Repeat,
  MessageCircle,
  Bookmark,
  Eye,
  ExternalLink,
  Pencil,
  Search,
  Download,
} from "lucide-react";
import Link from "next/link";
import { TONE_CONFIG, PLATFORM_LABELS } from "@/lib/theme";
import { formatCompactNumber, formatFullNumber } from "@/lib/numbers";
import clsx from "clsx";

export default function MessageCardPage() {
  const params = useParams<{ id: string }>();
  const messageId = Number(params.id);
  const queryClient = useQueryClient();
  const [selectedLinkIds, setSelectedLinkIds] = useState<Set<number>>(new Set());
  const [refreshing, setRefreshing] = useState(false);
  const [refreshingSelected, setRefreshingSelected] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [refreshingLinkIds, setRefreshingLinkIds] = useState<Set<number>>(new Set());
  const [search, setSearch] = useState("");
  const [platformFilter, setPlatformFilter] = useState<Platform | "">("");
  const [hashtagFilter, setHashtagFilter] = useState("");
  const { data: user } = useMe();
  useMessageSocket(messageId);

  const { data: message, isLoading } = useQuery<MessageDetail>({
    queryKey: ["message", messageId],
    queryFn: async () => (await api.get(`/messages/${messageId}`)).data,
  });

  const filteredLinks = useMemo(() => {
    if (!message) return [];
    let links = message.links;
    if (platformFilter) {
      links = links.filter((l) => l.platform === platformFilter);
    }
    if (hashtagFilter) {
      const tag = hashtagFilter.toLowerCase();
      links = links.filter((l) => l.hashtags.toLowerCase().split(",").some((h) => h.trim() === tag));
    }
    if (search) {
      const q = search.toLowerCase();
      links = links.filter((l) => l.url_raw.toLowerCase().includes(q) || l.url_normalized.toLowerCase().includes(q));
    }
    return links;
  }, [message, search, platformFilter, hashtagFilter]);

  const uniquePlatforms = useMemo(() => {
    if (!message) return [];
    const set = new Set(message.links.map((l) => l.platform));
    return Array.from(set).sort();
  }, [message]);

  const allHashtags = useMemo(() => {
    if (!message) return [];
    const set = new Set<string>();
    for (const link of message.links) {
      if (link.hashtags) {
        for (const h of link.hashtags.split(",")) {
          const trimmed = h.trim();
          if (trimmed) set.add(trimmed);
        }
      }
    }
    return Array.from(set).sort();
  }, [message]);

  function toggleAll() {
    setSelectedLinkIds((prev) =>
      prev.size === filteredLinks.length ? new Set() : new Set(filteredLinks.map((l) => l.id))
    );
  }

  function toggleOne(id: number) {
    setSelectedLinkIds((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  async function handleRefresh() {
    setRefreshing(true);
    try {
      await api.post(`/messages/${messageId}/refresh-metrics`);
      await queryClient.invalidateQueries({ queryKey: ["message", messageId] });
    } finally {
      setRefreshing(false);
    }
  }

  async function handleExportMetrics() {
    setExporting(true);
    try {
      const response = await api.get(`/messages/${messageId}/metrics/export`, {
        responseType: "blob",
      });
      const blob = new Blob([response.data], {
        type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `message_${messageId}_metrics.xlsx`;
      a.click();
      window.URL.revokeObjectURL(url);
    } finally {
      setExporting(false);
    }
  }

  async function handleRefreshLink(linkId: number) {
    setRefreshingLinkIds((prev) => new Set(prev).add(linkId));
    try {
      await api.post(`/messages/${messageId}/links/${linkId}/refresh-now`);
      await queryClient.invalidateQueries({ queryKey: ["message", messageId] });
      await queryClient.invalidateQueries({ queryKey: ["messages"] });
    } finally {
      setRefreshingLinkIds((prev) => {
        const next = new Set(prev);
        next.delete(linkId);
        return next;
      });
    }
  }

  async function handleRefreshSelected() {
    const linkIds = selectedLinkIds.size > 0 ? Array.from(selectedLinkIds) : filteredLinks.map((link) => link.id);
    if (linkIds.length === 0) return;

    setRefreshingSelected(true);
    setRefreshingLinkIds((prev) => new Set([...prev, ...linkIds]));
    try {
      for (const linkId of linkIds) {
        await api.post(`/messages/${messageId}/links/${linkId}/refresh-now`);
      }
      await queryClient.invalidateQueries({ queryKey: ["message", messageId] });
      await queryClient.invalidateQueries({ queryKey: ["messages"] });
    } finally {
      setRefreshingSelected(false);
      setRefreshingLinkIds((prev) => {
        const next = new Set(prev);
        for (const linkId of linkIds) next.delete(linkId);
        return next;
      });
    }
  }

  async function handleDeleteSelected() {
    const linkIds = selectedLinkIds.size > 0 ? Array.from(selectedLinkIds) : filteredLinks.map((link) => link.id);
    if (!message || linkIds.length === 0) return;
    const scope = selectedLinkIds.size > 0 ? "выбранные" : "найденные";
    if (!confirm(`Удалить ${scope} ссылки (${linkIds.length})?`)) return;
    await api.patch(`/messages/${messageId}`, {
      link_ids_remove: linkIds,
    });
    setSelectedLinkIds(new Set());
    queryClient.invalidateQueries({ queryKey: ["message", messageId] });
  }

  if (isLoading || !message) {
    return (
      <PageLayout user={user}>
        <p className="text-sm text-slate-500">Загрузка...</p>
      </PageLayout>
    );
  }

  const sumLikes = filteredLinks.reduce((s, l) => s + (l.latest_metrics?.likes ?? 0), 0);
  const sumReposts = filteredLinks.reduce((s, l) => s + (l.latest_metrics?.reposts ?? 0), 0);
  const sumComments = filteredLinks.reduce((s, l) => s + (l.latest_metrics?.comments ?? 0), 0);
  const sumSaves = filteredLinks.reduce((s, l) => s + (l.latest_metrics?.saves ?? 0), 0);
  const sumViews = filteredLinks.reduce((s, l) => s + (l.latest_metrics?.views ?? 0), 0);
  const actionLinkIds = selectedLinkIds.size > 0 ? Array.from(selectedLinkIds) : filteredLinks.map((link) => link.id);
  const actionLinksCount = actionLinkIds.length;
  const actionScopeLabel = selectedLinkIds.size > 0 ? "выбранные" : "найденные";
  const formatReposts = (link: MessageDetail["links"][number]) =>
    link.platform === "instagram" && link.url_normalized.includes("/reel/") && link.latest_metrics?.reposts === 0
      ? "—"
      : formatCompactNumber(link.latest_metrics?.reposts);

  return (
    <PageLayout user={user}>
      {/* Back + Actions */}
      <div className="mb-4 flex items-center justify-between">
        <Link href="/messages" className="inline-flex items-center gap-2 text-sm text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-200">
          <ArrowLeft className="h-4 w-4" />
          Назад к публикациям
        </Link>
        <div className="flex items-center gap-2">
          <Link href={`/messages/${messageId}/edit`}>
            <button className="btn secondary">
              <Pencil className="h-4 w-4" />
              Редактировать
            </button>
          </Link>
          <button onClick={handleExportMetrics} disabled={exporting} className="btn secondary">
            <Download className="h-4 w-4" />
            {exporting ? "Экспорт..." : "Excel"}
          </button>
          <button onClick={handleRefresh} disabled={refreshing} className="btn primary">
            <RefreshCw className={clsx("h-4 w-4", refreshing && "animate-spin")} />
            {refreshing ? "Обновление..." : "Обновить метрики"}
          </button>
        </div>
      </div>

      {/* Info card */}
      <div className="mb-4 rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-800">
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-lg font-semibold">{message.title}</h1>
            <p className="mt-1 text-sm text-slate-500">
              {message.department} · {message.content_format}
            </p>
            <div className="mt-2 flex items-center gap-2">
              <span className="badge" style={{ backgroundColor: TONE_CONFIG[message.tone].color === "positive" ? "#ecfdf5" : TONE_CONFIG[message.tone].color === "negative" ? "#fef2f2" : "#f8fafc", color: TONE_CONFIG[message.tone].color === "positive" ? "#047857" : TONE_CONFIG[message.tone].color === "negative" ? "#991b1b" : "#475569" }}>
                {TONE_CONFIG[message.tone].label}
              </span>
              {message.topics.map((t) => (
                <span key={t.id} className="badge neutral">
                  {t.name}
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Stats */}
      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="stat-card">
          <div className="stat-value text-emerald-600 dark:text-emerald-400" title={formatFullNumber(message.si_total)}>
            {formatCompactNumber(message.si_total)}
          </div>
          <div className="stat-label">Si</div>
        </div>
        <div className="stat-card">
          <div className="stat-value" title={formatFullNumber(sumViews)}>{formatCompactNumber(sumViews)}</div>
          <div className="stat-label">Просмотры</div>
        </div>
        <div className="stat-card">
          <div className="stat-value" title={formatFullNumber(sumLikes)}>{formatCompactNumber(sumLikes)}</div>
          <div className="stat-label flex items-center gap-1">
            <ThumbsUp className="h-3 w-3" /> Лайки
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-value" title={formatFullNumber(sumReposts)}>{formatCompactNumber(sumReposts)}</div>
          <div className="stat-label flex items-center gap-1">
            <Repeat className="h-3 w-3" /> Репосты
          </div>
        </div>
      </div>
      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-2">
        <div className="stat-card">
          <div className="stat-value" title={formatFullNumber(sumComments)}>{formatCompactNumber(sumComments)}</div>
          <div className="stat-label flex items-center gap-1">
            <MessageCircle className="h-3 w-3" /> Комментарии
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-value" title={formatFullNumber(sumSaves)}>{formatCompactNumber(sumSaves)}</div>
          <div className="stat-label flex items-center gap-1">
            <Bookmark className="h-3 w-3" /> Сохранения
          </div>
        </div>
      </div>

      {/* Links filter */}
      <div className="mb-4 rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative flex-1 min-w-[200px]">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              className="input pl-10"
              placeholder="Поиск по URL..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <select
            className="w-48"
            value={platformFilter}
            onChange={(e) => setPlatformFilter(e.target.value as Platform | "")}
          >
            <option value="">Все платформы</option>
            {uniquePlatforms.map((p) => (
              <option key={p} value={p}>{PLATFORM_LABELS[p] ?? p}</option>
            ))}
          </select>
          <select
            className="w-48"
            value={hashtagFilter}
            onChange={(e) => setHashtagFilter(e.target.value)}
          >
            <option value="">Все хэштеги</option>
            {allHashtags.map((h) => (
              <option key={h} value={h}>#{h}</option>
            ))}
          </select>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleRefreshSelected}
              disabled={actionLinksCount === 0 || refreshingSelected}
              className="btn secondary"
              title={selectedLinkIds.size > 0 ? "Обновить отмеченные ссылки" : "Обновить все ссылки, которые сейчас показаны"}
            >
              <RefreshCw className={clsx("h-4 w-4", refreshingSelected && "animate-spin")} />
              {refreshingSelected ? "Обновляем..." : `Обновить ${actionScopeLabel} (${actionLinksCount})`}
            </button>
            <button
              type="button"
              onClick={handleDeleteSelected}
              disabled={actionLinksCount === 0 || refreshingSelected}
              className="btn secondary text-red-600 hover:text-red-700 dark:text-red-400 dark:hover:text-red-300"
              title={selectedLinkIds.size > 0 ? "Удалить отмеченные ссылки" : "Удалить все ссылки, которые сейчас показаны"}
            >
              Удалить {actionScopeLabel} ({actionLinksCount})
            </button>
          </div>
        </div>
      </div>

      {/* Links table */}
      <div className="rounded-xl border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-800">
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3 dark:border-slate-700">
          <h2 className="section-heading mb-0">Ссылки ({filteredLinks.length}{filteredLinks.length !== message.links.length ? ` из ${message.links.length}` : ""})</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full table-fixed text-sm">
            <thead className="table-header">
              <tr>
                <th className="w-8 table-header">
                  <input
                    type="checkbox"
                    checked={selectedLinkIds.size === filteredLinks.length && filteredLinks.length > 0}
                    onChange={toggleAll}
                  />
                </th>
                <th className="w-8 table-header">#</th>
                <th className="min-w-[200px] max-w-[300px] truncate table-header">URL</th>
                <th className="w-24 table-header">Платформа</th>
                <th className="min-w-[120px] table-header">Хэштеги</th>
                <th className="w-16 whitespace-nowrap table-header">Лайки</th>
                <th className="w-20 whitespace-nowrap table-header">Репосты</th>
                <th className="w-24 whitespace-nowrap table-header">Комменты</th>
                <th className="w-28 whitespace-nowrap table-header">Сохранения</th>
                <th className="w-24 whitespace-nowrap table-header">Просмотры</th>
                <th className="w-14 whitespace-nowrap table-header">Si</th>
                <th className="w-32 whitespace-nowrap table-header">Обновлено</th>
                <th className="w-16 whitespace-nowrap table-header"></th>
              </tr>
            </thead>
            <tbody>
              {filteredLinks.length === 0 && (
                <tr>
                  <td colSpan={13} className="px-3 py-4 text-center text-slate-400">
                    {search || platformFilter || hashtagFilter ? "Нет ссылок, соответствующих фильтрам" : "Нет ссылок"}
                  </td>
                </tr>
              )}
              {filteredLinks.map((link, idx) => (
                <tr key={link.id} className="border-t border-slate-200 transition-colors hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800/50">
                  <td className="table-cell">
                    <input
                      type="checkbox"
                      checked={selectedLinkIds.has(link.id)}
                      onChange={() => toggleOne(link.id)}
                    />
                  </td>
                  <td className="table-cell text-slate-400">{idx + 1}</td>
                  <td className="table-cell">
                    <a href={link.url_raw} target="_blank" rel="noopener noreferrer" className="block truncate text-blue-600 hover:underline dark:text-blue-400">
                      <span className="inline-flex items-center gap-1">
                        {link.url_raw}
                        <ExternalLink className="h-3 w-3 shrink-0" />
                      </span>
                    </a>
                  </td>
                  <td className="table-cell">
                    <span className="badge neutral">{PLATFORM_LABELS[link.platform] ?? link.platform}</span>
                  </td>
                  <td className="table-cell">
                    <div className="flex flex-wrap gap-1">
                      {link.hashtags ? link.hashtags.split(",").map((h) => (
                        <span key={h} className="badge neutral text-xs">#{h.trim()}</span>
                      )) : "—"}
                    </div>
                  </td>
                  <td className="table-cell metric-cell" title={formatFullNumber(link.latest_metrics?.likes)}>{formatCompactNumber(link.latest_metrics?.likes)}</td>
                  <td className="table-cell metric-cell" title={formatFullNumber(link.latest_metrics?.reposts)}>{formatReposts(link)}</td>
                  <td className="table-cell metric-cell" title={formatFullNumber(link.latest_metrics?.comments)}>{formatCompactNumber(link.latest_metrics?.comments)}</td>
                  <td className="table-cell metric-cell" title={formatFullNumber(link.latest_metrics?.saves)}>{formatCompactNumber(link.latest_metrics?.saves)}</td>
                  <td className="table-cell metric-cell" title={formatFullNumber(link.latest_metrics?.views)}>{formatCompactNumber(link.latest_metrics?.views)}</td>
                  <td className="table-cell"><SiBadge value={link.latest_metrics?.si ?? 0} /></td>
                  <td className="table-cell text-slate-500">
                    {link.latest_metrics ? new Date(link.latest_metrics.fetched_at).toLocaleString("ru-RU") : "—"}
                  </td>
                  <td className="table-cell">
                    <button
                      type="button"
                      onClick={() => handleRefreshLink(link.id)}
                      disabled={refreshingLinkIds.has(link.id)}
                      className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-slate-300 text-slate-600 hover:bg-slate-50 disabled:opacity-60 dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-700"
                      title="Обновить эту ссылку сейчас"
                    >
                      <RefreshCw className={clsx("h-4 w-4", refreshingLinkIds.has(link.id) && "animate-spin")} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </PageLayout>
  );
}
