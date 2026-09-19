import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { useLoad, useTask } from "../hooks";
import { Modal } from "../components/Modal";
import { useToast } from "../components/Toast";
import { Badge, Chip, EmptyState, ErrorBanner, Field, FitScore, Progress, ROADMAP_STATUS_TONE, Spinner, StatusBadge, labelize } from "../components/ui";
import { RoleModal } from "./Roles";
import type { RoadmapItem, RoadmapResult, SkillLevel } from "../types";

export default function RoleDetail() {
  const { id } = useParams();
  const roleId = Number(id);
  const nav = useNavigate();
  const toast = useToast();
  const role = useLoad(() => api.roles.get(roleId), [roleId]);
  const roadmap = useLoad(() => api.roles.roadmap(roleId), [roleId]);
  const jobs = useLoad(() => api.jobs.list(), [roleId]);
  const gen = useTask<RoadmapResult>();
  const [editing, setEditing] = useState(false);
  const [genForm, setGenForm] = useState({ hours: 8, weeks: 12, include_jobs: true });
  const [summary, setSummary] = useState<RoadmapResult | null>(null);
  const [completing, setCompleting] = useState<RoadmapItem | null>(null);
  const [showClosed, setShowClosed] = useState(false);

  if (role.error) return <div className="banner banner-error">{role.error}</div>;
  if (!role.data) return <Spinner label="Loading" />;
  const r = role.data;
  const covered = r.coverage.required.filter((c) => c.have).length;
  const linkedJobs = (jobs.data || []).filter((j) => j.role_id === r.id);
  const items = roadmap.data || [];
  const open = items.filter((i) => i.status === "todo" || i.status === "in_progress");
  const closed = items.filter((i) => i.status === "done" || i.status === "skipped");
  const openWeeks = open.reduce((n, i) => n + (i.est_weeks || 0), 0);

  const generate = async () => {
    const res = await gen.run(() => api.roles.generate(r.id, genForm));
    if (res) {
      setSummary(res);
      roadmap.reload();
      toast(`Roadmap built with ${res.item_ids.length} items`, "success");
    }
  };

  const setStatus = async (item: RoadmapItem, status: "todo" | "in_progress" | "skipped") => {
    try {
      await api.roadmap.setStatus(item.id, { status });
      roadmap.reload();
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  return (
    <>
      <div className="crumbs">
        <Link to="/roles">Target roles</Link> / {r.title}
      </div>
      <div className="page-head">
        <div>
          <h1>{r.title}</h1>
          {r.description && <p>{r.description}</p>}
        </div>
        <div className="page-actions">
          <Badge tone={r.priority === 1 ? "accent" : "neutral"}>Priority {r.priority}</Badge>
          <button className="btn" onClick={() => setEditing(true)}>
            Edit role
          </button>
        </div>
      </div>

      <div className="grid grid-3 mb-2">
        <div className="card stat">
          <div className="stat-label">Required skills covered</div>
          <div className="stat-value">
            {covered}
            <span className="muted" style={{ fontSize: 16 }}>
              /{r.required_skills.length}
            </span>
          </div>
          <Progress value={covered} max={r.required_skills.length} label="coverage" />
        </div>
        <div className="card stat">
          <div className="stat-label">Roadmap items open</div>
          <div className="stat-value">{open.length}</div>
          <div className="stat-sub">about {openWeeks.toFixed(0)} weeks of work remaining</div>
        </div>
        <div className="card stat">
          <div className="stat-label">Linked jobs</div>
          <div className="stat-value">{linkedJobs.length}</div>
          <div className="stat-sub">{linkedJobs.filter((j) => j.jd_text).length} with descriptions to learn from</div>
        </div>
      </div>

      <div className="grid grid-2 mb-2">
        <div className="card">
          <div className="card-head">
            <h2>Skill coverage</h2>
          </div>
          <div className="card-body">
            <div className="section-title">Required</div>
            {r.coverage.required.length === 0 ? (
              <p className="muted">No required skills listed. Edit the role or let Claude suggest them.</p>
            ) : (
              <div className="chips mb-2">
                {r.coverage.required.map((c) => (
                  <Chip key={c.skill} tone={c.have ? "good" : "gap"} title={c.have ? "In your ledger" : "Gap"}>
                    {c.have ? "✓" : "○"} {c.skill}
                  </Chip>
                ))}
              </div>
            )}
            {r.coverage.nice_to_have.length > 0 && (
              <>
                <div className="section-title">Nice to have</div>
                <div className="chips">
                  {r.coverage.nice_to_have.map((c) => (
                    <Chip key={c.skill} tone={c.have ? "good" : "neutral"}>
                      {c.have ? "✓" : "○"} {c.skill}
                    </Chip>
                  ))}
                </div>
              </>
            )}
          </div>
        </div>

        <div className="card">
          <div className="card-head">
            <h2>Linked jobs</h2>
            <Link to="/jobs" className="small">
              All jobs
            </Link>
          </div>
          <div className="card-body tight">
            {linkedJobs.length === 0 ? (
              <EmptyState title="No jobs linked" body="Assign this role when saving a job so its description feeds the roadmap." />
            ) : (
              <table className="table">
                <tbody>
                  {linkedJobs.map((j) => (
                    <tr key={j.id} className="clickable" onClick={() => nav(`/jobs/${j.id}`)}>
                      <td className="title-cell">
                        <strong>{j.title}</strong>
                        <span className="sub">{j.company}</span>
                      </td>
                      <td>
                        <StatusBadge status={j.status} />
                      </td>
                      <td>
                        <FitScore score={j.fit_score} size="sm" />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <h2>Skill-up roadmap</h2>
          <div className="inline-form">
            <label className="check small">
              <input type="number" min={1} max={80} value={genForm.hours} onChange={(e) => setGenForm({ ...genForm, hours: Number(e.target.value) })} style={{ width: 64 }} /> h/week
            </label>
            <label className="check small">
              <input type="number" min={1} max={104} value={genForm.weeks} onChange={(e) => setGenForm({ ...genForm, weeks: Number(e.target.value) })} style={{ width: 64 }} /> weeks
            </label>
            <label className="check small">
              <input type="checkbox" checked={genForm.include_jobs} onChange={(e) => setGenForm({ ...genForm, include_jobs: e.target.checked })} /> use linked job descriptions
            </label>
            <button className="btn btn-primary" onClick={generate} disabled={gen.running}>
              {gen.running ? `Planning… ${gen.elapsed}s` : items.length ? "Regenerate" : "Generate roadmap"}
            </button>
          </div>
        </div>
        <div className="card-body">
          <ErrorBanner text={gen.error} onDismiss={gen.clearError} />
          {gen.running && <div className="banner banner-info">Claude is comparing your ledger with this role. Open items will be replaced; completed ones are kept.</div>}
          {summary && (
            <div className="banner banner-info" style={{ display: "block" }}>
              <p style={{ margin: 0 }}>{summary.summary}</p>
              {summary.leverage_existing.length > 0 && (
                <p className="small" style={{ margin: "6px 0 0" }}>
                  <strong>Lean on:</strong> {summary.leverage_existing.join("; ")}
                </p>
              )}
            </div>
          )}

          {items.length === 0 && !gen.running ? (
            <EmptyState title="No roadmap yet" body="Generate one to get a prioritised plan that closes the gaps above, each ending in a concrete proof artifact." />
          ) : (
            <div className="stack" style={{ gap: 8 }}>
              {open.map((i) => (
                <RoadmapRow key={i.id} item={i} onStart={() => setStatus(i, "in_progress")} onSkip={() => setStatus(i, "skipped")} onDone={() => setCompleting(i)} onReopen={() => setStatus(i, "todo")} />
              ))}
              {closed.length > 0 && (
                <>
                  <button className="btn btn-ghost btn-sm" style={{ alignSelf: "flex-start" }} onClick={() => setShowClosed(!showClosed)}>
                    {showClosed ? "Hide" : "Show"} {closed.length} completed or skipped
                  </button>
                  {showClosed && closed.map((i) => <RoadmapRow key={i.id} item={i} onReopen={() => setStatus(i, "todo")} />)}
                </>
              )}
            </div>
          )}
        </div>
      </div>

      {editing && (
        <RoleModal
          existing={r}
          onClose={() => setEditing(false)}
          onSaved={() => {
            setEditing(false);
            role.reload();
          }}
        />
      )}
      {completing && (
        <CompleteModal
          item={completing}
          onClose={() => setCompleting(null)}
          onDone={() => {
            setCompleting(null);
            roadmap.reload();
            role.reload();
          }}
        />
      )}
    </>
  );
}

function RoadmapRow({ item, onStart, onSkip, onDone, onReopen }: { item: RoadmapItem; onStart?: () => void; onSkip?: () => void; onDone?: () => void; onReopen?: () => void }) {
  const [openRow, setOpenRow] = useState(false);
  const proof = item.actions.find((a) => a.startsWith("Proof:"));
  const steps = item.actions.filter((a) => !a.startsWith("Proof:"));
  return (
    <div className={`rm-item rm-${item.status}`}>
      <div className="rm-head" onClick={() => setOpenRow(!openRow)}>
        <span className={`rm-prio rm-prio-${item.priority}`} title={`Priority ${item.priority}`}>
          P{item.priority}
        </span>
        <div>
          <div className="rm-title">{item.skill}</div>
          <div className="rm-meta">
            {item.est_weeks ? `~${item.est_weeks} weeks` : ""}
            {item.why ? ` · ${item.why}` : ""}
          </div>
        </div>
        <div className="row" onClick={(e) => e.stopPropagation()}>
          <Badge tone={ROADMAP_STATUS_TONE[item.status]}>{labelize(item.status)}</Badge>
          {item.status === "todo" && onStart && (
            <button className="btn btn-sm" onClick={onStart}>
              Start
            </button>
          )}
          {(item.status === "todo" || item.status === "in_progress") && onDone && (
            <button className="btn btn-sm btn-primary" onClick={onDone}>
              Done
            </button>
          )}
          {(item.status === "todo" || item.status === "in_progress") && onSkip && (
            <button className="btn btn-ghost btn-sm" onClick={onSkip}>
              Skip
            </button>
          )}
          {(item.status === "done" || item.status === "skipped") && onReopen && (
            <button className="btn btn-ghost btn-sm" onClick={onReopen}>
              Reopen
            </button>
          )}
        </div>
      </div>
      {openRow && (
        <div className="rm-body">
          {steps.length > 0 && (
            <>
              <div className="section-title">Steps</div>
              <ol>
                {steps.map((a, i) => (
                  <li key={i}>{a}</li>
                ))}
              </ol>
            </>
          )}
          {item.resources.length > 0 && (
            <>
              <div className="section-title">Resources</div>
              <ul>
                {item.resources.map((res, i) => (
                  <li key={i}>{res}</li>
                ))}
              </ul>
            </>
          )}
          {proof && (
            <>
              <div className="section-title">Proof</div>
              <p>{proof.replace(/^Proof:\s*/, "")}</p>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function CompleteModal({ item, onClose, onDone }: { item: RoadmapItem; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [level, setLevel] = useState<SkillLevel>("intermediate");
  const [proof, setProof] = useState("");
  const [addToLedger, setAddToLedger] = useState(true);
  const [saving, setSaving] = useState(false);
  const submit = async () => {
    setSaving(true);
    try {
      const res = await api.roadmap.setStatus(item.id, { status: "done", level, proof: proof || null, add_to_ledger: addToLedger });
      toast(res.ledger_entry_id ? `Marked done and added "${item.skill}" to your ledger` : "Marked done", "success");
      onDone();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setSaving(false);
    }
  };
  return (
    <Modal
      title={`Complete: ${item.skill}`}
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" onClick={submit} disabled={saving}>
            {saving ? "Saving…" : "Mark done"}
          </button>
        </>
      }
    >
      <p className="muted">Completing an item records the skill in your ledger so future fit scores and roadmaps see it.</p>
      <div className="form-grid">
        <Field label="Add to ledger" span2>
          <label className="check">
            <input type="checkbox" checked={addToLedger} onChange={(e) => setAddToLedger(e.target.checked)} /> Create a skill entry for {item.skill}
          </label>
        </Field>
        {addToLedger && (
          <>
            <Field label="Level">
              <select value={level} onChange={(e) => setLevel(e.target.value as SkillLevel)}>
                {(["beginner", "intermediate", "advanced", "expert"] as SkillLevel[]).map((l) => (
                  <option key={l} value={l}>
                    {l}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Proof link" hint="Repo, certificate, demo">
              <input type="url" value={proof} onChange={(e) => setProof(e.target.value)} placeholder="https://" />
            </Field>
          </>
        )}
      </div>
    </Modal>
  );
}
