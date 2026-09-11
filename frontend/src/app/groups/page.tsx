"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { api } from "@/lib/api";
import { PageLayout } from "@/components/PageLayout";
import { useMe } from "@/lib/useMe";
import {
  Plus, Trash2, RefreshCw, ExternalLink, FileText, Clock,
  Power, PowerOff, CheckCircle, XCircle, Rss, Eye,
} from "lucide-react";

const PLATFORMS = [
  { key: "all", label: "Все" },
  { key: "vk", label: "VK" },
  { key: "telegram", label: "Telegram" },
  { key: "youtube", label: "YouTube" },
  { key: "tiktok", label: "TikTok" },
  { key: "instagram", label: "Instagram" },
  { key: "dzen", label: "Дзен" },
  { key: "max", label: "MAX" },
  { key: "ok", label: "ОК" },
];

const PLATFORM_COLORS: Record<string, string> = {
  vk: "bg-blue-600", telegram: "bg-sky-500", youtube: "bg-red-600",
  tiktok: "bg-black", instagram: "bg-gradient-to-br from-purple-600 to-pink-500",
  dzen: "bg-orange-500", max: "bg-green-600", ok: "bg-orange-600",
};

interface Subscription {
  id: number;
  platform: string;
  source_url: string;
  source_id: string;
  name: string;
  screen_name: string;
  photo_url: string;
  is_active: boolean;
  backfill: boolean;
  backfill_completed: boolean;
  check_interval_minutes: number;
  last_checked_at: string | null;
  message_id: number | null;
  posts_count: number;
  active_posts_count: number;
  si_total: number;
  views_total: number;
  created_at: string;
}

interface SubPost {
  id: number;
  post_external_id: string;
  link_id: number | null;
  post_created_at: string;
  first_seen_at: string;
  is_tracking: boolean;
  likes: number;
  reposts: number;
  comments: number;
  views: number;
  si: number;
}

const INTERVAL_OPTIONS = [
  { label: "30 мин", value: 30 }, { label: "1 час", value: 60 },
  { label: "2 часа", value: 120 }, { label: "3 часа", value: 180 },
  { label: "5 часов", value: 300 }, { label: "6 часов", value: 360 },
  { label: "12 часов", value: 720 }, { label: "24 часа", value: 1440 },
];

