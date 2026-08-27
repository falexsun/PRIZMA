export type Tone = "positive" | "neutral" | "negative";
export type Platform = "vk" | "telegram" | "youtube" | "tiktok" | "instagram" | "dzen" | "max" | "ok";
export type UserRole = "admin" | "org_user";

export interface Topic {
  id: number;
  name: string;
}

export interface LinkMetrics {
  likes: number;
  reposts: number;
  comments: number;
  saves: number;
  views: number;
  si: number;
  fetched_at: string;
}

export interface Link {
  id: number;
  url_raw: string;
  url_normalized: string;
  platform: Platform;
  hashtags: string;
  created_at: string;
  latest_metrics: LinkMetrics | null;
}

export interface MessageListItem {
  id: number;
  department: string;
  content_format: string;
  title: string;
  tone: Tone;
  topics: Topic[];
  si_total: number;
  views_total: number;
  created_at: string;
  updated_at: string;
}

export interface MessageDetail extends MessageListItem {
  links: Link[];
  links_count: number;
}

export interface Me {
  id: number;
  login: string;
  org_name: string;
  department: string;
  role: UserRole;
  is_active: boolean;
}

export interface AdminUser {
  id: number;
  login: string;
  org_name: string;
  department: string;
  role: UserRole;
  is_active: boolean;
  created_at: string;
}

export interface RatingRow {
  org_name: string;
  messages_count: number;
  si_total: number;
  views_total: number;
  avg_si: number;
  rank: number;
}

export interface DashboardSummary {
  top_orgs: RatingRow[];
  platform_distribution: Record<string, number>;
  tone_distribution: Record<string, number>;
  top_messages: { id: number; title: string; si_total: number }[];
}

export interface TimeseriesPoint {
  date: string;
  org_name: string;
  si: number;
}
