import { STAGES, useStore } from "../state";

export function StageRail() {
  const { stageStatus, activity, selectedStage, selectStage } = useStore();
  return (
    <div className="stage-rail">
      {STAGES.map((s, i) => {
        const st = stageStatus[s.name] ?? "idle";
        const sel = selectedStage === s.name;
        return (
          <div
            key={s.name}
            className={`stage-pill ${st}` + (sel ? " selected" : "")}
            title={`${activity.message ?? st} — click for logs`}
            style={{ cursor: "pointer" }}
            onClick={() => selectStage(sel ? null : s.name)}
          >
            {st === "running" ? <span className="spinner" /> :
             st === "passed" ? <span>✓</span> :
             st === "failed" ? <span>✕</span> :
             st === "waiting" ? <span>⚠</span> : <span className="dot" />}
            <span>S{i + 1} {s.label}</span>
          </div>
        );
      })}
      {activity.message && (
        <span className="muted" style={{ marginLeft: 8, fontSize: 11, whiteSpace: "nowrap" }}>
          {activity.message}
        </span>
      )}
    </div>
  );
}
