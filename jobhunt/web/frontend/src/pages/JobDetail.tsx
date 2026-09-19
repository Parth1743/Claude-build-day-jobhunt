import { useEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useCopy, useLoad, useTask } from "../hooks";
import { Markdown } from "../components/Markdown";
import { useToast } from "../components/Toast";
import { Chip, EmptyState, ErrorBanner, FitScore, Spinner, StatusBadge, labelize } from "../components/ui";
import type { AnalyzeResult, JobStatus } from "../types";

const STATUSES: JobStatus[] = ["saved", "applied", "screening", "interview", "offer", "rejected", "withdrawn"];
type Tab = "analysis" | "materials" | "description" | "activity";

export default function JobDetail() {
  const { id } = useParams();
  const jobId = Number(id);
  const [params, setParams] = useSearchParams();
  const toast = useToast();
  const job = useLoad(() => api.jobs.get(jobId), [jobId]);
  const roles = useLoad(() => api.roles.list());
  const analyze = useTask<AnalyzeResult>();
  const { copy, copied } = useCopy();
  const [tab, setTab] = useState<Tab>("analysis");
  const [note, setNote] = useState("");
  const [statusNote, setStatusNote] = useState("");
  const [jd, setJd] = useState<string | null>(null);
  const autoRan = useRef(false);

  const runAnalyze = async () => {
    const res = await analyze.run(() => api.jobs.analyze(jobId));
    if (res) {
      toast(`Fit ${res.analysis.fit_score}/100. Materials saved.`, "success");
      job.reload();
      setTab("analysis");
    }
  };

  useEffect(() => {
    if (params.get("analyze") === "1" && job.data && !autoRan.current) {
      autoRan.current = true;
      setParams({}, { replace: true });
      if (job.data.jd_text) runAnalyze();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job.data]);

  if (job.error) return <div className="banner banner-error">{job.error}</div>;
  if (!job.data) return <Spinner label="Loading" />;
  const j = job.data;
  const a = j.analysis;
  const bullets = [...(j.materials || [])].reverse().find((m) => m.kind === "bullets");
  const letter = [...(j.materials || [])].reverse().find((m) => m.kind === "cover_letter");

  const changeStatus = async (s: JobStatus) => {
    try {
      await api.jobs.setStatus(jobId, s, statusNote || undefined);
      setStatusNote("");
      toast(`Now ${labelize(s)}`, "success");
      job.reload();
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };
  const addNote = async () => {
    if (!note.trim()) return;
    await api.jobs.addNote(jobId, note.trim());
    setNote("");
    job.reload();
  };
  const saveJd = async () => {
    if (jd === null) return;
    await api.jobs.update(jobId, { jd_text: jd });
    setJd(null);
    toast("Description saved", "success");
    job.reload();
  };
  const changeRole = async (v: string) => {
    await api.jobs.update(jobId, { role_id: v ? Number(v) : null });
    job.reload();
  };

  return (
    <>
      <div className="crumbs">
        <Link to="/jobs">Jobs</Link> / {j.company}
      </div>
      <div className="page-head">
        <div>
          <h1>{j.title}</h1>
          <p>
            {j.company}
            {j.location ? ` · ${j.location}` : ""}
            {j.url && (
              <>
                {" · "}
                <a href={j.url} target="_blank" rel="noreferrer">
                  posting ↗
                </a>
              </>
            )}
          </p>
        </div>
        <div className="page-actions">
          <select value={j.role_id ?? ""} onChange={(e) => changeRole(e.target.value)} aria-label="Target role" style={{ width: "auto" }}>
            <option value="">No target role</option>
            {(roles.data || []).map((r) => (
              <option key={r.id} value={r.id}>
                {r.title}
              </option>
            ))}
          </select>
          <button className="btn btn-primary" onClick={runAnalyze} disabled={analyze.running || !j.jd_text}>
            {analyze.running ? `Analyzing… ${analyze.elapsed}s` : a ? "Re-analyze" : "Analyze fit"}
          </button>
        </div>
      </div>

      <ErrorBanner text={analyze.error} onDismiss={analyze.clearError} />
      {analyze.running && <div className="banner banner-info">Claude is comparing the posting with your ledger and drafting materials. This typically takes one to three minutes.</div>}

      <div className="grid grid-3 mb-2">
        <div className="card stat">
          <div className="stat-label">Fit score</div>
          <div style={{ marginTop: 6 }}>{a ? <FitScore score={a.fit_score} size="lg" /> : <span className="muted">Not analyzed</span>}</div>
        </div>
        <div className="card stat">
          <div className="stat-label">Status</div>
          <div className="row mt-1">
            <StatusBadge status={j.status} />
            {j.applied_at && <span className="small muted">applied {j.applied_at.slice(0, 10)}</span>}
          </div>
          <div className="inline-form mt-1">
            <select value={j.status} onChange={(e) => changeStatus(e.target.value as JobStatus)} aria-label="Change status">
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {labelize(s)}
                </option>
              ))}
            </select>
            <input className="grow" type="text" value={statusNote} onChange={(e) => setStatusNote(e.target.value)} placeholder="Optional note with the change" style={{ minWidth: 120 }} />
          </div>
        </div>
        <div className="card stat">
          <div className="stat-label">Skill match</div>
          {a ? (
            <>
              <div className="stat-value">
                {a.matched_skills.length}
                <span className="muted" style={{ fontSize: 16 }}>
                  /{a.matched_skills.length + a.missing_skills.length}
                </span>
              </div>
              <div className="stat-sub">{a.missing_skills.length} required skills missing</div>
            </>
          ) : (
            <div className="stat-sub mt-1">Run the analysis to see matched and missing skills.</div>
          )}
        </div>
      </div>

      <div className="tabs">
        {(["analysis", "materials", "description", "activity"] as Tab[]).map((t) => (
          <button key={t} className={`tab ${tab === t ? "active" : ""}`} onClick={() => setTab(t)}>
            {labelize(t)}
          </button>
        ))}
      </div>

      {tab === "analysis" && (
        <div className="card">
          <div className="card-body">
            {!a ? (
              <EmptyState title="No analysis yet" body={j.jd_text ? "Run the fit analysis to score this posting against your ledger." : "Add the job description first, then run the analysis."} />
            ) : (
              <div className="grid grid-2">
                <div className="stack">
                  <div>
                    <div className="section-title">Summary</div>
                    <p>{a.fit_summary}</p>
                  </div>
                  <div>
                    <div className="section-title">Matched skills</div>
                    <div className="chips">
                      {a.matched_skills.map((s) => (
                        <Chip key={s} tone="good">
                          ✓ {s}
                        </Chip>
                      ))}
                      {a.matched_skills.length === 0 && <span className="muted">none</span>}
                    </div>
                  </div>
                  <div>
                    <div className="section-title">Missing skills</div>
                    <div className="chips">
                      {a.missing_skills.map((s) => (
                        <Chip key={s} tone="gap">
                          ○ {s}
                        </Chip>
                      ))}
                      {a.missing_skills.length === 0 && <span className="muted">none</span>}
                    </div>
                    {a.missing_skills.length > 0 && j.role_id && (
                      <p className="small muted mt-1">
                        These gaps feed the <Link to={`/roles/${j.role_id}`}>{j.role_title} roadmap</Link>.
                      </p>
                    )}
                  </div>
                </div>
                <div className="stack">
                  <div>
                    <div className="section-title">Keywords to mirror</div>
                    <div className="chips">
                      {a.keywords_to_include.map((s) => (
                        <Chip key={s} tone="accent">
                          {s}
                        </Chip>
                      ))}
                    </div>
                  </div>
                  <div>
                    <div className="section-title">Red flags</div>
                    {a.red_flags.length === 0 ? (
                      <span className="muted">None noted</span>
                    ) : (
                      <ul style={{ margin: 0, paddingLeft: "1.2em" }}>
                        {a.red_flags.map((f, i) => (
                          <li key={i}>{f}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                  <div>
                    <div className="section-title">Posting requires</div>
                    <div className="chips">
                      {a.required_skills.map((s) => (
                        <Chip key={s}>{s}</Chip>
                      ))}
                    </div>
                    {a.nice_to_have.length > 0 && (
                      <>
                        <div className="small muted mt-1 mb-1">Nice to have</div>
                        <div className="chips">
                          {a.nice_to_have.map((s) => (
                            <Chip key={s}>{s}</Chip>
                          ))}
                        </div>
                      </>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {tab === "materials" && (
        <div className="grid grid-2">
          <div className="card">
            <div className="card-head">
              <h2>Tailored resume bullets</h2>
              {bullets && (
                <button className="btn btn-sm" onClick={() => copy("bullets", stripRefs(bullets.content))}>
                  {copied === "bullets" ? "Copied" : "Copy"}
                </button>
              )}
            </div>
            <div className="card-body">{bullets ? <Markdown text={bullets.content} /> : <EmptyState title="Nothing yet" body="Run the analysis to generate bullets grounded in your ledger." />}</div>
          </div>
          <div className="card">
            <div className="card-head">
              <h2>Cover letter</h2>
              {letter && (
                <button className="btn btn-sm" onClick={() => copy("letter", letter.content)}>
                  {copied === "letter" ? "Copied" : "Copy"}
                </button>
              )}
            </div>
            <div className="card-body">{letter ? <Markdown text={letter.content} /> : <EmptyState title="Nothing yet" />}</div>
          </div>
        </div>
      )}

      {tab === "description" && (
        <div className="card">
          <div className="card-head">
            <h2>Job description</h2>
            <div className="row">
              {jd === null ? (
                <button className="btn btn-sm" onClick={() => setJd(j.jd_text || "")}>
                  {j.jd_text ? "Edit" : "Add description"}
                </button>
              ) : (
                <>
                  <button className="btn btn-sm" onClick={() => setJd(null)}>
                    Cancel
                  </button>
                  <button className="btn btn-sm btn-primary" onClick={saveJd}>
                    Save
                  </button>
                </>
              )}
            </div>
          </div>
          <div className="card-body">
            {jd !== null ? <textarea className="jd" value={jd} onChange={(e) => setJd(e.target.value)} autoFocus /> : j.jd_text ? <pre className="pre">{j.jd_text}</pre> : <EmptyState title="No description" body="Paste the posting so Claude can score it." />}
          </div>
        </div>
      )}

      {tab === "activity" && (
        <div className="grid grid-2">
          <div className="card">
            <div className="card-head">
              <h2>Notes</h2>
            </div>
            <div className="card-body">
              <div className="inline-form mb-2">
                <input className="grow" type="text" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Recruiter call went well, follow up Friday…" onKeyDown={(e) => e.key === "Enter" && addNote()} />
                <button className="btn" onClick={addNote} disabled={!note.trim()}>
                  Add note
                </button>
              </div>
              {j.notes ? <pre className="pre">{j.notes}</pre> : <span className="muted">No notes yet.</span>}
            </div>
          </div>
          <div className="card">
            <div className="card-head">
              <h2>Status history</h2>
            </div>
            <div className="card-body">
              <ul className="timeline">
                {(j.history || []).map((h) => (
                  <li key={h.id}>
                    <time>{h.at.replace("T", " ").slice(0, 16)}</time>
                    <span>
                      <StatusBadge status={h.to_status} /> {h.note && <span className="muted">{h.note}</span>}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function stripRefs(md: string) {
  return md
    .split("\n")
    .filter((l) => !l.trim().startsWith("_from:"))
    .map((l) => l.replace(/\s+$/, ""))
    .join("\n");
}
