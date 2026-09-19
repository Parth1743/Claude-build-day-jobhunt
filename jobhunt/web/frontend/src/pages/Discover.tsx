import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useLoad, useTask } from "../hooks";
import { useToast } from "../components/Toast";
import { Badge, Chip, EmptyState, ErrorBanner, Field, Spinner, fmtDate } from "../components/ui";
import type { DiscoverInfo, DiscoverRunResult, DiscoverSource, DiscoveredJob, ExternalLink } from "../types";

type ListStatus = "new" | "saved" | "dismissed";

export default function Discover() {
  const toast = useToast();
  const info = useLoad(() => api.discover.info());
  const rolesQ = useLoad(() => api.roles.list());
  const run = useTask<DiscoverRunResult>();

  const [query, setQuery] = useState("");
  const [location, setLocation] = useState<string | null>(null);
  const [remoteOnly, setRemoteOnly] = useState<boolean | null>(null);
  const [roleId, setRoleId] = useState<string>("");
  const [status, setStatus] = useState<ListStatus>("new");
  const [minScore, setMinScore] = useState(0);
  const [source, setSource] = useState("");
  const [text, setText] = useState("");
  const [links, setLinks] = useState<ExternalLink[]>([]);
  const [lastRun, setLastRun] = useState<DiscoverRunResult | null>(null);
  const [showSources, setShowSources] = useState(false);

  const effLocation = location ?? info.data?.location ?? "";
  const effRemote = remoteOnly ?? info.data?.remote_only ?? false;

  const results = useLoad(
    () => api.discover.jobs({ status, min_score: minScore, source: source || undefined, q: text || undefined }),
    [status, minScore, source, text],
  );

  useEffect(() => {
    if (info.data && !query) {
      const first = info.data.suggested_queries[0] || "";
      setQuery(first);
      const role = rolesQ.data?.find((r) => r.title === first);
      if (role) setRoleId(String(role.id));
      setLastRun(info.data.last_run);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [info.data, rolesQ.data]);

  useEffect(() => {
    if (!query.trim()) return setLinks([]);
    const h = setTimeout(() => api.discover.links(query, effLocation, effRemote).then(setLinks).catch(() => setLinks([])), 300);
    return () => clearTimeout(h);
  }, [query, effLocation, effRemote]);

  const search = async () => {
    if (!query.trim()) return toast("Enter what to search for", "error");
    const res = await run.run(() =>
      api.discover.run({ query: query.trim(), location: effLocation, remote_only: effRemote, role_id: roleId ? Number(roleId) : null }),
    );
    if (res) {
      setLastRun(res);
      setStatus("new");
      results.reload();
      info.reload();
      const errors = Object.values(res.per_source).filter((s) => s.error).length;
      toast(`${res.total} openings found, ${res.new} new${errors ? `, ${errors} source${errors > 1 ? "s" : ""} failed` : ""}`, errors && !res.total ? "error" : "success");
    }
  };

  const act = async (fn: () => Promise<unknown>, msg: string) => {
    try {
      await fn();
      toast(msg, "success");
      results.reload();
      info.reload();
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  const sourceLabel = useMemo(() => Object.fromEntries((info.data?.sources || []).map((s) => [s.id, s.label.split(" (")[0]])), [info.data]);
  const enabledConfigured = (info.data?.sources || []).filter((s) => s.enabled && s.configured);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Discover openings</h1>
          <p>Live postings from job boards, ranked against the skills in your ledger. Apply on the source site, or save one to the tracker.</p>
        </div>
        <div className="page-actions">
          <button className="btn" onClick={() => setShowSources(!showSources)}>
            {showSources ? "Hide sources" : `Sources (${enabledConfigured.length} active)`}
          </button>
        </div>
      </div>

      {info.error && <ErrorBanner text={info.error} />}
      {showSources && info.data && (
        <SourcesPanel
          info={info.data}
          onSaved={(d) => {
            info.setData({ ...info.data!, ...d });
            toast("Sources saved", "success");
          }}
        />
      )}

      <div className="card mb-2">
        <div className="card-body">
          <div className="search-row">
            <div className="field" style={{ flex: 2, minWidth: 220 }}>
              <span className="field-label">What</span>
              <input type="text" value={query} onChange={(e) => setQuery(e.target.value)} list="suggested-queries" placeholder="Platform Engineer, Data Analyst, React…" onKeyDown={(e) => e.key === "Enter" && search()} />
              <datalist id="suggested-queries">
                {(info.data?.suggested_queries || []).map((s) => (
                  <option key={s} value={s} />
                ))}
              </datalist>
            </div>
            <div className="field" style={{ flex: 1, minWidth: 160 }}>
              <span className="field-label">Where</span>
              <input type="text" value={effLocation} onChange={(e) => setLocation(e.target.value)} placeholder="Bengaluru, India" />
            </div>
            <div className="field" style={{ minWidth: 160 }}>
              <span className="field-label">Link to role</span>
              <select value={roleId} onChange={(e) => setRoleId(e.target.value)}>
                <option value="">None</option>
                {(rolesQ.data || []).map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.title}
                  </option>
                ))}
              </select>
            </div>
            <label className="check" style={{ alignSelf: "flex-end", paddingBottom: 9 }}>
              <input type="checkbox" checked={effRemote} onChange={(e) => setRemoteOnly(e.target.checked)} /> Remote only
            </label>
            <button className="btn btn-primary" style={{ alignSelf: "flex-end" }} onClick={search} disabled={run.running || !enabledConfigured.length}>
              {run.running ? `Searching… ${run.elapsed}s` : "Search"}
            </button>
          </div>
          {!enabledConfigured.length && info.data && (
            <div className="banner banner-warning mt-2" style={{ marginBottom: 0 }}>
              No job source is active. Open Sources above and enable at least one.
            </div>
          )}
          <ErrorBanner text={run.error} onDismiss={run.clearError} />

          {links.length > 0 && (
            <div className="links-row mt-2">
              <span className="small muted">Open this search on:</span>
              {links.map((l) => (
                <a key={l.id} className="btn btn-sm" href={l.url} target="_blank" rel="noreferrer">
                  {l.label} ↗
                </a>
              ))}
            </div>
          )}

          {lastRun && (
            <div className="row small muted mt-2">
              <span>
                Last search {fmtDate(lastRun.at)} for "{lastRun.query}"{lastRun.location ? ` in ${lastRun.location}` : ""}: {lastRun.total} found, {lastRun.new} new.
              </span>
              {Object.entries(lastRun.per_source).map(([sid, r]) => (
                <Badge key={sid} tone={r.error ? "serious" : "neutral"} icon={r.error ? "!" : undefined}>
                  {sourceLabel[sid] || sid}: {r.error ? r.error.slice(0, 40) : `${r.count}${r.new ? ` (+${r.new})` : ""}`}
                </Badge>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="tabs">
        {(["new", "saved", "dismissed"] as ListStatus[]).map((s) => (
          <button key={s} className={`tab ${status === s ? "active" : ""}`} onClick={() => setStatus(s)}>
            {s === "new" ? "Openings" : s[0].toUpperCase() + s.slice(1)}
            <span className="count">{info.data?.counts[s] ?? ""}</span>
          </button>
        ))}
        <div className="inline-form right" style={{ alignSelf: "center", paddingBottom: 4 }}>
          <input type="text" value={text} onChange={(e) => setText(e.target.value)} placeholder="Filter text" style={{ width: 150, padding: "4px 8px", fontSize: 12 }} />
          <select value={source} onChange={(e) => setSource(e.target.value)} style={{ padding: "4px 8px", fontSize: 12 }}>
            <option value="">All sources</option>
            {(info.data?.sources || []).map((s) => (
              <option key={s.id} value={s.id}>
                {sourceLabel[s.id]}
              </option>
            ))}
          </select>
          <label className="check small">
            Min match
            <input type="number" min={0} max={100} step={5} value={minScore} onChange={(e) => setMinScore(Number(e.target.value))} style={{ width: 60, padding: "4px 6px", fontSize: 12 }} />
          </label>
        </div>
      </div>

      {results.loading && !results.data ? (
        <Spinner label="Loading" />
      ) : !results.data?.length ? (
        <div className="card">
          <EmptyState
            title={status === "new" ? "No openings yet" : `Nothing ${status}`}
            body={status === "new" ? "Run a search above. Results are ranked by how many of your ledger skills each posting mentions." : undefined}
            action={status === "new" && !info.data?.suggested_queries.length ? <Link className="btn" to="/roles">Add a target role first</Link> : undefined}
          />
        </div>
      ) : (
        <div className="stack" style={{ gap: 10 }}>
          {results.data.map((d) => (
            <DiscoveredCard
              key={d.id}
              d={d}
              sourceLabel={sourceLabel[d.source] || d.source}
              onSave={() => act(() => api.discover.save(d.id, roleId ? Number(roleId) : null), "Saved to your applications")}
              onDismiss={() => act(() => api.discover.dismiss(d.id), "Dismissed")}
              onRestore={() => act(() => api.discover.restore(d.id), "Restored")}
            />
          ))}
        </div>
      )}
    </>
  );
}

function MatchScore({ score }: { score: number }) {
  const tone = score >= 60 ? "good" : score >= 35 ? "warning" : "serious";
  return (
    <div className={`match match-${tone}`} title={`Match ${score} of 100 against your ledger`}>
      <div className="match-num">{score}</div>
      <div className="match-label">match</div>
    </div>
  );
}

function DiscoveredCard({ d, sourceLabel, onSave, onDismiss, onRestore }: { d: DiscoveredJob; sourceLabel: string; onSave: () => void; onDismiss: () => void; onRestore: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="card disc-item">
      <div className="disc-head">
        <MatchScore score={d.match_score} />
        <div className="disc-main">
          <div className="row" style={{ gap: 6 }}>
            <a className="disc-title" href={d.url} target="_blank" rel="noreferrer">
              {d.title}
            </a>
            {d.remote && <Badge tone="info">Remote</Badge>}
            <Badge tone="neutral">{d.publisher ? `${d.publisher} via ${sourceLabel}` : sourceLabel}</Badge>
          </div>
          <div className="small muted">
            {d.company || "Unknown company"}
            {d.location && d.location !== "Remote" ? ` · ${d.location}` : ""}
            {d.salary ? ` · ${d.salary}` : ""}
            {d.posted_at ? ` · posted ${fmtDate(d.posted_at)}` : ""}
          </div>
          <div className="chips mt-1">
            {d.matched_skills.map((s) => (
              <Chip key={s} tone="good">
                ✓ {s}
              </Chip>
            ))}
            {d.tags.slice(0, 6).map((t) => (
              <Chip key={t}>{t}</Chip>
            ))}
          </div>
        </div>
        <div className="disc-actions">
          <a className="btn btn-primary btn-sm" href={d.url} target="_blank" rel="noreferrer">
            Apply ↗
          </a>
          {d.status === "saved" ? (
            <Link className="btn btn-sm" to={`/jobs/${d.saved_job_id}`}>
              Open in tracker
            </Link>
          ) : (
            <button className="btn btn-sm" onClick={onSave}>
              Save to tracker
            </button>
          )}
          {d.status === "dismissed" ? (
            <button className="btn btn-ghost btn-sm" onClick={onRestore}>
              Restore
            </button>
          ) : d.status === "new" ? (
            <button className="btn btn-ghost btn-sm" onClick={onDismiss}>
              Dismiss
            </button>
          ) : null}
          <button className="btn btn-ghost btn-sm" onClick={() => setOpen(!open)}>
            {open ? "Less" : "Details"}
          </button>
        </div>
      </div>
      {open && (
        <div className="disc-body">
          <pre className="pre">{(d.description || "No description provided by the source.").slice(0, 2500)}</pre>
        </div>
      )}
    </div>
  );
}

function SourcesPanel({ info, onSaved }: { info: DiscoverInfo; onSaved: (d: DiscoverInfo) => void }) {
  const [enabled, setEnabled] = useState<Set<string>>(new Set(info.sources.filter((s) => s.enabled).map((s) => s.id)));
  const [keys, setKeys] = useState<Record<string, string>>({});
  const [location, setLocation] = useState(info.location);
  const [country, setCountry] = useState(info.country);
  const [remote, setRemote] = useState(info.remote_only);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const toggle = (id: string) => {
    const next = new Set(enabled);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setEnabled(next);
  };

  const save = async () => {
    setSaving(true);
    setErr(null);
    try {
      const d = await api.discover.updateSettings({ location, country, remote_only: remote, sources_enabled: [...enabled], keys });
      setKeys({});
      onSaved(d);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="card mb-2">
      <div className="card-head">
        <h2>Job sources</h2>
        <span className="small muted">LinkedIn and Naukri have no public API; their postings arrive through JSearch and the search links.</span>
      </div>
      <div className="card-body">
        <ErrorBanner text={err} />
        <div className="stack" style={{ gap: 10 }}>
          {info.sources.map((s: DiscoverSource) => (
            <div key={s.id} className="src-row">
              <label className="check" style={{ alignItems: "flex-start" }}>
                <input type="checkbox" checked={enabled.has(s.id)} onChange={() => toggle(s.id)} style={{ marginTop: 3 }} />
                <span>
                  <strong>{s.label}</strong>
                  {s.configured ? <Badge tone="good">ready</Badge> : s.keys.length ? <Badge tone="warning">key needed</Badge> : null}
                  <span className="small muted" style={{ display: "block" }}>
                    {s.notes}{" "}
                    <a href={s.docs} target="_blank" rel="noreferrer">
                      docs ↗
                    </a>
                  </span>
                </span>
              </label>
              {s.keys.length > 0 && (
                <div className="src-keys">
                  {s.keys.map((k) => (
                    <Field key={k.setting} label={k.label} hint={k.status ? `${k.status === "saved" ? "Saved" : `From ${k.env}`} ${k.hint}` : `Or set ${k.env} in .env`}>
                      <input type="password" value={keys[k.setting] ?? ""} onChange={(e) => setKeys({ ...keys, [k.setting]: e.target.value })} placeholder={k.status ? "Replace…" : "Paste key"} autoComplete="off" />
                    </Field>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
        <div className="divider" />
        <div className="form-grid">
          <Field label="Default location" hint="Used by Adzuna and JSearch and in the search links">
            <input type="text" value={location} onChange={(e) => setLocation(e.target.value)} placeholder="Bengaluru, India" />
          </Field>
          <Field label="Country code" hint="Two letters, for Adzuna and JSearch: in, us, gb, de…">
            <input type="text" value={country} onChange={(e) => setCountry(e.target.value)} maxLength={2} style={{ width: 80 }} />
          </Field>
          <label className="check span-2">
            <input type="checkbox" checked={remote} onChange={(e) => setRemote(e.target.checked)} /> Remote jobs only by default
          </label>
        </div>
        <div className="row mt-2">
          <button className="btn btn-primary" onClick={save} disabled={saving}>
            {saving ? "Saving…" : "Save sources"}
          </button>
        </div>
      </div>
    </div>
  );
}
