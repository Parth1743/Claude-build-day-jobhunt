import { useEffect, useState } from "react";
import { api } from "../api";
import { useLoad, useTask } from "../hooks";
import { useToast } from "../components/Toast";
import { Badge, ErrorBanner, Field, Spinner } from "../components/ui";
import type { ProviderInfo, SettingsInfo, TestResult } from "../types";

export default function Settings() {
  const toast = useToast();
  const info = useLoad(() => api.settings.get());
  const test = useTask<TestResult>();
  const [selected, setSelected] = useState<string>("");
  const [model, setModel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [key, setKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<TestResult | null>(null);

  useEffect(() => {
    if (info.data && !selected) setSelected(info.data.provider);
  }, [info.data, selected]);

  useEffect(() => {
    const p = info.data?.providers.find((x) => x.id === selected);
    if (p) {
      setModel(p.model);
      setBaseUrl(p.base_url);
      setKey("");
      setResult(null);
    }
  }, [selected, info.data]);

  if (info.error) return <div className="banner banner-error">{info.error}</div>;
  if (!info.data) return <Spinner label="Loading" />;
  const data: SettingsInfo = info.data;
  const p = data.providers.find((x) => x.id === selected) || data.providers[0];
  const isActive = data.provider === p.id;

  const save = async (activate: boolean) => {
    setSaving(true);
    try {
      const updated = await api.settings.update({
        provider: activate ? p.id : undefined,
        model_provider: p.id,
        model,
        base_url: baseUrl,
        api_keys: key ? { [p.id]: key } : {},
      });
      info.setData(updated);
      setKey("");
      toast(activate ? `${p.label} is now the active provider` : "Settings saved", "success");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setSaving(false);
    }
  };

  const clearKey = async () => {
    if (!confirm(`Remove the saved ${p.label} key?`)) return;
    const updated = await api.settings.update({ api_keys: { [p.id]: "" } });
    info.setData(updated);
    toast("Key removed", "success");
  };

  const runTest = async () => {
    setResult(null);
    if (key || model !== p.model || baseUrl !== p.base_url) await save(false);
    const r = await test.run(() => api.settings.test(p.id));
    if (r) {
      setResult(r);
      info.reload();
    }
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Settings</h1>
          <p>Choose which model provider powers resume import, fit analysis and roadmaps.</p>
        </div>
        <div className="page-actions">
          <Badge tone={data.ai_configured ? "good" : "warning"}>
            {data.ai_configured ? `Active: ${data.providers.find((x) => x.id === data.provider)?.label} · ${data.model}` : "No provider configured"}
          </Badge>
        </div>
      </div>

      <div className="grid" style={{ gridTemplateColumns: "280px 1fr", alignItems: "start" }}>
        <div className="card">
          <div className="card-head">
            <h2>Providers</h2>
          </div>
          <div className="provider-list">
            {data.providers.map((x) => (
              <ProviderRow key={x.id} p={x} active={x.id === data.provider} selected={x.id === p.id} onSelect={() => setSelected(x.id)} />
            ))}
          </div>
        </div>

        <div className="stack">
          <div className="card">
            <div className="card-head">
              <h2>{p.label}</h2>
              <div className="row">
                {isActive ? <Badge tone="accent">Active</Badge> : null}
                <a className="small" href={p.docs} target="_blank" rel="noreferrer">
                  Get an API key ↗
                </a>
              </div>
            </div>
            <div className="card-body">
              <div className="form-grid">
                <Field label="API key" hint={keyHint(p)} span2>
                  <div className="inline-form">
                    <input className="grow" type="password" value={key} onChange={(e) => setKey(e.target.value)} placeholder={p.key_status ? "Enter a new key to replace the current one" : "Paste your key"} autoComplete="off" />
                    {p.key_status === "saved" && (
                      <button className="btn btn-ghost btn-sm" onClick={clearKey} type="button">
                        Remove saved key
                      </button>
                    )}
                  </div>
                </Field>
                <Field label="Model" hint={`Default: ${p.default_model}`}>
                  <input type="text" value={model} onChange={(e) => setModel(e.target.value)} placeholder={p.default_model} list={`models-${p.id}`} />
                  <datalist id={`models-${p.id}`}>
                    {p.models_hint.map((m) => (
                      <option key={m} value={m} />
                    ))}
                  </datalist>
                </Field>
                <Field label="Base URL" hint={p.default_base_url ? "Leave blank for the default" : "Only for proxies or gateways"}>
                  <input type="url" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder={p.default_base_url || "https://api.anthropic.com"} />
                </Field>
              </div>
              <div className="row mt-2">
                <button className="btn btn-primary" onClick={() => save(true)} disabled={saving}>
                  {isActive ? "Save" : "Save and make active"}
                </button>
                {!isActive && (
                  <button className="btn" onClick={() => save(false)} disabled={saving}>
                    Save only
                  </button>
                )}
                <button className="btn" onClick={runTest} disabled={test.running || (!p.key_status && !key)}>
                  {test.running ? `Testing… ${test.elapsed}s` : "Test connection"}
                </button>
              </div>
              <div className="mt-2">
                <ErrorBanner text={test.error} onDismiss={test.clearError} />
                {result && (
                  <div className="banner banner-info" style={{ display: "block" }}>
                    <strong>Connected.</strong> {result.model} answered in {result.latency_ms} ms with "{result.reply}".
                  </div>
                )}
              </div>
            </div>
          </div>

          <div className="card">
            <div className="card-body">
              <div className="section-title">How keys are stored</div>
              <p className="muted small" style={{ margin: 0 }}>
                Keys you enter here are saved in the local SQLite database in plain text and never leave this machine except to call the provider you chose. Keys set through environment variables or a <code>.env</code> file are used automatically when nothing is saved here. Testing the connection makes one tiny request.
              </p>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

function keyHint(p: ProviderInfo) {
  if (p.key_status === "saved") return `Saved key ending ${p.key_hint}`;
  if (p.key_status === "env") return `Using ${p.env_keys.join(" or ")} from the environment (ending ${p.key_hint})`;
  return `Or set ${p.env_keys.join(" or ")} in .env`;
}

function ProviderRow({ p, active, selected, onSelect }: { p: ProviderInfo; active: boolean; selected: boolean; onSelect: () => void }) {
  return (
    <button className={`provider-row ${selected ? "selected" : ""}`} onClick={onSelect}>
      <span className="provider-name">
        {p.label}
        {active && <Badge tone="accent">active</Badge>}
      </span>
      <span className="small muted">
        {p.model || p.default_model} · {p.key_status ? (p.key_status === "saved" ? "key saved" : "key from env") : "no key"}
      </span>
    </button>
  );
}
