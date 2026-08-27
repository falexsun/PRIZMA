"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { RatingRow } from "@/lib/types";
import { PageLayout } from "@/components/PageLayout";
import { useMe } from "@/lib/useMe";
import { Download, Trophy, Medal, Award } from "lucide-react";

export default function AdminRatingPage() {
  const [period, setPeriod] = useState("30");
  const { data: user } = useMe();

  const { data: rows, isLoading } = useQuery<RatingRow[]>({
    queryKey: ["admin-rating", period],
    queryFn: async () => (await api.get("/admin/rating", { params: { period } })).data,
  });

  async function handleExport() {
    const response = await api.get("/admin/rating/export", {
      params: { period },
      responseType: "blob",
    });
    const url = URL.createObjectURL(response.data);
    const a = document.createElement("a");
    a.href = url;
    a.download = `rating_${period}.xlsx`;
    a.click();
    URL.revokeObjectURL(url);
  }

  function rankBadge(rank: number) {
    if (rank === 1) return <Trophy className="h-4 w-4 text-amber-500" />;
    if (rank === 2) return <Medal className="h-4 w-4 text-slate-400" />;
    if (rank === 3) return <Medal className="h-4 w-4 text-amber-700" />;
    return <span className="text-xs text-slate-400">#{rank}</span>;
  }

  return (
    <PageLayout user={user}>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-lg font-semibold">Рейтинг организаций</h1>
        <div className="flex items-center gap-2">
          <select
            className="w-32"
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
          >
            <option value="7">7 дней</option>
            <option value="30">30 дней</option>
            <option value="90">90 дней</option>
            <option value="all">Всё время</option>
          </select>
          <button
            onClick={handleExport}
            className="btn secondary"
          >
            <Download className="h-4 w-4" />
            Экспорт xlsx
          </button>
        </div>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-800">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="table-header">
              <tr>
                <th className="table-header text-center">Место</th>
                <th className="table-header">Организация</th>
                <th className="table-header">Публикаций</th>
                <th className="table-header">Σ Si</th>
                <th className="table-header">Σ просмотров</th>
                <th className="table-header">Средний Si</th>
              </tr>
            </thead>
            <tbody>
              {isLoading && (
                <tr>
                  <td colSpan={6} className="px-3 py-4 text-center text-slate-400">
                    Загрузка...
                  </td>
                </tr>
              )}
              {rows?.map((row) => (
                <tr key={row.org_name} className="border-t border-slate-200 transition-colors hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800/50">
                  <td className="table-cell text-center">
                    <div className="mx-auto flex h-8 w-8 items-center justify-center">
                      {rankBadge(row.rank)}
                    </div>
                  </td>
                  <td className="table-cell font-medium">{row.org_name}</td>
                  <td className="table-cell">{row.messages_count}</td>
                  <td className="table-cell font-medium">{row.si_total.toLocaleString("ru-RU")}</td>
                  <td className="table-cell">{row.views_total.toLocaleString("ru-RU")}</td>
                  <td className="table-cell">{row.avg_si}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </PageLayout>
  );
}
