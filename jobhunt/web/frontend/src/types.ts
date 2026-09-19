export type LedgerKind = "experience" | "education" | "skill" | "certification" | "project" | "achievement";
export type SkillLevel = "beginner" | "intermediate" | "advanced" | "expert";
export type JobStatus = "saved" | "applied" | "screening" | "interview" | "offer" | "rejected" | "withdrawn";
export type RoadmapStatus = "todo" | "in_progress" | "done" | "skipped";

export interface AppConfig {
  ai_configured: boolean;
  provider: string;
  provider_label: string;
  model: string;
  db_path: string;
  out_dir: string;
  ledger_kinds: LedgerKind[];
  skill_levels: SkillLevel[];
  job_statuses: JobStatus[];
  roadmap_statuses: RoadmapStatus[];
}

export interface LedgerEntry {
  id: number;
  kind: LedgerKind;
  title: string;
  org: string | null;
  start_date: string | null;
  end_date: string | null;
  description: string | null;
  skills: string[];
  level: SkillLevel | null;
  url: string | null;
  active: number;
  created_at: string;
  updated_at: string;
}

export interface LedgerInput {
  kind: LedgerKind;
  title: string;
  org?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  description?: string | null;
  skills: string[];
  level?: SkillLevel | null;
  url?: string | null;
}

export interface LedgerEvent {
  id: number;
  entry_id: number;
  action: "create" | "update" | "retire";
  source: string | null;
  snapshot: Partial<LedgerEntry>;
  at: string;
}

export interface SkillSummary {
  name: string;
  level: SkillLevel | null;
  evidence: string[];
}

export interface Coverage {
  skill: string;
  have: boolean;
}

export interface Role {
  id: number;
  title: string;
  description: string | null;
  required_skills: string[];
  nice_to_have: string[];
  priority: number;
  created_at: string;
  coverage: { required: Coverage[]; nice_to_have: Coverage[] };
  job_count: number;
}

export interface TailoredBullet {
  ledger_ref: string;
  bullet: string;
}

export interface JobAnalysis {
  required_skills: string[];
  nice_to_have: string[];
  matched_skills: string[];
  missing_skills: string[];
  fit_score: number;
  fit_summary: string;
  red_flags: string[];
  keywords_to_include: string[];
  tailored_bullets: TailoredBullet[];
  cover_letter: string;
}

export interface Material {
  id: number;
  job_id: number;
  kind: "bullets" | "cover_letter";
  content: string;
  created_at: string;
}

export interface JobEvent {
  id: number;
  job_id: number;
  from_status: JobStatus | null;
  to_status: JobStatus;
  note: string | null;
  at: string;
}

export interface Job {
  id: number;
  company: string;
  title: string;
  url: string | null;
  location: string | null;
  role_id: number | null;
  role_title: string | null;
  jd_text: string | null;
  status: JobStatus;
  fit_score: number | null;
  analysis: JobAnalysis | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  applied_at: string | null;
  materials?: Material[];
  history?: JobEvent[];
}

export interface RoadmapItem {
  id: number;
  role_id: number;
  skill: string;
  priority: number;
  why: string | null;
  actions: string[];
  resources: string[];
  est_weeks: number | null;
  status: RoadmapStatus;
  created_at: string;
  updated_at: string;
  ledger_entry_id?: number | null;
}

export interface Task<T = unknown> {
  id: string;
  kind: string;
  status: "running" | "done" | "error";
  result: T | null;
  error: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface Funnel {
  [status: string]: number;
}

export interface DashboardRole {
  id: number;
  title: string;
  priority: number;
  required: number;
  covered: number;
  open_items: number;
  done_items: number;
}

export interface Dashboard {
  ledger_counts: Record<LedgerKind, number>;
  skill_count: number;
  funnel: Funnel;
  roles: DashboardRole[];
  recent_jobs: Job[];
  recent_changes: {
    at: string;
    action: string;
    source: string | null;
    entry_id: number;
    title: string | null;
    kind: LedgerKind | null;
  }[];
}

export interface ExtractResult {
  entries: LedgerInput[];
  notes: string;
  source: string;
}

export interface RoleSuggestion {
  description: string;
  required_skills: string[];
  nice_to_have: string[];
}

export interface RoadmapResult {
  summary: string;
  leverage_existing: string[];
  item_ids: number[];
}

export interface AnalyzeResult {
  analysis: JobAnalysis;
  bullets_md: string;
  folder: string;
}

export interface ProviderInfo {
  id: string;
  label: string;
  kind: "anthropic" | "openai";
  default_model: string;
  model: string;
  base_url: string;
  default_base_url: string | null;
  env_keys: string[];
  key_status: "saved" | "env" | null;
  key_hint: string | null;
  docs: string;
  models_hint: string[];
}

export interface SettingsInfo {
  provider: string;
  model: string;
  ai_configured: boolean;
  providers: ProviderInfo[];
}

export interface SettingsUpdate {
  provider?: string;
  model?: string;
  base_url?: string;
  model_provider?: string;
  api_keys?: Record<string, string>;
}

export interface TestResult {
  ok: boolean;
  provider: string;
  model: string;
  latency_ms: number;
  reply: string;
}

export interface DiscoverKey {
  setting: string;
  label: string;
  env: string;
  status: "saved" | "env" | null;
  hint: string | null;
}

export interface DiscoverSource {
  id: string;
  label: string;
  kind: "remote" | "aggregator";
  notes: string;
  docs: string;
  keys: DiscoverKey[];
  configured: boolean;
  enabled: boolean;
}

export interface DiscoverRunResult {
  at: string;
  query: string;
  location: string;
  remote_only: boolean;
  country: string;
  total: number;
  new: number;
  per_source: Record<string, { count?: number; new?: number; error?: string }>;
}

export interface DiscoverInfo {
  location: string;
  country: string;
  remote_only: boolean;
  sources: DiscoverSource[];
  last_run: DiscoverRunResult | null;
  counts: Record<"new" | "saved" | "dismissed", number>;
  suggested_queries: string[];
}

export interface DiscoveredJob {
  id: number;
  source: string;
  external_id: string;
  title: string;
  company: string | null;
  location: string | null;
  remote: boolean;
  url: string;
  description: string | null;
  tags: string[];
  salary: string | null;
  publisher: string | null;
  posted_at: string | null;
  query: string | null;
  role_id: number | null;
  match_score: number;
  matched_skills: string[];
  status: "new" | "saved" | "dismissed";
  saved_job_id: number | null;
  first_seen_at: string;
  fetched_at: string;
}

export interface ExternalLink {
  id: string;
  label: string;
  url: string;
}
