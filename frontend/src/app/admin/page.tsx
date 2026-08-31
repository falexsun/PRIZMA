"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  AreaChart,
  Area,
  Customized,
} from "recharts";
import { api } from "@/lib/api";
import type { AdminUser, DashboardSummary, TimeseriesPoint } from "@/lib/types";
import { PageLayout } from "@/components/PageLayout";
import { useMe } from "@/lib/useMe";
import {
  LayoutDashboard,
  Award,
  FileText,
  Users,
  TrendingUp,
  BarChart3,
  PieChart as PieChartIcon,
} from "lucide-react";
import { PIE_COLORS, BRAND } from "@/lib/theme";
import { formatCompactNumber, formatFullNumber } from "@/lib/numbers";

const PIE_COLORS_ARRAY = PIE_COLORS;

interface TooltipEntry {
  name: string;
  value: number;
  color: string;
}

interface CustomTooltipProps {
  active?: boolean;
  payload?: { name: string; value: number; color: string }[];
  label?: string;
}

function ChartTooltip({ active, payload, label }: CustomTooltipProps) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 shadow-lg dark:border-slate-700 dark:bg-slate-800">
      {label && <p className="mb-1 text-xs font-medium text-slate-500 dark:text-slate-400">{label}</p>}
      {payload.map((entry, idx) => (
        <div key={idx} className="flex items-center gap-2 text-sm">
          <div className="h-2 w-2 rounded-full" style={{ backgroundColor: entry.color }} />
          <span className="text-slate-600 dark:text-slate-300">{entry.name}:</span>
          <span className="font-medium tabular-nums" title={typeof entry.value === "number" ? formatFullNumber(entry.value) : String(entry.value)}>
            {typeof entry.value === "number" ? formatCompactNumber(entry.value) : entry.value}
          </span>
        </div>
      ))}
    </div>
  );
}

function reshapeTimeseries(points: TimeseriesPoint[]) {
  const byDate = new Map<string, Record<string, number | string>>();
  const orgs = new Set<string>();
  for (const p of points) {
    orgs.add(p.org_name);
    const row = byDate.get(p.date) ?? { date: p.date };
    row[p.org_name] = p.si;
    byDate.set(p.date, row);
  }
  return { rows: Array.from(byDate.values()).sort((a, b) => String(a.date).localeCompare(String(b.date))), orgs: Array.from(orgs) };
}

