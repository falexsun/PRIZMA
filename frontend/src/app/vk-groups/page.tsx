"use client";

import { useEffect, useState, useCallback } from "react";
import { api } from "@/lib/api";
import { PageLayout } from "@/components/PageLayout";
import { useMe } from "@/lib/useMe";
import {
  Plus,
  Trash2,
  RefreshCw,
  ExternalLink,
  Users,
  FileText,
  Clock,
  Power,
  PowerOff,
  CheckCircle,
  XCircle,
} from "lucide-react";

interface VKGroup {
  id: number;
  vk_group_id: number;
  name: string;
  screen_name: string;
  photo_url: string;
  is_active: boolean;
  check_interval_minutes: number;
  last_checked_at: string | null;
  message_id: number | null;
  posts_count: number;
  active_posts_count: number;
  created_at: string;
}

interface VKGroupPost {
  id: number;
  post_external_id: string;
  link_id: number | null;
  post_created_at: string;
  first_seen_at: string;
  is_tracking: boolean;
}

const INTERVAL_OPTIONS = [
  { label: "30 мин", value: 30 },
  { label: "1 час", value: 60 },
  { label: "2 часа", value: 120 },
  { label: "3 часа", value: 180 },
  { label: "5 часов", value: 300 },
  { label: "6 часов", value: 360 },
  { label: "12 часов", value: 720 },
  { label: "24 часа", value: 1440 },
];

