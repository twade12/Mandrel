import { useState } from "react";
import { useStore } from "../state";

const FORM_FACTORS = ["feather", "hat", "mikrobus", "arduino_shield", "din_rail", "custom"];

export function Sidebar() {
  const { projects, activeRunId, startRun, selectProject } = useStore();
  const [brief, setBrief] = useState("");
  const [formFactor, setFormFactor] = useState("feather");
  const [model, setModel] = useState("");
  const [busy, setBusy] = useState(false);

  async function run() {
    if (!brief.trim()) return;
    setBusy(true);
    try {
      await startRun({
        brief,
        form_factor: formFactor,
        auto_approve: true,
        llm_model: model.trim() || null,
      });
      setBrief("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="sidebar">
      <div className="brand">
        <svg width="24" height="24" viewBox="0 0 32 32" fill="none">
          <rect width="32" height="32" rx="6" fill="#0C1521" />
          <path d="M6 24 L6 8 L16 18 L26 8 L26 24" stroke="#22D3EE" strokeWidth="2.5"
            strokeLinecap="round" strokeLinejoin="round" fill="none" />
        </svg>
        <h1>MANDREL</h1>
      </div>

      <div className="new-run">
        <div className="section-label" style={{ padding: 0 }}>New Design</div>
        <textarea
          rows={3}
          placeholder="e.g. A Feather board measuring temperature and humidity over USB-C"
          value={brief}
          onChange={(e) => setBrief(e.target.value)}
        />
        <select value={formFactor} onChange={(e) => setFormFactor(e.target.value)}>
          {FORM_FACTORS.map((f) => <option key={f} value={f}>{f}</option>)}
        </select>
        <input placeholder="LLM model (blank = default)" value={model} onChange={(e) => setModel(e.target.value)} />
        <button className="btn" disabled={busy || !brief.trim()} onClick={run}>
          {busy ? "Starting…" : "▶ Run Pipeline"}
        </button>
      </div>

      <div className="section-label">Projects</div>
      <div className="project-list">
        {projects.length === 0 && <div className="placeholder">No runs yet</div>}
        {projects.map((p) => (
          <div
            key={p.runId}
            className={"project-item" + (p.runId === activeRunId ? " active" : "")}
            onClick={() => selectProject(p.runId)}
          >
            <span className="title">{p.title}</span>
            <span className="meta">
              <StatusDot status={p.status} /> {p.status} · {new Date(p.createdAt).toLocaleTimeString()}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function StatusDot({ status }: { status: string }) {
  const color =
    status === "completed" ? "var(--success)" :
    status === "failed" ? "var(--error)" :
    status === "waiting_checkpoint" ? "var(--warning)" : "var(--cyan)";
  return <span style={{ color }}>●</span>;
}
