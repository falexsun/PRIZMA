"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { PageLayout } from "@/components/PageLayout";
import { api } from "@/lib/api";
import { useMe } from "@/lib/useMe";

interface SettingsResponse {
  settings: Record<string, string | null>;
}

interface MaxLoginStatus {
  stage: "idle" | "code_required" | "password_required" | "authenticated" | "error";
  message: string;
}

interface MaxSessionStatus {
  configured: boolean;
  valid: boolean;
  message: string;
}

interface ConnectionStatus {
  configured: boolean;
  valid: boolean;
  message: string;
  type?: string | null;
}

type ProxyStatusResponse = Record<"non_ru_proxy" | "ru_proxy", ConnectionStatus>;

const SETTINGS_KEYS = [
  "non_ru_proxy",
  "ru_proxy",
  "vk_user_token",
  "vk_service_token",
  "network_access_config",
] as const;

export default function AdminSettingsPage() {
  const queryClient = useQueryClient();
  const { data: user } = useMe();
  const [saved, setSaved] = useState(false);
  const [form, setForm] = useState<Record<string, string>>({});
  const [visible, setVisible] = useState<Set<string>>(new Set());
  const [vkTokenType, setVkTokenType] = useState<"user" | "service">("user");
  const [maxPhone, setMaxPhone] = useState("");
  const [maxCode, setMaxCode] = useState("");
  const [maxPassword, setMaxPassword] = useState("");
  const [networkFile, setNetworkFile] = useState<File | null>(null);
  const [networkFileStatus, setNetworkFileStatus] = useState<string | null>(null);

  const { data, isLoading } = useQuery<SettingsResponse>({
    queryKey: ["admin-settings"],
    queryFn: async () => (await api.get("/admin/settings")).data,
  });

  const { data: maxLogin } = useQuery<MaxLoginStatus>({
    queryKey: ["max-login-status"],
    queryFn: async () => (await api.get("/admin/settings/max-login")).data,
  });

  const { data: maxSession, isFetching: isCheckingMaxSession } = useQuery<MaxSessionStatus>({
    queryKey: ["max-session-status"],
    queryFn: async () => (await api.get("/admin/settings/max-session")).data,
  });

  const {
    data: proxyStatus,
    isFetching: isCheckingProxy,
    refetch: checkProxy,
  } = useQuery<ProxyStatusResponse>({
    queryKey: ["proxy-status"],
    queryFn: async () => (await api.get("/admin/settings/proxy-status")).data,
  });

  const {
    data: vkTokenStatus,
    isFetching: isCheckingVkToken,
    refetch: checkVkToken,
  } = useQuery<ConnectionStatus>({
    queryKey: ["vk-token-status"],
    queryFn: async () => (await api.get("/admin/settings/vk-token-status")).data,
  });

  useEffect(() => {
    if (!data) return;
    const next: Record<string, string> = {};
    for (const key of SETTINGS_KEYS) {
      next[key] = data.settings[key] ?? "";
    }
    setForm(next);
    setVkTokenType(data.settings.vk_service_token && !data.settings.vk_user_token ? "service" : "user");
  }, [data]);

  const saveSettings = useMutation({
    mutationFn: async (values: Record<string, string | null>) => {
      await api.put("/admin/settings", { settings: values });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-settings"] });
      queryClient.invalidateQueries({ queryKey: ["proxy-status"] });
      queryClient.invalidateQueries({ queryKey: ["vk-token-status"] });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    },
  });

  const maxLoginAction = useMutation({
    mutationFn: async ({ action, value }: { action: "start" | "code" | "password" | "cancel"; value?: string }) => {
      if (action === "start") {
        return (await api.post("/admin/settings/max-login/start", { phone: value })).data;
      }
      if (action === "code") {
        return (await api.post("/admin/settings/max-login/code", { code: value })).data;
      }
      if (action === "password") {
        return (await api.post("/admin/settings/max-login/password", { password: value })).data;
      }
      return (await api.delete("/admin/settings/max-login")).data;
    },
    onSuccess: (result: MaxLoginStatus) => {
      queryClient.setQueryData(["max-login-status"], result);
      queryClient.invalidateQueries({ queryKey: ["max-session-status"] });
      if (result.stage !== "code_required") setMaxCode("");
      if (result.stage !== "password_required") setMaxPassword("");
    },
  });

  const maxLoginError =
    (maxLoginAction.error as any)?.response?.data?.detail ??
    (maxLoginAction.isError ? "Не удалось выполнить вход в MAX" : null);

  function toggleVisible(key: string) {
    setVisible((prev) => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  }

  function updateField(key: string, value: string) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function loadNetworkFile(file: File) {
    if (file.size > 1024 * 1024) {
      setNetworkFileStatus("Файл слишком большой");
      return;
    }
    const text = await file.text();
    updateField("network_access_config", text.trim());
    setNetworkFile(file);
    setNetworkFileStatus("Файл загружен в поле");
    setTimeout(() => setNetworkFileStatus(null), 3000);
  }

  function renderSecretField(key: string, label: string, placeholder: string) {
    return (
      <div className="space-y-1">
        <label className="text-sm font-medium text-slate-700 dark:text-slate-300">{label}</label>
        <div className="flex gap-2">
          <input
            type={visible.has(key) ? "text" : "password"}
            value={form[key] ?? ""}
            onChange={(event) => updateField(key, event.target.value)}
            className="input flex-1"
            placeholder={placeholder}
          />
          <button
            type="button"
            onClick={() => toggleVisible(key)}
            className="shrink-0 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-600 hover:bg-slate-50 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
          >
            {visible.has(key) ? "Скрыть" : "Показать"}
          </button>
        </div>
      </div>
    );
  }

  function renderStatus(status?: ConnectionStatus, loading = false) {
    const valid = Boolean(status?.valid);
    const configured = Boolean(status?.configured);
    const label = loading ? "Проверка..." : valid ? "Работает" : configured ? "Ошибка" : "Не настроен";
    return (
      <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${valid ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400" : configured ? "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400" : "bg-slate-100 text-slate-500 dark:bg-slate-700 dark:text-slate-400"}`}>
        <span className={`h-1.5 w-1.5 rounded-full ${valid ? "bg-emerald-500" : configured ? "bg-red-500" : "bg-slate-400"}`} />
        {label}
      </span>
    );
  }

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    saveSettings.mutate({ ...form });
  }

  const maxSessionOk = Boolean(maxSession?.valid);

  return (
    <PageLayout user={user}>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-lg font-semibold">Настройки платформ</h1>
        <Link href="/admin" className="btn secondary">
          <ArrowLeft className="h-4 w-4" />
          Назад
        </Link>
      </div>

      <section className="rounded-xl border border-slate-200 bg-white p-6 dark:border-slate-700 dark:bg-slate-800">
        {isLoading ? (
          <p className="text-sm text-slate-500">Загрузка...</p>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 dark:border-slate-700 dark:bg-slate-800/50">
              <h2 className="mb-3 text-sm font-semibold text-slate-800 dark:text-slate-200">Прокси</h2>
              <p className="mb-3 text-xs text-slate-500">
                Необязательно: оставьте пустым, если доступ уже есть через сеть компьютера или внешний VPN.
              </p>
              <div className="mb-3 flex items-center gap-2">
                <button type="button" onClick={() => checkProxy()} disabled={isCheckingProxy} className="btn secondary text-xs">
                  Проверить
                </button>
              </div>
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <div className="flex-1">{renderSecretField("non_ru_proxy", "NON-RU proxy", "socks5://user:pass@host:port")}</div>
                  {renderStatus(proxyStatus?.non_ru_proxy, isCheckingProxy)}
                </div>
                {proxyStatus?.non_ru_proxy?.message && <p className="text-xs text-slate-500">NON-RU: {proxyStatus.non_ru_proxy.message}</p>}
                <div className="flex items-center gap-2">
                  <div className="flex-1">{renderSecretField("ru_proxy", "RU proxy", "socks5://user:pass@host:port")}</div>
                  {renderStatus(proxyStatus?.ru_proxy, isCheckingProxy)}
                </div>
                {proxyStatus?.ru_proxy?.message && <p className="text-xs text-slate-500">RU: {proxyStatus.ru_proxy.message}</p>}
              </div>
            </div>

            <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 dark:border-slate-700 dark:bg-slate-800/50">
              <h2 className="mb-3 text-sm font-semibold text-slate-800 dark:text-slate-200">VK</h2>
              <div className="mb-3 flex items-center gap-2">
                {renderStatus(vkTokenStatus, isCheckingVkToken)}
                <button type="button" onClick={() => checkVkToken()} disabled={isCheckingVkToken} className="btn secondary text-xs">
                  Проверить
                </button>
              </div>
              <div className="mb-3 flex gap-2">
                <button type="button" onClick={() => setVkTokenType("user")} className={`btn text-xs ${vkTokenType === "user" ? "primary" : "secondary"}`}>
                  User token
                </button>
                <button type="button" onClick={() => setVkTokenType("service")} className={`btn text-xs ${vkTokenType === "service" ? "primary" : "secondary"}`}>
                  Service token
                </button>
              </div>
              {vkTokenType === "user"
                ? renderSecretField("vk_user_token", "VK User token", "vk1.a...")
                : renderSecretField("vk_service_token", "VK Service token", "••••••••")}
            </div>

            <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 dark:border-slate-700 dark:bg-slate-800/50">
              <div className="mb-3 flex items-center gap-2">
                <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-200">MAX</h2>
                <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${maxSessionOk ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400" : "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400"}`}>
                  <span className={`h-1.5 w-1.5 rounded-full ${maxSessionOk ? "bg-emerald-500" : "bg-amber-500"}`} />
                  {isCheckingMaxSession ? "Проверка..." : maxSessionOk ? "Сессия работает" : "Нужно войти"}
                </span>
              </div>

              <p className={`mb-3 text-sm ${maxSessionOk ? "text-emerald-600 dark:text-emerald-400" : "text-slate-600 dark:text-slate-400"}`}>
                {maxSessionOk ? "Активная сессия MAX найдена, сбор метрик доступен." : "Активной сессии MAX нет, войдите в аккаунт ниже."}
              </p>

              {(!maxLogin || ["idle", "error", "authenticated"].includes(maxLogin.stage)) && (
                <div className="flex flex-wrap items-end gap-2">
                  <label className="min-w-64 flex-1 text-xs font-medium text-slate-700 dark:text-slate-300">
                    Номер телефона
                    <input
                      type="tel"
                      autoComplete="tel"
                      value={maxPhone}
                      onChange={(event) => setMaxPhone(event.target.value)}
                      placeholder="+7..."
                      className="input mt-1"
                    />
                  </label>
                  <button
                    type="button"
                    disabled={!maxPhone.trim() || maxLoginAction.isPending}
                    onClick={() => maxLoginAction.mutate({ action: "start", value: maxPhone })}
                    className="btn primary"
                  >
                    Отправить SMS
                  </button>
                </div>
              )}

              {maxLogin?.stage === "code_required" && (
                <div className="flex flex-wrap items-end gap-2">
                  <label className="min-w-48 flex-1 text-xs font-medium text-slate-700 dark:text-slate-300">
                    Код из SMS
                    <input
                      type="text"
                      inputMode="numeric"
                      autoComplete="one-time-code"
                      value={maxCode}
                      onChange={(event) => setMaxCode(event.target.value.replace(/\D/g, ""))}
                      className="input mt-1"
                    />
                  </label>
                  <button
                    type="button"
                    disabled={!maxCode || maxLoginAction.isPending}
                    onClick={() => maxLoginAction.mutate({ action: "code", value: maxCode })}
                    className="btn primary"
                  >
                    Подтвердить SMS
                  </button>
                </div>
              )}

              {maxLogin?.stage === "password_required" && (
                <div className="flex flex-wrap items-end gap-2">
                  <label className="min-w-64 flex-1 text-xs font-medium text-slate-700 dark:text-slate-300">
                    Пароль 2FA
                    <input
                      type="password"
                      autoComplete="current-password"
                      value={maxPassword}
                      onChange={(event) => setMaxPassword(event.target.value)}
                      className="input mt-1"
                    />
                  </label>
                  <button
                    type="button"
                    disabled={!maxPassword || maxLoginAction.isPending}
                    onClick={() => maxLoginAction.mutate({ action: "password", value: maxPassword })}
                    className="btn primary"
                  >
                    Завершить вход
                  </button>
                </div>
              )}

              {(maxLogin?.stage === "code_required" || maxLogin?.stage === "password_required") && (
                <button
                  type="button"
                  disabled={maxLoginAction.isPending}
                  onClick={() => maxLoginAction.mutate({ action: "cancel" })}
                  className="mt-2 text-sm text-slate-500 underline hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-300"
                >
                  Отменить вход
                </button>
              )}

              {maxLogin?.message && <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">{maxLogin.message}</p>}
              {maxLoginAction.isPending && <p className="mt-2 text-sm text-slate-500">Ожидание ответа MAX...</p>}
              {maxLoginError && <p className="mt-2 text-sm text-red-600">{maxLoginError}</p>}
            </div>

            <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 dark:border-slate-700 dark:bg-slate-800/50">
              <div className="mb-2 flex items-center gap-2">
                <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-200">Сетевой доступ</h2>
                <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${form.network_access_config ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400" : "bg-slate-100 text-slate-500 dark:bg-slate-700 dark:text-slate-400"}`}>
                  {form.network_access_config ? "Ключ добавлен" : "Не настроен"}
                </span>
              </div>
              <div className="space-y-3">
                <label className="block text-xs font-medium text-slate-700 dark:text-slate-300">
                  Клиентская ссылка или ключ
                  <textarea
                    value={form.network_access_config ?? ""}
                    onChange={(event) => updateField("network_access_config", event.target.value)}
                    className="input mt-1 min-h-28 font-mono text-xs"
                    placeholder="vless://..., hysteria2://..., ss://..., trojan://..., amneziawg://..., WireGuard config или данные 3x-ui"
                  />
                </label>
                <p className="text-xs text-slate-500">
                  Необязательно: если системный VPN уже даёт доступ, оставьте это поле пустым. Если внешний клиент выдаёт HTTP/SOCKS адрес, укажите его в полях прокси выше.
                </p>
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <input
                  type="file"
                  accept=".txt,.conf,.json,.yaml,.yml"
                  onChange={(event) => {
                    const file = event.target.files?.[0] ?? null;
                    if (file) void loadNetworkFile(file);
                  }}
                  className="text-sm"
                />
                <button
                  type="button"
                  disabled={!networkFile && !form.network_access_config}
                  onClick={() => {
                    setNetworkFile(null);
                    updateField("network_access_config", "");
                  }}
                  className="btn secondary"
                >
                  Очистить
                </button>
                {networkFileStatus && (
                  <span className={networkFileStatus.includes("слишком") ? "text-sm text-red-600" : "text-sm text-emerald-600 dark:text-emerald-400"}>
                    {networkFileStatus}
                  </span>
                )}
              </div>
            </div>

            <div className="flex items-center gap-3 pt-2">
              <button type="submit" disabled={saveSettings.isPending} className="btn primary">
                {saveSettings.isPending ? "Сохранение..." : "Сохранить"}
              </button>
              {saved && <span className="text-sm text-emerald-600 dark:text-emerald-400">Сохранено</span>}
              {saveSettings.isError && <span className="text-sm text-red-600">Ошибка сохранения</span>}
            </div>
          </form>
        )}
      </section>
    </PageLayout>
  );
}
