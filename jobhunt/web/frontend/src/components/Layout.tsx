import { NavLink, Outlet } from "react-router-dom";
import { api } from "../api";
import { useLoad } from "../hooks";

const NAV = [
  { to: "/", label: "Dashboard", icon: "◫" },
  { to: "/discover", label: "Discover", icon: "◈" },
  { to: "/ledger", label: "Ledger", icon: "☰" },
  { to: "/roles", label: "Target roles", icon: "◎" },
  { to: "/jobs", label: "Applications", icon: "▤" },
  { to: "/settings", label: "Settings", icon: "⚙" },
];

export function Layout() {
  const { data: config } = useLoad(() => api.config());
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            jh
          </span>
          <span className="brand-name">jobhunt</span>
        </div>
        <nav className="nav">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.to === "/"} className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
              <span className="nav-icon" aria-hidden="true">
                {n.icon}
              </span>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          {config && (
            <NavLink
              to="/settings"
              className={`ai-pill ${config.ai_configured ? "on" : "off"}`}
              title={config.ai_configured ? `${config.provider_label} · ${config.model}` : "Open Settings to add an API key"}
            >
              <span className="dot" aria-hidden="true" />
              {config.ai_configured ? `${config.provider_label} · ${config.model}` : "No AI provider configured"}
            </NavLink>
          )}
          <a className="foot-link" href="/api/docs" target="_blank" rel="noreferrer">
            API docs
          </a>
        </div>
      </aside>
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}
