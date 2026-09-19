import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, splitCsv } from "../api";
import { useLoad, useTask } from "../hooks";
import { Modal } from "../components/Modal";
import { useToast } from "../components/Toast";
import { Badge, Chip, EmptyState, ErrorBanner, Field, Spinner, dateRange, fmtDate } from "../components/ui";
import type { ExtractResult, LedgerEntry, LedgerInput, LedgerKind, SkillLevel } from "../types";

const KINDS: LedgerKind[] = ["experience", "project", "education", "certification", "achievement", "skill"];
const LEVELS: SkillLevel[] = ["beginner", "intermediate", "advanced", "expert"];

export default function Ledger() {
  const [params, setParams] = useSearchParams();
  const [kind, setKind] = useState<string>("");
  const [showRetired, setShowRetired] = useState(false);
  const [view, setView] = useState<"entries" | "skills" | "history">("entries");
  const [editing, setEditing] = useState<LedgerEntry | "new" | null>(null);
  const [importing, setImporting] = useState(params.get("import") === "1");
  const toast = useToast();

  const entries = useLoad(() => api.ledger.list(kind || undefined, showRetired), [kind, showRetired]);
  const skills = useLoad(() => api.ledger.skills(), [entries.data]);
  const history = useLoad(() => api.ledger.history(), [entries.data]);

  useEffect(() => {
    if (params.get("import")) setParams({}, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const e of entries.data || []) c[e.kind] = (c[e.kind] || 0) + 1;
    return c;
  }, [entries.data]);

  const retire = async (e: LedgerEntry) => {
    if (!confirm(`Retire "${e.title}"? It stays in history but leaves your active profile.`)) return;
    try {
      await api.ledger.retire(e.id);
      toast("Entry retired", "success");
      entries.reload();
    } catch (err) {
      toast(String((err as Error).message), "error");
    }
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Ledger</h1>
          <p>Your experience, projects, education, certifications and skills. Nothing is ever deleted.</p>
        </div>
        <div className="page-actions">
          <a className="btn" href="/api/ledger/export" target="_blank" rel="noreferrer">
            Export Markdown
          </a>
          <button className="btn" onClick={() => setImporting(true)}>
            Import resume
          </button>
          <button className="btn btn-primary" onClick={() => setEditing("new")}>
            Add entry
          </button>
        </div>
      </div>

      <div className="tabs">
        <button className={`tab ${view === "entries" ? "active" : ""}`} onClick={() => setView("entries")}>
          Entries<span className="count">{entries.data?.length ?? ""}</span>
        </button>
        <button className={`tab ${view === "skills" ? "active" : ""}`} onClick={() => setView("skills")}>
          Skills<span className="count">{skills.data?.length ?? ""}</span>
        </button>
        <button className={`tab ${view === "history" ? "active" : ""}`} onClick={() => setView("history")}>
          History
        </button>
      </div>

      {view === "entries" && (
        <div className="card">
          <div className="card-head">
            <div className="row">
              <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Filter by kind">
                <option value="">All kinds</option>
                {KINDS.map((k) => (
                  <option key={k} value={k}>
                    {k[0].toUpperCase() + k.slice(1)} {counts[k] ? `(${counts[k]})` : ""}
                  </option>
                ))}
              </select>
              <label className="check">
                <input type="checkbox" checked={showRetired} onChange={(e) => setShowRetired(e.target.checked)} /> Show retired
              </label>
            </div>
          </div>
          <div className="card-body tight">
            <ErrorBanner text={entries.error} />
            {entries.loading && !entries.data ? (
              <div className="card-body">
                <Spinner label="Loading" />
              </div>
            ) : !entries.data?.length ? (
              <EmptyState
                title="Your ledger is empty"
                body="Import a resume to have Claude extract entries, or add them one by one."
                action={
                  <div className="row" style={{ justifyContent: "center" }}>
                    <button className="btn btn-primary" onClick={() => setImporting(true)}>
                      Import resume
                    </button>
                    <button className="btn" onClick={() => setEditing("new")}>
                      Add manually
                    </button>
                  </div>
                }
              />
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th>Kind</th>
                    <th>Title</th>
                    <th>Dates</th>
                    <th>Skills</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {entries.data.map((e) => (
                    <tr key={e.id} className={e.active ? "" : "retired"}>
                      <td>
                        <span className="kind-tag">{e.kind}</span>
                      </td>
                      <td className="title-cell">
                        <strong>{e.title}</strong>
                        {e.kind === "skill" && e.level && <Badge tone="accent">{e.level}</Badge>}
                        {e.org && <span className="sub">{e.org}</span>}
                      </td>
                      <td className="nowrap muted">{dateRange(e.start_date, e.end_date)}</td>
                      <td>
                        <div className="chips">
                          {e.skills.slice(0, 6).map((s) => (
                            <Chip key={s}>{s}</Chip>
                          ))}
                          {e.skills.length > 6 && <Chip>+{e.skills.length - 6}</Chip>}
                        </div>
                      </td>
                      <td className="nowrap" style={{ textAlign: "right" }}>
                        <button className="btn btn-ghost btn-sm" onClick={() => setEditing(e)}>
                          Edit
                        </button>
                        {e.active ? (
                          <button className="btn btn-ghost btn-sm" onClick={() => retire(e)}>
                            Retire
                          </button>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}

      {view === "skills" && (
        <div className="card">
          <div className="card-body tight">
            {!skills.data?.length ? (
              <EmptyState title="No skills yet" body="Skills come from dedicated skill entries and from the skills attached to experience and projects." />
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th>Skill</th>
                    <th>Level</th>
                    <th>Evidence</th>
                  </tr>
                </thead>
                <tbody>
                  {skills.data.map((s) => (
                    <tr key={s.name}>
                      <td>
                        <strong>{s.name}</strong>
                      </td>
                      <td>{s.level ? <Badge tone="accent">{s.level}</Badge> : <span className="muted">—</span>}</td>
                      <td className="muted">{s.evidence.join("; ") || "stated directly"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}

      {view === "history" && (
        <div className="card">
          <div className="card-body tight">
            <table className="table">
              <thead>
                <tr>
                  <th>When</th>
                  <th>Action</th>
                  <th>Entry</th>
                  <th>Source</th>
                </tr>
              </thead>
              <tbody>
                {(history.data || []).map((h) => (
                  <tr key={h.id}>
                    <td className="nowrap muted tabular">{h.at.replace("T", " ").slice(0, 16)}</td>
                    <td>
                      <Badge tone={h.action === "retire" ? "muted" : h.action === "create" ? "good" : "info"}>{h.action}</Badge>
                    </td>
                    <td>
                      <span className="kind-tag">{h.snapshot.kind}</span> {h.snapshot.title}
                    </td>
                    <td className="muted">{h.source}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {editing && (
        <EntryModal
          entry={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            entries.reload();
          }}
        />
      )}
      {importing && (
        <ImportModal
          onClose={() => setImporting(false)}
          onSaved={() => {
            setImporting(false);
            entries.reload();
          }}
        />
      )}
    </>
  );
}

/* ---------------------------------------------------------------- entry form */

function EntryModal({ entry, onClose, onSaved }: { entry: LedgerEntry | null; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const [form, setForm] = useState({
    kind: (entry?.kind ?? "experience") as LedgerKind,
    title: entry?.title ?? "",
    org: entry?.org ?? "",
    start_date: entry?.start_date ?? "",
    end_date: entry?.end_date ?? "",
    description: entry?.description ?? "",
    skills: entry?.skills.join(", ") ?? "",
    level: (entry?.level ?? "") as SkillLevel | "",
    url: entry?.url ?? "",
  });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const history = useLoad(() => (entry ? api.ledger.history(entry.id) : Promise.resolve([])), [entry?.id]);
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setForm({ ...form, [k]: e.target.value });

  const submit = async () => {
    if (!form.title.trim()) return setErr("Title is required.");
    setSaving(true);
    setErr(null);
    const body: LedgerInput = {
      kind: form.kind,
      title: form.title.trim(),
      org: form.org || null,
      start_date: form.start_date || null,
      end_date: form.end_date || null,
      description: form.description || null,
      skills: splitCsv(form.skills),
      level: form.kind === "skill" && form.level ? form.level : null,
      url: form.url || null,
    };
    try {
      if (entry) await api.ledger.update(entry.id, body);
      else await api.ledger.create(body);
      toast(entry ? "Entry updated" : "Entry added", "success");
      onSaved();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={entry ? `Edit #${entry.id}` : "New ledger entry"}
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" onClick={submit} disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </button>
        </>
      }
    >
      <ErrorBanner text={err} />
      <div className="form-grid">
        <Field label="Kind">
          <select value={form.kind} onChange={set("kind")}>
            {KINDS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
        </Field>
        {form.kind === "skill" ? (
          <Field label="Level">
            <select value={form.level} onChange={set("level")}>
              <option value="">not set</option>
              {LEVELS.map((l) => (
                <option key={l} value={l}>
                  {l}
                </option>
              ))}
            </select>
          </Field>
        ) : (
          <Field label="Organisation">
            <input type="text" value={form.org} onChange={set("org")} placeholder="Company, school, issuer" />
          </Field>
        )}
        <Field label="Title" span2>
          <input type="text" value={form.title} onChange={set("title")} placeholder={form.kind === "skill" ? "e.g. Kubernetes" : "e.g. Backend Engineer"} autoFocus />
        </Field>
        <Field label="Start" hint="YYYY-MM or YYYY">
          <input type="text" value={form.start_date} onChange={set("start_date")} placeholder="2022-01" />
        </Field>
        <Field label="End" hint="Leave blank if ongoing">
          <input type="text" value={form.end_date} onChange={set("end_date")} placeholder="2024-06" />
        </Field>
        <Field label="Description" span2>
          <textarea value={form.description} onChange={set("description")} placeholder="What you did and the outcomes, with numbers where you have them." />
        </Field>
        <Field label="Skills" hint="Comma separated" span2>
          <input type="text" value={form.skills} onChange={set("skills")} placeholder="Python, PostgreSQL, Docker" />
        </Field>
        <Field label="Link" span2>
          <input type="url" value={form.url} onChange={set("url")} placeholder="https://" />
        </Field>
      </div>
      {entry && history.data && history.data.length > 0 && (
        <>
          <div className="divider" />
          <div className="section-title">History</div>
          <ul className="timeline">
            {history.data.map((h) => (
              <li key={h.id}>
                <time>{h.at.replace("T", " ").slice(0, 16)}</time>
                <span>
                  {h.action} <span className="muted">· {h.source}</span>
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </Modal>
  );
}

/* ------------------------------------------------------------- import flow */

function ImportModal({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const task = useTask<ExtractResult>();
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<ExtractResult | null>(null);
  const [selected, setSelected] = useState<boolean[]>([]);
  const [saving, setSaving] = useState(false);

  const extract = async () => {
    if (!file) return;
    const r = await task.run(() => api.ledger.import(file));
    if (r) {
      setResult(r);
      setSelected(r.entries.map(() => true));
    }
  };

  const commit = async () => {
    if (!result) return;
    setSaving(true);
    try {
      const chosen = result.entries.filter((_, i) => selected[i]);
      const res = await api.ledger.commit(chosen, result.source);
      toast(`Saved ${res.saved} entries${res.skipped.length ? `, ${res.skipped.length} skipped` : ""}`, "success");
      onSaved();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title="Import resume"
      onClose={onClose}
      wide
      footer={
        result ? (
          <>
            <button className="btn" onClick={() => setResult(null)}>
              Back
            </button>
            <button className="btn btn-primary" onClick={commit} disabled={saving || !selected.some(Boolean)}>
              {saving ? "Saving…" : `Save ${selected.filter(Boolean).length} entries`}
            </button>
          </>
        ) : (
          <>
            <button className="btn" onClick={onClose}>
              Cancel
            </button>
            <button className="btn btn-primary" onClick={extract} disabled={!file || task.running}>
              {task.running ? `Extracting… ${task.elapsed}s` : "Extract with Claude"}
            </button>
          </>
        )
      }
    >
      <ErrorBanner text={task.error} onDismiss={task.clearError} />
      {!result ? (
        <>
          <p className="muted">Upload a PDF, Markdown or text resume. Claude proposes ledger entries and you pick which to keep. Nothing is saved until you confirm.</p>
          <Field label="Resume file">
            <input type="file" accept=".pdf,.md,.txt" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </Field>
          {task.running && (
            <div className="mt-2">
              <Spinner label="Reading your resume. This usually takes 20 to 60 seconds." />
            </div>
          )}
        </>
      ) : (
        <>
          {result.notes && <div className="banner banner-warning">{result.notes}</div>}
          <div className="row row-between mb-1">
            <span className="muted small">{result.entries.length} proposed entries</span>
            <span className="row">
              <button className="btn btn-ghost btn-sm" onClick={() => setSelected(selected.map(() => true))}>
                Select all
              </button>
              <button className="btn btn-ghost btn-sm" onClick={() => setSelected(selected.map(() => false))}>
                None
              </button>
            </span>
          </div>
          <table className="table">
            <thead>
              <tr>
                <th></th>
                <th>Kind</th>
                <th>Title</th>
                <th>Dates</th>
                <th>Skills</th>
              </tr>
            </thead>
            <tbody>
              {result.entries.map((e, i) => (
                <tr key={i}>
                  <td>
                    <input type="checkbox" checked={selected[i]} onChange={(ev) => setSelected(selected.map((s, j) => (j === i ? ev.target.checked : s)))} aria-label={`Include ${e.title}`} />
                  </td>
                  <td>
                    <span className="kind-tag">{e.kind}</span>
                  </td>
                  <td className="title-cell">
                    <strong>{e.title}</strong>
                    {e.org && <span className="sub">{e.org}</span>}
                    {e.description && <span className="sub">{e.description}</span>}
                  </td>
                  <td className="nowrap muted">{dateRange(e.start_date ?? null, e.end_date ?? null)}</td>
                  <td>
                    <div className="chips">
                      {e.skills.slice(0, 5).map((s) => (
                        <Chip key={s}>{s}</Chip>
                      ))}
                      {e.skills.length > 5 && <Chip>+{e.skills.length - 5}</Chip>}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted small mt-1">Imported {fmtDate(new Date().toISOString())} from {result.source.replace("import:", "")}. You can edit any entry afterwards.</p>
        </>
      )}
    </Modal>
  );
}