export default function AdminPage() {
  const [period, setPeriod] = useState("30");
  const queryClient = useQueryClient();
  const { data: user } = useMe();
  const [newUser, setNewUser] = useState({ login: "", password: "", org_name: "", department: "" });
  const [createError, setCreateError] = useState<string | null>(null);

  const { data: users } = useQuery<AdminUser[]>({
    queryKey: ["admin-users"],
    queryFn: async () => (await api.get("/admin/users")).data,
  });

  const { data: summary } = useQuery<DashboardSummary>({
    queryKey: ["admin-summary", period],
    queryFn: async () => (await api.get("/admin/dashboard/summary", { params: { period } })).data,
  });

  const { data: timeseries } = useQuery<TimeseriesPoint[]>({
    queryKey: ["admin-timeseries", period],
    queryFn: async () => (await api.get("/admin/dashboard/timeseries", { params: { period } })).data,
  });

  async function handleCreateUser(e: React.FormEvent) {
    e.preventDefault();
    setCreateError(null);
    try {
      await api.post("/admin/users", newUser);
      setNewUser({ login: "", password: "", org_name: "", department: "" });
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
    } catch {
      setCreateError("Не удалось создать пользователя");
    }
  }

  async function toggleActive(user: AdminUser) {
    await api.patch(`/admin/users/${user.id}`, { is_active: !user.is_active });
    queryClient.invalidateQueries({ queryKey: ["admin-users"] });
  }

  const { rows: timeseriesRows, orgs } = reshapeTimeseries(timeseries ?? []);
  const platformData = Object.entries(summary?.platform_distribution ?? {}).map(([name, value]) => ({
    name,
    value,
  }));
  const toneData = Object.entries(summary?.tone_distribution ?? {}).map(([name, value]) => ({ name, value }));

  const totalMessages = summary?.top_orgs?.reduce((s, o) => s + o.messages_count, 0) ?? 0;
  const totalSi = summary?.top_orgs?.reduce((s, o) => s + o.si_total, 0) ?? 0;
  const totalViews = summary?.top_orgs?.reduce((s, o) => s + o.views_total, 0) ?? 0;
  const orgCount = summary?.top_orgs?.length ?? 0;

  return (
    <PageLayout user={user}>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-lg font-semibold">Админ-панель</h1>
        <div className="flex items-center gap-3">
          <a
            href="/admin/settings"
            className="btn secondary"
          >
            <Award className="h-4 w-4" />
            Настройки платформ
          </a>
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
        </div>
      </div>

      {/* Stats */}
      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="stat-card">
          <FileText className="h-5 w-5 text-slate-400" />
          <div className="stat-value mt-2" title={formatFullNumber(totalMessages)}>{formatCompactNumber(totalMessages)}</div>
          <div className="stat-label">Публикаций</div>
        </div>
        <div className="stat-card">
          <TrendingUp className="h-5 w-5 text-slate-400" />
          <div className="stat-value mt-2" title={formatFullNumber(totalSi)}>{formatCompactNumber(totalSi)}</div>
          <div className="stat-label">Общий Si</div>
        </div>
        <div className="stat-card">
          <BarChart3 className="h-5 w-5 text-slate-400" />
          <div className="stat-value mt-2" title={formatFullNumber(totalViews)}>{formatCompactNumber(totalViews)}</div>
          <div className="stat-label">Просмотров</div>
        </div>
        <div className="stat-card">
          <PieChartIcon className="h-5 w-5 text-slate-400" />
          <div className="stat-value mt-2">{orgCount}</div>
          <div className="stat-label">Организаций</div>
        </div>
      </div>

      {/* Charts */}
      <div className="mb-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="card p-5">
          <h2 className="section-heading">Топ-10 организаций по Si</h2>
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={summary?.top_orgs ?? []}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" className="dark:stroke-slate-700" />
              <XAxis dataKey="org_name" tick={{ fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 11 }} axisLine={false} tickLine={false} />
              <Tooltip content={<ChartTooltip />} />
              <Bar dataKey="si_total" fill={BRAND} radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="card p-5">
          <h2 className="section-heading">Динамика Si по дням</h2>
          <ResponsiveContainer width="100%" height={250}>
            <AreaChart data={timeseriesRows}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" className="dark:stroke-slate-700" />
              <XAxis dataKey="date" tick={{ fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 11 }} axisLine={false} tickLine={false} />
              <Tooltip content={<ChartTooltip />} />
              <Legend />
              {orgs.map((org, idx) => (
                <Area
                  key={org}
                  type="monotone"
                  dataKey={org}
                  stackId="1"
                  stroke={PIE_COLORS_ARRAY[idx % PIE_COLORS_ARRAY.length]}
                  fill={PIE_COLORS_ARRAY[idx % PIE_COLORS_ARRAY.length]}
                  strokeWidth={1}
                />
              ))}
            </AreaChart>
          </ResponsiveContainer>
        </div>

        <div className="card p-5">
          <h2 className="section-heading">Распределение по платформам</h2>
          <ResponsiveContainer width="100%" height={250}>
            <PieChart>
              <Pie data={platformData} dataKey="value" nameKey="name" outerRadius={90} label={{ fontSize: 11 }} labelLine={false}>
                {platformData.map((_, idx) => (
                  <Cell key={idx} fill={PIE_COLORS_ARRAY[idx % PIE_COLORS_ARRAY.length]} />
                ))}
              </Pie>
              <Tooltip content={<ChartTooltip />} />
            </PieChart>
          </ResponsiveContainer>
        </div>

        <div className="card p-5">
          <h2 className="section-heading">Распределение по тональности</h2>
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={toneData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" className="dark:stroke-slate-700" />
              <XAxis dataKey="name" tick={{ fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 11 }} axisLine={false} tickLine={false} />
              <Tooltip content={<ChartTooltip />} />
              <Bar dataKey="value" fill={BRAND} radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Top messages */}
      <div className="card p-5">
        <h2 className="section-heading">Топ-10 публикаций</h2>
        <ol className="space-y-1 text-sm">
          {summary?.top_messages.map((m, idx) => (
            <li key={m.id} className="flex items-center justify-between border-b border-slate-100 py-2 dark:border-slate-700">
              <span className="flex items-center gap-2">
                <span className="flex h-5 w-5 items-center justify-center rounded-full bg-slate-100 text-xs font-medium text-slate-600 dark:bg-slate-700 dark:text-slate-400">
                  {idx + 1}
                </span>
                {m.title}
              </span>
              <span className="shrink-0 font-medium tabular-nums" title={formatFullNumber(m.si_total)}>{formatCompactNumber(m.si_total)}</span>
            </li>
          ))}
        </ol>
      </div>

      {/* Users */}
      <div className="card p-5">
        <h2 className="section-heading">Пользователи</h2>
        <table className="mb-4 w-full text-sm">
          <thead className="table-header">
            <tr>
              <th className="table-header">Логин</th>
              <th className="table-header">Организация</th>
              <th className="table-header">Отдел</th>
              <th className="table-header">Роль</th>
              <th className="table-header">Статус</th>
              <th className="table-header"></th>
            </tr>
          </thead>
          <tbody>
            {users?.map((u) => (
              <tr key={u.id} className="border-t border-slate-200 transition-colors hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800/50">
                <td className="table-cell">{u.login}</td>
                <td className="table-cell">{u.org_name}</td>
                <td className="table-cell">{u.department}</td>
                <td className="table-cell">
                  <span className="badge info">{u.role === "admin" ? "Админ" : "Пользователь"}</span>
                </td>
                <td className="table-cell">
                  <span className={u.is_active ? "text-emerald-600 dark:text-emerald-400" : "text-slate-400"}>
                    {u.is_active ? "✓ Активен" : "Заблокирован"}
                  </span>
                </td>
                <td className="table-cell">
                  <button onClick={() => toggleActive(u)} className="text-blue-600 hover:underline dark:text-blue-400">
                    {u.is_active ? "Заблокировать" : "Активировать"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <form onSubmit={handleCreateUser} className="flex flex-wrap items-end gap-2 border-t border-slate-200 pt-4 dark:border-slate-700">
          <input
            placeholder="Логин"
            className="w-36"
            value={newUser.login}
            onChange={(e) => setNewUser((s) => ({ ...s, login: e.target.value }))}
            required
          />
          <input
            placeholder="Пароль"
            type="password"
            className="w-36"
            value={newUser.password}
            onChange={(e) => setNewUser((s) => ({ ...s, password: e.target.value }))}
            required
          />
          <input
            placeholder="Организация"
            className="w-48"
            value={newUser.org_name}
            onChange={(e) => setNewUser((s) => ({ ...s, org_name: e.target.value }))}
            required
          />
          <input
            placeholder="Отдел"
            className="w-36"
            value={newUser.department}
            onChange={(e) => setNewUser((s) => ({ ...s, department: e.target.value }))}
            required
          />
          <button type="submit" className="btn primary">
            <Users className="h-4 w-4" />
            Создать
          </button>
          {createError && <span className="text-sm text-red-600">{createError}</span>}
        </form>
      </div>
    </PageLayout>
  );
}
