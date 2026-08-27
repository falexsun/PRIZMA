"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  LogOut,
  User,
  ChevronDown,
  LayoutDashboard,
  List,
  Award,
  Settings,
  Sun,
  Moon,
} from "lucide-react";
import { api, clearTokens } from "@/lib/api";
import type { Me } from "@/lib/types";
import { useTheme } from "./ThemeProvider";
import { TONE_CONFIG } from "@/lib/theme";
import clsx from "clsx";

const ROLE_LABELS: Record<string, string> = {
  admin: "Администратор",
  org_user: "Организация",
};

export function AppHeader({
  user,
  onMobileMenuClick,
}: {
  user?: Me;
  onMobileMenuClick?: () => void;
}) {
  const router = useRouter();
  const { theme, toggleTheme } = useTheme();

  function logout() {
    clearTokens();
    router.push("/login");
  }

  return (
    <header className="sticky top-0 z-10 flex h-14 items-center justify-between border-b border-slate-200 bg-white/80 px-4 backdrop-blur dark:border-slate-800 dark:bg-slate-900/80 md:px-6">
      {/* Left: logo + mobile menu */}
      <div className="flex items-center gap-3">
        {onMobileMenuClick && (
          <button
            onClick={onMobileMenuClick}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800 md:hidden"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5">
              <line x1="4" x2="20" y1="12" y2="12" />
              <line x1="4" x2="20" y1="6" y2="6" />
              <line x1="4" x2="20" y1="18" y2="18" />
            </svg>
          </button>
        )}
        <Link href="/messages" className="flex items-center gap-2 font-semibold">
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-brand text-sm font-bold text-white">
            C
          </div>
          <span className="hidden text-sm sm:inline">Content Tracker</span>
        </Link>
      </div>

      {/* Right: user + theme + logout */}
      <div className="flex items-center gap-2">
        <button
          onClick={toggleTheme}
          className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800"
          title={theme === "dark" ? "Светлая тема" : "Тёмная тема"}
        >
          {theme === "dark" ? (
            <Sun className="h-4 w-4" />
          ) : (
            <Moon className="h-4 w-4" />
          )}
        </button>

        {user && (
          <div className="flex items-center gap-2 rounded-lg px-2 py-1 hover:bg-slate-100 dark:hover:bg-slate-800">
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-slate-200 text-xs font-medium text-slate-600 dark:bg-slate-700 dark:text-slate-300">
              {user.login.charAt(0).toUpperCase()}
            </div>
            <span className="hidden text-sm text-slate-600 dark:text-slate-300 sm:inline">
              {user.login}
            </span>
            <ChevronDown className="hidden h-4 w-4 text-slate-400 sm:block" />
          </div>
        )}

        <button
          onClick={logout}
          className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 hover:text-red-600 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-red-400"
          title="Выйти"
        >
          <LogOut className="h-4 w-4" />
        </button>
      </div>
    </header>
  );
}
