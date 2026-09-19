import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useLoad } from "../hooks";
import { EmptyState, FitScore, Progress, StatusBadge, fmtDate } from "../components/ui";
import type { JobStatus } from "../types";

const OPEN_STAGES: JobStatus[] = ["saved", "applied", "screening", "interview", "offer"];
const CLOSED_STAGES: JobStatus[] = ["rejected", "withdrawn"];
const STAGE_COLOR: Record<string, string> = {
  saved: "var(--seq-250)",
  applied: "var(--seq-350)",
  screening: "var(--seq-450)",
  interview: "var(--seq-550)",
  offer: "var(--seq-650)",
};

export default function Dashboard() {
  const nav = useNavigate();
  const { data, error, loading } = useLoad(() => api.dashboard());

  if (loading && !data) return <div className="skeleton" style={{ height: 200 }} />;
  if (error) return <div className="banner banner-error">{error}</div>;
  if (!data) return null;

  const ledgerTotal = Object.values(data.ledger_counts).reduce((a, b) => a + b, 0);
  const openJobs = OPEN_STAGES.reduce((n, s) => n + (data.funnel[s] || 0), 0);
  const allJobs = Object.values(data.funnel).reduce((a, b) => a + b, 0);
  const maxStage = Math.max(1, ...Object.values(data.funnel));
  const openItems = data.roles.reduce((n, r) => n + r.open_items, 0);
  const isFresh = ledgerTotal === 0 && allJobs === 0 && data.roles.length === 0;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Dashboard</h1>
          <p>Where your search stands today.</p>
        </div>
      </div>

      {isFresh && (
        <div className="card mb-2">
          <EmptyState
            title="Let's get set up"
            body="Three steps: seed your ledger from a resume, add a target role, then discover openings that match your skills."
            action={
              <div className="row" style={{ justifyContent: "center" }}>
                <Link className="btn btn-primary" to="/ledger?import=1">
                  Import resume
                </Link>
                <Link className="btn" to="/roles">
                  Add a target role
                </Link>
                <Link className="btn" to="/discover">
                  Find openings
                </Link>
              </div>
            }
          />
        </div>
      )}

      <div className="grid grid-4 mb-2">
        <div className="card stat">
          <div className="stat-label">Ledger entries</div>
          <div className="stat-value">{ledgerTotal}</div>
          <div className="stat-sub">{data.skill_count} distinct skills</div>
        </div>
        <div className="card stat">
          <div className="stat-label">Open applications</div>
          <div className="stat-value">{openJobs}</div>
          <div className="stat-sub">{allJobs} saved in total</div>
        </div>
        <div className="card stat">
          <div className="stat-label">Interviews and offers</div>
          <div className="stat-value">{(data.funnel.interview || 0) + (data.funnel.offer || 0)}</div>
          <div className="stat-sub">{data.funnel.offer || 0} offers</div>
        </div>
        <div className="card stat">
          <div className="stat-label">Roadmap items open</div>
          <div className="stat-value">{openItems}</div>
          <div className="stat-sub">across {data.roles.length} target roles</div>
        </div>
      </div>

      <div className="grid grid-2 mb-2">
        <div className="card">
          <div className="card-head">
            <h2>Pipeline</h2>
            <Link to="/jobs" className="small">
              All jobs
            </Link>
          </div>
          <div className="card-body">
            <div className="funnel">
              {OPEN_STAGES.map((s) => (
                <FunnelRow key={s} stage={s} n={data.funnel[s] || 0} max={maxStage} />
              ))}
              {CLOSED_STAGES.map((s) => (
                <FunnelRow key={s} stage={s} n={data.funnel[s] || 0} max={maxStage} closed />
              ))}
            </div>
          </div>
        </div>

        <div className="card">
          <div className="card-head">
            <h2>Role readiness</h2>
            <Link to="/roles" className="small">
              All roles
            </Link>
          </div>
          <div className="card-body tight">
            {data.roles.length === 0 ? (
              <EmptyState title="No target roles" body="Add a role to see how your skills cover its requirements." />
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th>Role</th>
                    <th>Required skills covered</th>
                    <th className="num">Roadmap</th>
                  </tr>
                </thead>
                <tbody>
                  {data.roles.map((r) => (
                    <tr key={r.id} className="clickable" onClick={() => nav(`/roles/${r.id}`)}>
                      <td>
                        <strong>{r.title}</strong>
                      </td>
                      <td style={{ minWidth: 180 }}>
                        <Progress value={r.covered} max={r.required} label={`${r.title} coverage`} />
                      </td>
                      <td className="num nowrap">
                        {r.open_items} open · {r.done_items} done
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>

      <div className="grid grid-2">
        <div className="card">
          <div className="card-head">
            <h2>Recent jobs</h2>
          </div>
          <div className="card-body tight">
            {data.recent_jobs.length === 0 ? (
              <EmptyState title="No jobs yet" />
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th>Job</th>
                    <th>Status</th>
                    <th>Fit</th>
                  </tr>
                </thead>
                <tbody>
                  {data.recent_jobs.map((j) => (
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

        <div className="card">
          <div className="card-head">
            <h2>Ledger activity</h2>
            <Link to="/ledger" className="small">
              Open ledger
            </Link>
          </div>
          <div className="card-body">
            {data.recent_changes.length === 0 ? (
              <EmptyState title="No changes yet" />
            ) : (
              <ul className="timeline">
                {data.recent_changes.map((c, i) => (
                  <li key={i}>
                    <time>{fmtDate(c.at)}</time>
                    <span>
                      <span className="kind-tag">{c.action}</span> {c.title}
                      {c.source && <span className="muted"> · {c.source}</span>}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
    </>
  );
}

function FunnelRow({ stage, n, max, closed }: { stage: string; n: number; max: number; closed?: boolean }) {
  const pct = Math.max(n > 0 ? 2 : 0, Math.round((n / max) * 100));
  return (
    <>
      <span className="funnel-label">{stage[0].toUpperCase() + stage.slice(1)}</span>
      <div className={`funnel-track ${closed ? "funnel-closed" : ""}`} title={`${n} ${stage}`}>
        <div className="funnel-bar" style={{ width: `${pct}%`, background: closed ? undefined : STAGE_COLOR[stage] }} />
      </div>
      <span className="funnel-count">{n}</span>
    </>
  );
}
