import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, splitCsv } from "../api";
import { useLoad, useTask } from "../hooks";
import { Modal } from "../components/Modal";
import { useToast } from "../components/Toast";
import { Badge, EmptyState, ErrorBanner, Field, Progress, Spinner } from "../components/ui";
import type { RoleSuggestion } from "../types";

export default function Roles() {
  const nav = useNavigate();
  const roles = useLoad(() => api.roles.list());
  const [adding, setAdding] = useState(false);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Target roles</h1>
          <p>What you are aiming for, what each role requires, and how much of it you already have.</p>
        </div>
        <div className="page-actions">
          <button className="btn btn-primary" onClick={() => setAdding(true)}>
            Add role
          </button>
        </div>
      </div>

      <ErrorBanner text={roles.error} />
      {roles.loading && !roles.data ? (
        <Spinner label="Loading" />
      ) : !roles.data?.length ? (
        <div className="card">
          <EmptyState
            title="No target roles yet"
            body="Add the roles you are applying for. Claude can fill in the typical skill requirements so you see your gaps immediately."
            action={
              <button className="btn btn-primary" onClick={() => setAdding(true)}>
                Add your first role
              </button>
            }
          />
        </div>
      ) : (
        <div className="grid grid-3">
          {roles.data.map((r) => {
            const covered = r.coverage.required.filter((c) => c.have).length;
            return (
              <div key={r.id} className="card role-card" onClick={() => nav(`/roles/${r.id}`)} role="link" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && nav(`/roles/${r.id}`)}>
                <div className="row row-between">
                  <h3>{r.title}</h3>
                  <Badge tone={r.priority === 1 ? "accent" : "neutral"}>P{r.priority}</Badge>
                </div>
                {r.description && <div className="desc-clamp">{r.description}</div>}
                <div>
                  <div className="small muted mb-1">Required skills covered</div>
                  <Progress value={covered} max={r.required_skills.length} label={`${r.title} coverage`} />
                </div>
                <div className="row small muted">
                  <span>{r.job_count} linked jobs</span>
                  <span>·</span>
                  <span>{r.nice_to_have.length} nice-to-haves</span>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {adding && (
        <RoleModal
          onClose={() => setAdding(false)}
          onSaved={(id) => {
            setAdding(false);
            nav(`/roles/${id}`);
          }}
        />
      )}
    </>
  );
}

export function RoleModal({
  onClose,
  onSaved,
  existing,
}: {
  onClose: () => void;
  onSaved: (id: number) => void;
  existing?: { id: number; title: string; description: string | null; required_skills: string[]; nice_to_have: string[]; priority: number };
}) {
  const toast = useToast();
  const suggest = useTask<RoleSuggestion>();
  const [form, setForm] = useState({
    title: existing?.title ?? "",
    description: existing?.description ?? "",
    required: existing?.required_skills.join(", ") ?? "",
    nice: existing?.nice_to_have.join(", ") ?? "",
    priority: existing?.priority ?? 1,
  });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const runSuggest = async () => {
    if (!form.title.trim()) return setErr("Enter a role title first.");
    setErr(null);
    const s = await suggest.run(() => api.roles.suggest(form.title.trim(), form.description || undefined));
    if (s) {
      setForm((f) => ({
        ...f,
        description: f.description || s.description,
        required: f.required || s.required_skills.join(", "),
        nice: f.nice || s.nice_to_have.join(", "),
      }));
    }
  };

  const submit = async () => {
    if (!form.title.trim()) return setErr("Title is required.");
    setSaving(true);
    setErr(null);
    try {
      if (existing) {
        const r = await api.roles.update(existing.id, {
          description: form.description,
          required_skills: splitCsv(form.required),
          nice_to_have: splitCsv(form.nice),
          priority: Number(form.priority),
        });
        toast("Role updated", "success");
        onSaved(r.id);
      } else {
        const r = await api.roles.create({
          title: form.title.trim(),
          description: form.description || null,
          required_skills: splitCsv(form.required),
          nice_to_have: splitCsv(form.nice),
          priority: Number(form.priority),
        });
        toast("Role added", "success");
        onSaved(r.id);
      }
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={existing ? "Edit role" : "New target role"}
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
      <ErrorBanner text={err || suggest.error} onDismiss={() => { setErr(null); suggest.clearError(); }} />
      <div className="form-grid">
        <Field label="Role title" span2>
          <div className="inline-form">
            <input className="grow" type="text" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="e.g. Platform Engineer" disabled={!!existing} autoFocus />
            <button className="btn" onClick={runSuggest} disabled={suggest.running} type="button">
              {suggest.running ? `Thinking… ${suggest.elapsed}s` : "Suggest skills with Claude"}
            </button>
          </div>
        </Field>
        <Field label="Priority" hint="1 is your top target">
          <select value={form.priority} onChange={(e) => setForm({ ...form, priority: Number(e.target.value) })}>
            <option value={1}>1</option>
            <option value={2}>2</option>
            <option value={3}>3</option>
          </select>
        </Field>
        <Field label="Description" span2>
          <textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder="Optional. What this role does, or context about your situation." />
        </Field>
        <Field label="Required skills" hint="Comma separated" span2>
          <textarea value={form.required} onChange={(e) => setForm({ ...form, required: e.target.value })} placeholder="Kubernetes, Terraform, Go, Observability" style={{ minHeight: 60 }} />
        </Field>
        <Field label="Nice to have" hint="Comma separated" span2>
          <textarea value={form.nice} onChange={(e) => setForm({ ...form, nice: e.target.value })} placeholder="Helm, ArgoCD" style={{ minHeight: 48 }} />
        </Field>
      </div>
    </Modal>
  );
}
