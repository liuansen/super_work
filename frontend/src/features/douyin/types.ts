// 抖音应用前端类型（与 backend/app/api/platforms/douyin.py 响应一一对应）

export interface DouyinAccount {
  id: number;
  provider_account_id: string | null;
  nickname: string;
  avatar_url: string;
  status: "active" | "invalid" | "unknown" | string;
  status_message: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface DouyinWorkStats {
  digg_count: number | null;
  comment_count: number | null;
  share_count: number | null;
  collect_count: number | null;
}

export interface DouyinMetricSnapshot {
  id: number;
  reference_work_id: number;
  digg_count: number | null;
  comment_count: number | null;
  share_count: number | null;
  collect_count: number | null;
  availability: string;
  collected_at: string | null;
}

export interface DouyinReference {
  id: number;
  provider_work_id: string;
  work_url: string;
  title: string;
  cover_url: string;
  author_nickname: string;
  author_sec_uid: string;
  duration_ms: number | null;
  publish_time_ms: number | null;
  stats: DouyinWorkStats;
  tags: string[];
  note: string;
  collected_at: string | null;
  latest_metrics?: DouyinMetricSnapshot;
}

export interface DouyinPublishTask {
  id: number;
  account_id: number;
  kind: "video" | "images" | string;
  media_names: string[];
  title: string;
  description: string;
  visibility: number;
  allow_download: boolean;
  scheduled_at: string | null;
  status: "pending" | "running" | "succeeded" | "failed" | "unknown" | "cancelled" | string;
  provider_work_id: string | null;
  error_message: string;
  dispatched_at: string | null;
  created_at: string | null;
}

export interface MediaUploadResult {
  file_name: string;
  file_path: string;
  download_url: string;
  asset_type: "video" | "image";
  size: number;
}
