import type {
  AppConfig,
  Dashboard,
  DiscoverInfo,
  DiscoverRunResult,
  DiscoveredJob,
  ExternalLink,
  Funnel,
  Job,
  JobStatus,
  LedgerEntry,
  LedgerEvent,
  LedgerInput,
  RoadmapItem,
  RoadmapStatus,
  Role,
  SettingsInfo,
  SettingsUpdate,
  SkillSummary,
  Task,
} from "./types";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {};
  if (init.body && !(init.body instanceof FormData)) headers["Content-Type"] = "application/json";
  const res = await fetch(path, { ...init, headers: { ...headers, ...(init.headers as Record<string, string>) } });
  const text = await res.text();
  if (!res.ok) {
    let detail = text;
    try {
      const parsed = JSON.parse(text);
      detail = typeof parsed.detail === "string" ? parsed.detail : JSON.stringify(parsed.detail);
    } catch {
      /* plain text error */
    }
    throw new ApiError(res.status, detail || res.statusText);
  }
  if (!text) return undefined as T;
  const ct = res.headers.get("content-type") || "";
  return (ct.includes("application/json") ? JSON.parse(text) : text) as T;
}

const json = (body: unknown) => JSON.stringify(body);

export const api = {
  config: () => request<AppConfig>("/api/config"),
  dashboard: () => request<Dashboard>("/api/status"),
  task: <T>(id: string) => request<Task<T>>(`/api/tasks/${id}`),

  ledger: {
    list: (kind?: string, includeInactive = false) => {
      const q = new URLSearchParams();
      if (kind) q.set("kind", kind);
      if (includeInactive) q.set("include_inactive", "true");
      return request<LedgerEntry[]>(`/api/ledger?${q}`);
    },
    get: (id: number) => request<LedgerEntry>(`/api/ledger/${id}`),
    create: (body: LedgerInput) => request<LedgerEntry>("/api/ledger", { method: "POST", body: json(body) }),
    update: (id: number, body: Partial<LedgerInput>) =>
      request<LedgerEntry>(`/api/ledger/${id}`, { method: "PATCH", body: json(body) }),
    retire: (id: number) => request<LedgerEntry>(`/api/ledger/${id}`, { method: "DELETE" }),
    history: (id?: number) => request<LedgerEvent[]>(id ? `/api/ledger/${id}/history` : "/api/ledger/history"),
    skills: () => request<SkillSummary[]>("/api/ledger/skills"),
    import: (file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      return request<Task>("/api/ledger/import", { method: "POST", body: fd });
    },
    commit: (entries: LedgerInput[], source: string) =>
      request<{ saved: number; skipped: string[] }>("/api/ledger/import/commit", {
        method: "POST",
        body: json({ entries, source }),
      }),
  },

  roles: {
    list: () => request<Role[]>("/api/roles"),
    get: (id: number) => request<Role>(`/api/roles/${id}`),
    create: (body: {
      title: string;
      description?: string | null;
      required_skills: string[];
      nice_to_have: string[];
      priority: number;
    }) => request<Role>("/api/roles", { method: "POST", body: json(body) }),
    update: (
      id: number,
      body: { description?: string; required_skills?: string[]; nice_to_have?: string[]; priority?: number },
    ) => request<Role>(`/api/roles/${id}`, { method: "PATCH", body: json(body) }),
    suggest: (title: string, hint?: string) =>
      request<Task>("/api/roles/suggest", { method: "POST", body: json({ title, hint: hint || null }) }),
    roadmap: (id: number) => request<RoadmapItem[]>(`/api/roles/${id}/roadmap`),
    generate: (id: number, body: { hours: number; weeks: number; include_jobs: boolean }) =>
      request<Task>(`/api/roles/${id}/roadmap/generate`, { method: "POST", body: json(body) }),
  },

  roadmap: {
    setStatus: (
      itemId: number,
      body: { status: RoadmapStatus; level?: string | null; proof?: string | null; add_to_ledger?: boolean },
    ) => request<RoadmapItem>(`/api/roadmap/${itemId}/status`, { method: "POST", body: json(body) }),
  },

  discover: {
    info: () => request<DiscoverInfo>("/api/discover"),
    updateSettings: (body: {
      location?: string;
      country?: string;
      remote_only?: boolean;
      sources_enabled?: string[];
      keys?: Record<string, string>;
    }) => request<DiscoverInfo>("/api/discover/settings", { method: "PUT", body: json(body) }),
    run: (body: { query: string; location?: string; remote_only?: boolean; role_id?: number | null; sources?: string[] }) =>
      request<Task<DiscoverRunResult>>("/api/discover/run", { method: "POST", body: json(body) }),
    links: (query: string, location = "", remoteOnly = false) => {
      const q = new URLSearchParams({ query, location, remote_only: String(remoteOnly) });
      return request<ExternalLink[]>(`/api/discover/links?${q}`);
    },
    jobs: (opts: { status?: string; min_score?: number; source?: string; q?: string; remote_only?: boolean } = {}) => {
      const q = new URLSearchParams();
      if (opts.status) q.set("status", opts.status);
      if (opts.min_score) q.set("min_score", String(opts.min_score));
      if (opts.source) q.set("source", opts.source);
      if (opts.q) q.set("q", opts.q);
      if (opts.remote_only) q.set("remote_only", "true");
      return request<DiscoveredJob[]>(`/api/discover/jobs?${q}`);
    },
    save: (id: number, roleId?: number | null) =>
      request<DiscoveredJob>(`/api/discover/jobs/${id}/save`, { method: "POST", body: json({ role_id: roleId ?? null }) }),
    dismiss: (id: number) => request<DiscoveredJob>(`/api/discover/jobs/${id}/dismiss`, { method: "POST" }),
    restore: (id: number) => request<DiscoveredJob>(`/api/discover/jobs/${id}/restore`, { method: "POST" }),
  },

  settings: {
    get: () => request<SettingsInfo>("/api/settings"),
    update: (body: SettingsUpdate) => request<SettingsInfo>("/api/settings", { method: "PUT", body: json(body) }),
    test: (provider?: string) =>
      request<Task>("/api/settings/test", { method: "POST", body: json(provider ? { provider } : {}) }),
  },

  jobs: {
    list: (status?: string, includeClosed = true) => {
      const q = new URLSearchParams();
      if (status) q.set("status", status);
      if (!includeClosed) q.set("include_closed", "false");
      return request<Job[]>(`/api/jobs?${q}`);
    },
    funnel: () => request<Funnel>("/api/jobs/funnel"),
    get: (id: number) => request<Job>(`/api/jobs/${id}`),
    create: (body: {
      company: string;
      title: string;
      url?: string | null;
      location?: string | null;
      role_id?: number | null;
      jd_text?: string | null;
    }) => request<Job>("/api/jobs", { method: "POST", body: json(body) }),
    update: (
      id: number,
      body: { company?: string; title?: string; url?: string | null; location?: string | null; role_id?: number | null; jd_text?: string },
    ) => request<Job>(`/api/jobs/${id}`, { method: "PATCH", body: json(body) }),
    setStatus: (id: number, status: JobStatus, note?: string) =>
      request<Job>(`/api/jobs/${id}/status`, { method: "POST", body: json({ status, note: note || null }) }),
    addNote: (id: number, text: string) =>
      request<Job>(`/api/jobs/${id}/notes`, { method: "POST", body: json({ text }) }),
    analyze: (id: number) => request<Task>(`/api/jobs/${id}/analyze`, { method: "POST" }),
  },
};

/** Poll a background task until it finishes. Resolves with the result or rejects with the error. */
export function waitForTask<T>(taskId: string, onTick?: (t: Task<T>) => void, intervalMs = 1500): Promise<T> {
  return new Promise((resolve, reject) => {
    const tick = async () => {
      try {
        const t = await api.task<T>(taskId);
        onTick?.(t);
        if (t.status === "done") return resolve(t.result as T);
        if (t.status === "error") return reject(new Error(t.error || "Task failed"));
        setTimeout(tick, intervalMs);
      } catch (e) {
        reject(e);
      }
    };
    tick();
  });
}

export const splitCsv = (s: string) =>
  s
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);
