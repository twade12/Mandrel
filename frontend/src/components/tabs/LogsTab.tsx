import { STAGES, useStore } from "../../state";
import { PipelineEvent } from "../../api";

const STAGE_LABEL: Record<string, string> = Object.fromEntries(STAGES.map((s) => [s.name, s.label]));

// Per-stage activity log: what the AI and the backend actually did. Click a
// stage in the rail to filter; otherwise shows the whole run.
export function LogsTab() {
  const { events, selectedStage, selectStage } = useStore();
  const shown = selectedStage ? events.filter((e) => e.stage === selectedStage) : events;

  return (
    <div className="tab" style={{ display: "flex", flexDirection: "column" }}>
      <h2 style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span>Activity Log{selectedStage ? ` — ${STAGE_LABEL[selectedStage] ?? selectedStage}` : " — all stages"}</span>
        {selectedStage && (
          <button className="btn btn-ghost" style={{ padding: "2px 8px" }} onClick={() => selectStage(null)}>
            show all
          </button>
        )}
      </h2>
      {shown.length === 0 ? (
        <div className="placeholder">No activity yet. Run a pipeline, then click a stage in the rail to inspect it.</div>
      ) : (
        <div className="log-console" style={{ flex: 1, padding: 10 }}>
          {shown.map((e, i) => <LogLine key={i} ev={e} />)}
        </div>
      )}
    </div>
  );
}

function LogLine({ ev }: { ev: PipelineEvent }) {
  const stage = ev.stage ? `${STAGE_LABEL[ev.stage] ?? ev.stage}` : "";
  let cls = "muted";
  let text = ev.type;
  switch (ev.type) {
    case "stage_started": cls = "accent"; text = `▶ ${ev.label ?? stage} started`; break;
    case "stage_progress": cls = "muted"; text = `  ⋯ ${ev.message ?? ""}`; break;
    case "stage_completed":
      cls = ev.passed ? "text-success" : "text-error";
      text = `${ev.passed ? "✓" : "✗"} ${ev.label ?? stage} ${ev.passed ? "passed" : "FAILED"} (score ${(ev.score ?? 0).toFixed(2)})`;
      break;
    case "stage_failed": cls = "text-error"; text = `✗ ${ev.label ?? stage} error: ${ev.error}`; break;
    case "checkpoint_needed": cls = "text-warning"; text = `⚠ checkpoint: ${ev.label ?? stage}`; break;
    case "checkpoint_resolved": cls = "muted"; text = `→ checkpoint ${stage}: ${ev.decision}`; break;
    case "run_completed": cls = "text-success"; text = "✓ run completed"; break;
    case "run_failed": cls = "text-error"; text = `✗ run failed: ${ev.error}`; break;
  }
  return (
    <div style={{ fontFamily: "var(--font)", fontSize: 11.5, lineHeight: 1.5 }}>
      <span className={cls}>{text}</span>
      {ev.detail && (
        <pre style={{
          margin: "2px 0 6px 14px", padding: 8, whiteSpace: "pre-wrap",
          background: "var(--surface)", border: "1px solid var(--border)",
          borderRadius: 4, fontSize: 10.5, maxHeight: 220, overflow: "auto",
        }}>{ev.detail}</pre>
      )}
      {ev.violations && ev.violations.length > 0 && ev.type === "stage_completed" && (
        <div style={{ margin: "2px 0 6px 14px" }}>
          {ev.violations.slice(0, 12).map((v, k) => (
            <div key={k} style={{ fontSize: 10.5 }}>
              <span className={v.severity === "error" ? "text-error" : "text-warning"}>
                [{v.severity}] {v.code}
              </span>{" "}
              <span className="muted">{v.message}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
