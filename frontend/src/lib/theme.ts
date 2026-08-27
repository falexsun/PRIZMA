// Theme constants for the application
export const BRAND = "#2563EB";
export const SUCCESS = "#10B981";
export const WARNING = "#F59E0B";
export const DANGER = "#EF4444";

// Chart colors (consistent across pie, area, stacked charts)
export const PIE_COLORS = [
  "#2563EB", "#10B981", "#F59E0B", "#EF4444",
  "#8B5CF6", "#0EA5E9", "#EC4899",
];

// SI thresholds for badge coloring
export const SI_THRESHOLDS = {
  high: 1000,
  medium: 100,
};

// Tone configuration
export const TONE_CONFIG: Record<string, { color: string; label: string }> = {
  positive: { color: "positive", label: "Позитив" },
  neutral: { color: "neutral", label: "Нейтрал" },
  negative: { color: "negative", label: "Негатив" },
};

// Platform display labels
export const PLATFORM_LABELS: Record<string, string> = {
  vk: "VK",
  telegram: "TG",
  youtube: "YT",
  tiktok: "TT",
  instagram: "IG",
  dzen: "Dzen",
  max: "MAX",
  ok: "OK",
};
