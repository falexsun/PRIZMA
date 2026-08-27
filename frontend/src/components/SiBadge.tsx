import { SI_THRESHOLDS } from "@/lib/theme";

export function SiBadge({ value }: { value: number }) {
  const { high, medium } = SI_THRESHOLDS;
  const colorClass =
    value >= high
      ? "badge positive"
      : value >= medium
      ? "badge amber"
      : "badge neutral";

  return (
    <span className={colorClass}>
      {value.toLocaleString("ru-RU")}
    </span>
  );
}