export default function GroupsPage() {
  const { data: user } = useMe();
  const [subs, setSubs] = useState<Subscription[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("all");
  const [showAddForm, setShowAddForm] = useState(false);
  const [newUrl, setNewUrl] = useState("");
  const [newInterval, setNewInterval] = useState(300);
  const [newBackfill, setNewBackfill] = useState(false);
  const [adding, setAdding] = useState(false);
  const [selectedSub, setSelectedSub] = useState<number | null>(null);
  const [subPosts, setSubPosts] = useState<SubPost[]>([]);
  const [postsLoading, setPostsLoading] = useState(false);

  const fetchSubs = useCallback(async () => {
    try {
      setLoading(true);
      const { data } = await api.get("/subscriptions");
      setSubs(data);
      setError(null);
    } catch (err: any) {
      setError(err.response?.data?.detail || "Ошибка загрузки");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchSubs(); }, [fetchSubs]);

  const filtered = useMemo(() => {
    if (filter === "all") return subs;
    return subs.filter((s) => s.platform === filter);
  }, [subs, filter]);

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: subs.length };
    for (const s of subs) c[s.platform] = (c[s.platform] || 0) + 1;
    return c;
  }, [subs]);

  const handleAdd = async () => {
    if (!newUrl.trim()) return;
    try {
      setAdding(true);
      await api.post("/subscriptions", {
        source_url: newUrl.trim(),
        check_interval_minutes: newInterval,
        backfill: newBackfill,
      });
      setNewUrl(""); setNewBackfill(false); setShowAddForm(false);
      await fetchSubs();
    } catch (err: any) {
      setError(err.response?.data?.detail || "Ошибка добавления");
    } finally { setAdding(false); }
  };

  const handleDelete = async (id: number) => {
    if (!confirm("Удалить группу и все связанные данные?")) return;
    try {
      await api.delete(`/subscriptions/${id}`);
      if (selectedSub === id) setSelectedSub(null);
      await fetchSubs();
    } catch (err: any) { setError(err.response?.data?.detail || "Ошибка удаления"); }
  };

  const handleToggle = async (sub: Subscription) => {
    try {
      await api.patch(`/subscriptions/${sub.id}`, { is_active: !sub.is_active });
      await fetchSubs();
    } catch (err: any) { setError(err.response?.data?.detail || "Ошибка"); }
  };

  const handleCheckNow = async (id: number) => {
    try {
      await api.post(`/subscriptions/${id}/check-now`);
      setError(null);
      setTimeout(() => fetchSubs(), 3000);
    } catch (err: any) { setError(err.response?.data?.detail || "Ошибка"); }
  };

  const fetchPosts = async (subId: number) => {
    try {
      setPostsLoading(true); setSelectedSub(subId);
      const { data } = await api.get(`/subscriptions/${subId}/posts`);
      setSubPosts(data);
    } catch (err: any) { setError(err.response?.data?.detail || "Ошибка"); }
    finally { setPostsLoading(false); }
  };

  const fmtInterval = (m: number) => m < 60 ? `${m} мин` : m < 1440 ? `${Math.floor(m / 60)} ч` : `${Math.floor(m / 1440)} д`;
  const fmtAge = (d: string) => {
    const diff = Date.now() - new Date(d).getTime();
    const h = Math.floor(diff / 3600000), m = Math.floor((diff % 3600000) / 60000);
    if (h > 24) return `${Math.floor(h / 24)} д назад`;
    if (h > 0) return `${h} ч ${m} мин назад`;
    return `${m} мин назад`;
  };

  return (
    <PageLayout user={user}>
      <div>
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold">Группы</h1>
            <p className="text-sm text-slate-500">Мониторинг публикаций из соцсетей</p>
          </div>
          <button onClick={() => setShowAddForm(true)} className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 transition-colors">
            <Plus className="h-4 w-4" /> Добавить группу
          </button>
        </div>

        {/* Platform filter tabs */}
        <div className="mb-4 flex flex-wrap gap-1 border-b pb-2">
          {PLATFORMS.map((p) => (
            <button key={p.key} onClick={() => { setFilter(p.key); setSelectedSub(null); }}
              className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                filter === p.key
                  ? "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300"
                  : "text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
              }`}>
              {p.label}
              {counts[p.key] ? <span className="ml-1 text-xs opacity-60">({counts[p.key]})</span> : null}
            </button>
          ))}
        </div>

        {/* Add form modal */}
        {showAddForm && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
            <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl dark:bg-slate-800">
              <h2 className="mb-4 text-lg font-semibold">Добавить группу</h2>
              <div className="space-y-4">
                <div>
                  <label className="mb-1 block text-sm font-medium">Ссылка на паблик / канал / аккаунт</label>
                  <input type="text" value={newUrl} onChange={(e) => setNewUrl(e.target.value)}
                    placeholder="https://vk.com/public12345 или https://t.me/channel"
                    className="w-full rounded-lg border px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-700"
                    onKeyDown={(e) => e.key === "Enter" && handleAdd()} />
                  <p className="mt-1 text-xs text-slate-400">VK, Telegram, YouTube, TikTok, Instagram, Дзен, MAX, Одноклассники</p>
                </div>
                <div>
                  <label className="mb-1 block text-sm font-medium">Интервал проверки</label>
                  <select value={newInterval} onChange={(e) => setNewInterval(Number(e.target.value))}
                    className="w-full rounded-lg border px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-700">
                    {INTERVAL_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                </div>
                <div>
                  <label className="flex items-center gap-3 cursor-pointer">
                    <input type="checkbox" checked={newBackfill} onChange={(e) => setNewBackfill(e.target.checked)} className="h-4 w-4 rounded" />
                    <div>
                      <span className="text-sm font-medium">Загрузить все посты</span>
                      <p className="text-xs text-slate-500">Спарсить все доступные посты при добавлении</p>
                    </div>
                  </label>
                </div>
                <div className="flex justify-end gap-3">
                  <button onClick={() => { setShowAddForm(false); setNewUrl(""); setNewBackfill(false); }}
                    className="rounded-lg px-4 py-2 text-sm hover:bg-slate-100 dark:hover:bg-slate-700">Отмена</button>
                  <button onClick={handleAdd} disabled={adding || !newUrl.trim()}
                    className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
                    {adding ? "Добавление..." : "Добавить"}
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {error && (
          <div className="mb-4 rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-400">
            {error} <button onClick={() => setError(null)} className="ml-2 underline">Скрыть</button>
          </div>
        )}

        {loading ? (
          <div className="flex items-center justify-center py-12 text-slate-400">
            <RefreshCw className="mr-2 h-5 w-5 animate-spin" /> Загрузка...
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-slate-400">
            <Rss className="mb-4 h-12 w-12" />
            <p className="text-lg font-medium">{filter === "all" ? "Нет групп" : `Нет групп на ${PLATFORMS.find(p => p.key === filter)?.label}`}</p>
            <p className="text-sm">Нажмите &laquo;Добавить группу&raquo;</p>
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {filtered.map((sub) => (
              <div key={sub.id}
                className={`cursor-pointer rounded-xl border p-4 transition-all hover:shadow-md ${selectedSub === sub.id ? "border-blue-500 ring-2 ring-blue-500/20" : "border-slate-200 dark:border-slate-700"}`}
                onClick={() => fetchPosts(sub.id)}>
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    {sub.photo_url ? (
                      <img src={sub.photo_url} alt={sub.name} className="h-10 w-10 rounded-full object-cover" />
                    ) : (
                      <div className={`flex h-10 w-10 items-center justify-center rounded-full text-xs font-bold text-white ${PLATFORM_COLORS[sub.platform] || "bg-slate-400"}`}>
                        {sub.name.charAt(0).toUpperCase()}
                      </div>
                    )}
                    <div>
                      <h3 className="font-medium leading-tight">{sub.name}</h3>
                      <span className="flex items-center gap-1 text-xs text-slate-500">
                        <span className={`inline-block h-2 w-2 rounded-full ${PLATFORM_COLORS[sub.platform] || "bg-slate-400"}`} />
                        {PLATFORMS.find(p => p.key === sub.platform)?.label || sub.platform}
                      </span>
                    </div>
                  </div>
                  <button onClick={(e) => { e.stopPropagation(); handleToggle(sub); }}
                    className={`rounded p-1 transition-colors ${sub.is_active ? "text-green-600 hover:bg-green-50" : "text-slate-400 hover:bg-slate-100"}`}
                    title={sub.is_active ? "Остановить" : "Запустить"}>
                    {sub.is_active ? <Power className="h-4 w-4" /> : <PowerOff className="h-4 w-4" />}
                  </button>
                </div>

                <div className="mt-3 flex flex-wrap gap-3 text-xs text-slate-500">
                  <span className="flex items-center gap-1"><FileText className="h-3 w-3" />{sub.posts_count} постов</span>
                  {sub.si_total > 0 && (
                    <span className="rounded-full bg-blue-100 px-2 py-0.5 font-medium text-blue-700 dark:bg-blue-900/30 dark:text-blue-300">
                      Si {sub.si_total.toLocaleString()}
                    </span>
                  )}
                  {sub.views_total > 0 && (
                    <span className="flex items-center gap-1"><Eye className="h-3 w-3" />{sub.views_total.toLocaleString()}</span>
                  )}
                  <span className="flex items-center gap-1"><Clock className="h-3 w-3" />{fmtInterval(sub.check_interval_minutes)}</span>
                  {sub.active_posts_count > 0 && (
                    <span className="rounded-full bg-green-100 px-2 py-0.5 text-green-700 dark:bg-green-900/30 dark:text-green-400">
                      {sub.active_posts_count} активных
                    </span>
                  )}
                </div>

                {sub.last_checked_at && <p className="mt-2 text-xs text-slate-400">Проверено: {fmtAge(sub.last_checked_at)}</p>}

                <div className="mt-3 flex gap-2">
                  <button onClick={(e) => { e.stopPropagation(); handleCheckNow(sub.id); }}
                    className="flex items-center gap-1 rounded-lg bg-slate-100 px-3 py-1.5 text-xs font-medium hover:bg-slate-200 dark:bg-slate-700 dark:hover:bg-slate-600">
                    <RefreshCw className="h-3 w-3" /> Проверить
                  </button>
                  {sub.message_id && (
                    <a href={`/messages/${sub.message_id}`} onClick={(e) => e.stopPropagation()}
                      className="flex items-center gap-1 rounded-lg bg-slate-100 px-3 py-1.5 text-xs font-medium hover:bg-slate-200 dark:bg-slate-700 dark:hover:bg-slate-600">
                      <ExternalLink className="h-3 w-3" /> Публикация
                    </a>
                  )}
                  <a href={sub.source_url} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()}
                    className="flex items-center gap-1 rounded-lg bg-slate-100 px-3 py-1.5 text-xs font-medium hover:bg-slate-200 dark:bg-slate-700 dark:hover:bg-slate-600">
                    <ExternalLink className="h-3 w-3" /> Источник
                  </a>
                  <button onClick={(e) => { e.stopPropagation(); handleDelete(sub.id); }}
                    className="flex items-center gap-1 rounded-lg bg-red-50 px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-100 dark:bg-red-900/20 dark:text-red-400">
                    <Trash2 className="h-3 w-3" /> Удалить
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Posts section */}
        {selectedSub && (
          <div className="mt-6 rounded-xl border p-4 dark:border-slate-700">
            <h3 className="mb-3 font-medium">Посты</h3>
            {postsLoading ? (
              <div className="flex items-center justify-center py-8 text-slate-400">
                <RefreshCw className="mr-2 h-4 w-4 animate-spin" /> Загрузка...
              </div>
            ) : subPosts.length === 0 ? (
              <p className="py-8 text-center text-sm text-slate-400">Посты пока не найдены</p>
            ) : (
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {subPosts.map((post) => (
                  <div key={post.id} className="rounded-lg border p-3 text-sm dark:border-slate-700">
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-slate-500 truncate">{post.post_external_id}</span>
                      {post.is_tracking ? (
                        <span className="flex items-center gap-1 text-xs text-green-600"><CheckCircle className="h-3 w-3" /> Трекинг</span>
                      ) : (
                        <span className="flex items-center gap-1 text-xs text-slate-400"><XCircle className="h-3 w-3" /> Завершён</span>
                      )}
                    </div>
                    {(post.likes > 0 || post.reposts > 0 || post.views > 0 || post.si > 0) && (
                      <div className="mt-2 flex flex-wrap gap-2 text-xs">
                        {post.si > 0 && <span className="rounded bg-blue-100 px-1.5 py-0.5 font-medium text-blue-700 dark:bg-blue-900/30 dark:text-blue-300">Si {post.si}</span>}
                        {post.likes > 0 && <span className="text-slate-500">👍 {post.likes}</span>}
                        {post.reposts > 0 && <span className="text-slate-500">🔄 {post.reposts}</span>}
                        {post.views > 0 && <span className="text-slate-500">👁 {post.views}</span>}
                      </div>
                    )}
                    <p className="mt-1 text-xs text-slate-400">{post.post_created_at ? fmtAge(post.post_created_at) : "—"}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </PageLayout>
  );
}
