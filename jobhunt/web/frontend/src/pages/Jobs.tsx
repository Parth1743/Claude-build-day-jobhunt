import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useLoad } from "../hooks";
import { Modal } from "../components/Modal";
import { useToast } from "../components/Toast";
import { EmptyState, ErrorBanner, Field, FitScore, Spinner, StatusBadge, fmtDate, labelize } from "../components/ui";
import type { JobStatus } from "../types";

const STATUSES: JobStatus[] = ["saved", "applied", "screening", "interview", "offer", "rejected", "withdrawn"];

export default function Jobs() {
  const nav = useNavigate();
  const toast = useToast();
  const [filter, setFilter] = useState<string>("");
  const [hideClosed, setHideClosed] = useState(true);
  const [adding, setAdding] = useState(false);
  const jobs = useLoad(() => api.jobs.list(filter || undefined, !hideClosed), [filter, hideClosed]);
  const funnel = useLoad(() => api.jobs.funnel(), [jobs.data]);
  const roles = useLoad(() => api.roles.list());

  const quickStatus = async (id: number, status: JobStatus) => {
    try {
      await api.jobs.setStatus(id, status);
      toast(`Moved to ${labelize(status)}`, "success");
      jobs.reload();
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Jobs</h1>
          <p>Postings you are tracking, scored against your ledger.</p>
        </div>
        <div className="page-actions">
          <button className="btn btn-primary" onClick={() => setAdding(true)}>
            Save a job
          </button>
        </div>
      </div>

      <div className="tabs">
        <button className={`tab ${filter === "" ? "active" : ""}`} onClick={() => setFilter("")}>
          All
        </button>
        {STATUSES.map((s) => (
          <button key={s} className={`tab ${filter === s ? "active" : ""}`} onClick={() => setFilter(s)}>
            {labelize(s)}
            <span className="count">{funnel.data?.[s] ?? ""}</span>
          </button>
        ))}
        <label className="check small right" style={{ alignSelf: "center" }}>
          <input type="checkbox" checked={hideClosed} onChange={(e) => setHideClosed(e.target.checked)} /> Hide rejected and withdrawn
        </label>
      </div>

      <div className="card">
        <div className="card-body tight">
          <ErrorBanner text={jobs.error} />
          {jobs.loading && !jobs.data ? (
            <div className="card-body">
              <Spinner label="Loading" />
            </div>
          ) : !jobs.data?.length ? (
            <EmptyState
              title={filter ? `Nothing in ${labelize(filter)}` : "No jobs saved yet"}
              body="Paste a job description and Claude will score the fit, write tailored bullets and draft a cover letter from your ledger."
              action={
                <button className="btn btn-primary" onClick={() => setAdding(true)}>
                  Save your first job
                </button>
              }
            />
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Job</th>
                  <th>Role</th>
                  <th>Status</th>
                  <th>Fit</th>
                  <th>Updated</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {jobs.data.map((j) => (
                  <tr key={j.id} className="clickable" onClick={() => nav(`/jobs/${j.id}`)}>
                    <td className="title-cell">
                      <strong>{j.title}</strong>
                      <span className="sub">
                        {j.company}
                        {j.location ? ` · ${j.location}` : ""}
                      </span>
                    </td>
                    <td className="muted">{j.role_title || "—"}</td>
                    <td>
                      <StatusBadge status={j.status} />
                    </td>
                    <td>{j.fit_score === null ? <span className="muted small">{j.jd_text ? "not analyzed" : "no description"}</span> : <FitScore score={j.fit_score} size="sm" />}</td>
                    <td className="muted nowrap">{fmtDate(j.updated_at)}</td>
                    <td onClick={(e) => e.stopPropagation()} style={{ textAlign: "right" }}>
                      <select value={j.status} onChange={(e) => quickStatus(j.id, e.target.value as JobStatus)} aria-label="Change status" style={{ width: "auto", padding: "4px 8px", fontSize: 12 }}>
                        {STATUSES.map((s) => (
                          <option key={s} value={s}>
                            {labelize(s)}
                          </option>
                        ))}
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {adding && (
        <AddJobModal
          roles={roles.data || []}
          onClose={() => setAdding(false)}
          onSaved={(id, analyze) => {
            setAdding(false);
            nav(`/jobs/${id}${analyze ? "?analyze=1" : ""}`);
          }}
        />
      )}
    </>
  );
}

function AddJobModal({ roles, onClose, onSaved }: { roles: { id: number; title: string }[]; onClose: () => void; onSaved: (id: number, analyze: boolean) => void }) {
  const [form, setForm] = useState({ company: "", title: "", url: "", location: "", role_id: "", jd_text: "", analyze: true });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => setForm({ ...form, [k]: e.target.value });

  const submit = async () => {
    if (!form.company.trim() || !form.title.trim()) return setErr("Company and title are required.");
    setSaving(true);
    setErr(null);
    try {
      const j = await api.jobs.create({
        company: form.company.trim(),
        title: form.title.trim(),
        url: form.url || null,
        location: form.location || null,
        role_id: form.role_id ? Number(form.role_id) : null,
        jd_text: form.jd_text.trim() || null,
      });
      onSaved(j.id, form.analyze && !!form.jd_text.trim());
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title="Save a job"
      onClose={onClose}
      wide
      footer={
        <>
          <button className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" onClick={submit} disabled={saving}>
            {saving ? "Saving…" : form.analyze && form.jd_text.trim() ? "Save and analyze" : "Save"}
          </button>
        </>
      }
    >
      <ErrorBanner text={err} />
      <div className="form-grid">
        <Field label="Company">
          <input type="text" value={form.company} onChange={set("company")} autoFocus />
        </Field>
        <Field label="Job title">
          <input type="text" value={form.title} onChange={set("title")} />
        </Field>
        <Field label="Posting URL">
          <input type="url" value={form.url} onChange={set("url")} placeholder="https://" />
        </Field>
        <Field label="Location">
          <input type="text" value={form.location} onChange={set("location")} placeholder="Remote, Bengaluru, …" />
        </Field>
        <Field label="Target role" hint="Links this posting to a role so its description feeds that roadmap" span2>
          <select value={form.role_id} onChange={set("role_id")}>
            <option value="">None</option>
            {roles.map((r) => (
              <option key={r.id} value={r.id}>
                {r.title}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Job description" hint="Paste the full posting. You can add it later too." span2>
          <textarea className="jd" value={form.jd_text} onChange={set("jd_text")} />
        </Field>
        <label className="check span-2">
          <input type="checkbox" checked={form.analyze} onChange={(e) => setForm({ ...form, analyze: e.target.checked })} /> Run the fit analysis right after saving
        </label>
      </div>
    </Modal>
  );
}