export default function VKGroupsPage() {
  const { data: user } = useMe();
  const [groups, setGroups] = useState<VKGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showAddForm, setShowAddForm] = useState(false);
  const [newGroupUrl, setNewGroupUrl] = useState("");
  const [newGroupInterval, setNewGroupInterval] = useState(300);
  const [newGroupBackfill, setNewGroupBackfill] = useState(false);
  const [adding, setAdding] = useState(false);
  const [selectedGroup, setSelectedGroup] = useState<number | null>(null);
  const [groupPosts, setGroupPosts] = useState<VKGroupPost[]>([]);
  const [postsLoading, setPostsLoading] = useState(false);

  const fetchGroups = useCallback(async () => {
    try {
      setLoading(true);
      const { data } = await api.get("/vk-groups");
      setGroups(data);
      setError(null);
    } catch (err: any) {
      setError(err.response?.data?.detail || "Ошибка загрузки групп");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchGroups();
  }, [fetchGroups]);

  const handleAdd = async () => {
    if (!newGroupUrl.trim()) return;
    try {
      setAdding(true);
      await api.post("/vk-groups", {
        vk_group_url: newGroupUrl.trim(),
        check_interval_minutes: newGroupInterval,
        backfill: newGroupBackfill,
      });
      setNewGroupUrl("");
      setNewGroupBackfill(false);
      setShowAddForm(false);
      await fetchGroups();
    } catch (err: any) {
      setError(err.response?.data?.detail || "Ошибка добавления группы");
    } finally {
      setAdding(false);
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm("Удалить группу и все связанные данные?")) return;
    try {
      await api.delete(`/vk-groups/${id}`);
      if (selectedGroup === id) setSelectedGroup(null);
      await fetchGroups();
    } catch (err: any) {
      setError(err.response?.data?.detail || "Ошибка удаления");
    }
  };

  const handleToggleActive = async (group: VKGroup) => {
    try {
      await api.patch(`/vk-groups/${group.id}`, {
        is_active: !group.is_active,
      });
      await fetchGroups();
    } catch (err: any) {
      setError(err.response?.data?.detail || "Ошибка обновления");
    }
  };

  const handleCheckNow = async (id: number) => {
    try {
      await api.post(`/vk-groups/${id}/check-now`);
      setError(null);
      // Show brief success
      setTimeout(() => fetchGroups(), 3000);
    } catch (err: any) {
      setError(err.response?.data?.detail || "Ошибка запуска проверки");
    }
  };

  const fetchPosts = async (groupId: number) => {
    try {
      setPostsLoading(true);
      setSelectedGroup(groupId);
      const { data } = await api.get(`/vk-groups/${groupId}/posts`);
      setGroupPosts(data);
    } catch (err: any) {
      setError(err.response?.data?.detail || "Ошибка загрузки постов");
    } finally {
      setPostsLoading(false);
    }
  };

  const formatInterval = (minutes: number) => {
    if (minutes < 60) return `${minutes} мин`;
    if (minutes < 1440) return `${Math.floor(minutes / 60)} ч`;
    return `${Math.floor(minutes / 1440)} д`;
  };

  const formatAge = (dateStr: string) => {
    const now = new Date();
    const date = new Date(dateStr);
    const diffMs = now.getTime() - date.getTime();
    const hours = Math.floor(diffMs / 3600000);
    const mins = Math.floor((diffMs % 3600000) / 60000);
    if (hours > 24) return `${Math.floor(hours / 24)} д назад`;
    if (hours > 0) return `${hours} ч ${mins} мин назад`;
    return `${mins} мин назад`;
  };

  return (
    <PageLayout user={user}>
      <div>
        {/* Header */}
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold">VK Группы</h1>
            <p className="text-sm text-slate-500">
              Автоматический мониторинг постов из пабликов ВКонтакте
            </p>
          </div>
          <button
            onClick={() => setShowAddForm(true)}
            className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 transition-colors"
          >
            <Plus className="h-4 w-4" />
            Добавить группу
          </button>
        </div>

        {/* Add form modal */}
        {showAddForm && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
            <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl dark:bg-slate-800">
              <h2 className="mb-4 text-lg font-semibold">Добавить VK группу</h2>
              <div className="space-y-4">
                <div>
                  <label className="mb-1 block text-sm font-medium">
                    Ссылка на группу или ID
                  </label>
                  <input
                    type="text"
                    value={newGroupUrl}
                    onChange={(e) => setNewGroupUrl(e.target.value)}
                    placeholder="https://vk.com/public12345 или club12345"
                    className="w-full rounded-lg border px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-700"
                    onKeyDown={(e) => e.key === "Enter" && handleAdd()}
                  />
                </div>
                <div>
                  <label className="mb-1 block text-sm font-medium">
                    Интервал проверки
                  </label>
                  <select
                    value={newGroupInterval}
                    onChange={(e) => setNewGroupInterval(Number(e.target.value))}
                    className="w-full rounded-lg border px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-700"
                  >
                    {INTERVAL_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="flex items-center gap-3 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={newGroupBackfill}
                      onChange={(e) => setNewGroupBackfill(e.target.checked)}
                      className="h-4 w-4 rounded border-slate-300"
                    />
                    <div>
                      <span className="text-sm font-medium">Загрузить все посты</span>
                      <p className="text-xs text-slate-500">
                        Спарсить все доступные посты со стены группы при добавлении
                      </p>
                    </div>
                  </label>
                </div>
                <div className="flex justify-end gap-3">
                  <button
                    onClick={() => {
                      setShowAddForm(false);
                      setNewGroupUrl("");
                      setNewGroupBackfill(false);
                    }}
                    className="rounded-lg px-4 py-2 text-sm hover:bg-slate-100 dark:hover:bg-slate-700"
                  >
                    Отмена
                  </button>
                  <button
                    onClick={handleAdd}
                    disabled={adding || !newGroupUrl.trim()}
                    className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                  >
                    {adding ? "Добавление..." : "Добавить"}
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Error display */}
        {error && (
          <div className="mb-4 rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-400">
            {error}
            <button onClick={() => setError(null)} className="ml-2 underline">
              Скрыть
            </button>
          </div>
        )}

        {/* Content */}
        {loading ? (
          <div className="flex items-center justify-center py-12 text-slate-400">
            <RefreshCw className="mr-2 h-5 w-5 animate-spin" />
            Загрузка...
          </div>
        ) : groups.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-slate-400">
            <Users className="mb-4 h-12 w-12" />
            <p className="text-lg font-medium">Нет добавленных групп</p>
            <p className="text-sm">
              Добавьте VK паблик для автоматического мониторинга постов
            </p>
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {groups.map((group) => (
              <div
                key={group.id}
                className={`cursor-pointer rounded-xl border p-4 transition-all hover:shadow-md ${
                  selectedGroup === group.id
                    ? "border-blue-500 ring-2 ring-blue-500/20"
                    : "border-slate-200 dark:border-slate-700"
                }`}
                onClick={() => fetchPosts(group.id)}
              >
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    {group.photo_url ? (
                      <img
                        src={group.photo_url}
                        alt={group.name}
                        className="h-10 w-10 rounded-full object-cover"
                      />
                    ) : (
                      <div className="flex h-10 w-10 items-center justify-center rounded-full bg-slate-200 dark:bg-slate-700">
                        <Users className="h-5 w-5 text-slate-400" />
                      </div>
                    )}
                    <div>
                      <h3 className="font-medium leading-tight">
                        {group.name}
                      </h3>
                      <a
                        href={`https://vk.com/${group.screen_name}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={(e) => e.stopPropagation()}
                        className="flex items-center gap-1 text-xs text-blue-500 hover:underline"
                      >
                        {group.screen_name}
                        <ExternalLink className="h-3 w-3" />
                      </a>
                    </div>
                  </div>
                  <div className="flex gap-1">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleToggleActive(group);
                      }}
                      className={`rounded p-1 transition-colors ${
                        group.is_active
                          ? "text-green-600 hover:bg-green-50 dark:hover:bg-green-900/20"
                          : "text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700"
                      }`}
                      title={group.is_active ? "Остановить" : "Запустить"}
                    >
                      {group.is_active ? (
                        <Power className="h-4 w-4" />
                      ) : (
                        <PowerOff className="h-4 w-4" />
                      )}
                    </button>
                  </div>
                </div>

                <div className="mt-3 flex flex-wrap gap-3 text-xs text-slate-500">
                  <span className="flex items-center gap-1">
                    <FileText className="h-3 w-3" />
                    {group.posts_count} постов
                  </span>
                  <span className="flex items-center gap-1">
                    <Clock className="h-3 w-3" />
                    {formatInterval(group.check_interval_minutes)}
                  </span>
                  {group.active_posts_count > 0 && (
                    <span className="rounded-full bg-green-100 px-2 py-0.5 text-green-700 dark:bg-green-900/30 dark:text-green-400">
                      {group.active_posts_count} активных
                    </span>
                  )}
                </div>

                {group.last_checked_at && (
                  <p className="mt-2 text-xs text-slate-400">
                    Проверено: {formatAge(group.last_checked_at)}
                  </p>
                )}

                <div className="mt-3 flex gap-2">
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      handleCheckNow(group.id);
                    }}
                    className="flex items-center gap-1 rounded-lg bg-slate-100 px-3 py-1.5 text-xs font-medium hover:bg-slate-200 dark:bg-slate-700 dark:hover:bg-slate-600"
                  >
                    <RefreshCw className="h-3 w-3" />
                    Проверить
                  </button>
                  {group.message_id && (
                    <a
                      href={`/messages/${group.message_id}`}
                      onClick={(e) => e.stopPropagation()}
                      className="flex items-center gap-1 rounded-lg bg-slate-100 px-3 py-1.5 text-xs font-medium hover:bg-slate-200 dark:bg-slate-700 dark:hover:bg-slate-600"
                    >
                      <ExternalLink className="h-3 w-3" />
                      Публикация
                    </a>
                  )}
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDelete(group.id);
                    }}
                    className="flex items-center gap-1 rounded-lg bg-red-50 px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-100 dark:bg-red-900/20 dark:text-red-400 dark:hover:bg-red-900/30"
                  >
                    <Trash2 className="h-3 w-3" />
                    Удалить
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Posts section */}
        {selectedGroup && (
          <div className="mt-6 rounded-xl border p-4 dark:border-slate-700">
            <h3 className="mb-3 font-medium">Посты группы</h3>
            {postsLoading ? (
              <div className="flex items-center justify-center py-8 text-slate-400">
                <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
                Загрузка...
              </div>
            ) : groupPosts.length === 0 ? (
              <p className="py-8 text-center text-sm text-slate-400">
                Посты пока не найдены
              </p>
            ) : (
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {groupPosts.map((post) => (
                  <div
                    key={post.id}
                    className="rounded-lg border p-3 text-sm dark:border-slate-700"
                  >
                    <div className="flex items-center justify-between">
                      <a
                        href={`https://vk.com/wall${post.post_external_id}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-blue-500 hover:underline"
                      >
                        Пост {post.post_external_id.split("_")[1]}
                      </a>
                      {post.is_tracking ? (
                        <span className="flex items-center gap-1 text-xs text-green-600">
                          <CheckCircle className="h-3 w-3" />
                          Трекинг
                        </span>
                      ) : (
                        <span className="flex items-center gap-1 text-xs text-slate-400">
                          <XCircle className="h-3 w-3" />
                          Завершён
                        </span>
                      )}
                    </div>
                    <p className="mt-1 text-xs text-slate-400">
                      Опубликован: {formatAge(post.post_created_at)}
                    </p>
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
