"use client";

import { useState } from "react";
import { X } from "lucide-react";

export function LinkChipsInput({
  links,
  onChange,
}: {
  links: string[];
  onChange: (links: string[]) => void;
}) {
  const [raw, setRaw] = useState("");

  function addFromRaw() {
    const candidates = raw
      .split(/[\s,;]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (candidates.length === 0) return;
    const merged = Array.from(new Set([...links, ...candidates]));
    onChange(merged);
    setRaw("");
  }

  function removeLink(url: string) {
    onChange(links.filter((l) => l !== url));
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2 rounded-lg border border-slate-200 bg-white p-2 min-h-[44px] dark:border-slate-600 dark:bg-slate-800">
        {links.map((url) => (
          <span
            key={url}
            className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-3 py-1 text-xs text-blue-800 transition-colors hover:bg-blue-100 dark:bg-blue-900/30 dark:text-blue-300 dark:hover:bg-blue-900/50"
          >
            <span className="max-w-[200px] truncate">{url}</span>
            <button
              type="button"
              onClick={() => removeLink(url)}
              className="ml-0.5 rounded-full p-0.5 text-blue-400 hover:text-blue-700 dark:text-blue-500 dark:hover:text-blue-300"
            >
              <X className="h-3 w-3" />
            </button>
          </span>
        ))}
        {links.length === 0 && (
          <span className="text-xs text-slate-400 dark:text-slate-500">
            Ссылки не добавлены
          </span>
        )}
      </div>
      <div className="flex gap-2">
        <textarea
          className="flex-1 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm transition-colors focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100 dark:focus:border-blue-400"
          rows={2}
          placeholder="Вставьте ссылки (через пробел, запятую или с новой строки)"
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
        />
        <button
          type="button"
          onClick={addFromRaw}
          className="shrink-0 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
        >
          Добавить
        </button>
      </div>
    </div>
  );
}
