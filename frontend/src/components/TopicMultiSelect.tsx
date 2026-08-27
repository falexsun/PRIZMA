import type { Topic } from "@/lib/types";

export function TopicMultiSelect({
  topics,
  selectedIds,
  onChange,
}: {
  topics: Topic[];
  selectedIds: number[];
  onChange: (ids: number[]) => void;
}) {
  function toggle(id: number) {
    onChange(selectedIds.includes(id) ? selectedIds.filter((x) => x !== id) : [...selectedIds, id]);
  }

  return (
    <div className="flex flex-wrap gap-2">
      {topics.map((t) => {
        const active = selectedIds.includes(t.id);
        return (
          <button
            type="button"
            key={t.id}
            onClick={() => toggle(t.id)}
            className={
              active
                ? "rounded-full bg-brand px-3 py-1 text-xs font-medium text-white"
                : "rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600 transition-colors hover:bg-slate-200 dark:bg-slate-700 dark:text-slate-300 dark:hover:bg-slate-600"
            }
          >
            {t.name}
          </button>
        );
      })}
    </div>
  );
}
