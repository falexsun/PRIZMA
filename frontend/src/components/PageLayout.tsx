"use client";

import { useState, useEffect } from "react";
import { usePathname } from "next/navigation";
import { AppHeader } from "./AppHeader";
import { Sidebar } from "./Sidebar";
import type { Me } from "@/lib/types";

export function PageLayout({
  children,
  user,
}: {
  children: React.ReactNode;
  user?: Me;
}) {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  // Expand sidebar on navigation
  useEffect(() => {
    setCollapsed(false);
  }, [pathname]);

  const userInfo = user
    ? {
        name: user.login,
        initials: user.login.charAt(0).toUpperCase(),
        role: user.role === "admin" ? "Администратор" : user.department,
      }
    : undefined;

  return (
    <div className="flex h-screen overflow-hidden bg-slate-50 dark:bg-slate-950">
      {/* Desktop sidebar */}
      <div className="hidden md:block">
        <Sidebar user={userInfo} collapsed={collapsed} onToggle={() => setCollapsed(!collapsed)} />
      </div>

      {/* Mobile sidebar overlay */}
      {mobileOpen && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div className="absolute inset-0 bg-black/40" onClick={() => setMobileOpen(false)} />
          <div className="relative z-50">
            <Sidebar
              user={userInfo}
              collapsed={false}
              onToggle={() => setMobileOpen(false)}
            />
          </div>
        </div>
      )}

      {/* Main content */}
      <div className="flex flex-1 flex-col overflow-hidden">
        <AppHeader user={user} onMobileMenuClick={() => setMobileOpen(true)} />
        <main className="flex-1 overflow-y-auto p-4 sm:p-6">
          {children}
        </main>
      </div>
    </div>
  );
}
