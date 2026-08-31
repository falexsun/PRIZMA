import { SI_THRESHOLDS } from "@/lib/theme";
import { formatCompactNumber, formatFullNumber } from "@/lib/numbers";

export function SiBadge({ value }: { value: number }) {
  const { high, medium } = SI_THRESHOLDS;
  const colorClass =
    value >= high
      ? "badge positive"
      : value >= medium
      ? "badge amber"
      : "badge neutral";

  return (
    <span className={`${colorClass} max-w-full whitespace-nowrap tabular-nums`} title={formatFullNumber(value)}>
      {formatCompactNumber(value)}
    </span>
  );
}
