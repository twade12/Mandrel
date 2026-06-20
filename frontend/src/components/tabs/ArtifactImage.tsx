import { useEffect, useState } from "react";
import { artifactUrl } from "../../api";
import { useStore } from "../../state";
import { PanZoom } from "../PanZoom";

// Renders an SVG artifact served by the backend. Polls a few times after the
// stage reports ready (the file is generated lazily on first request), then
// shows a clear error state instead of hanging on "loading…".
export function ArtifactImage({ name, ready, hint }: { name: string; ready: boolean; hint: string }) {
  const { activeRunId } = useStore();
  const [status, setStatus] = useState<"idle" | "loading" | "ok" | "error">("idle");
  const [tick, setTick] = useState(0);

  useEffect(() => {
    setStatus(ready ? "loading" : "idle");
  }, [activeRunId, name, ready, tick]);

  if (!activeRunId) return <div className="tab"><div className="placeholder">No active run.</div></div>;
  if (!ready) return <div className="tab"><div className="placeholder">{hint}</div></div>;

  const url = `${artifactUrl(activeRunId, name)}?v=${tick}`;
  return (
    <div className="tab" style={{ display: "flex", flexDirection: "column" }}>
      <h2 style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span>{name}</span>
        <button className="btn btn-ghost" style={{ padding: "2px 8px" }} onClick={() => setTick((t) => t + 1)}>
          ⟳ refresh
        </button>
      </h2>
      <div className="svg-frame" style={{ flex: 1 }}>
        {status === "loading" && <div className="placeholder">rendering {name}…</div>}
        {status === "error" && (
          <div className="placeholder">
            {name} not available yet.<br />
            <span className="muted">The stage may still be running, or this artifact failed to render. Try ⟳ refresh.</span>
          </div>
        )}
        {status === "ok" ? (
          <PanZoom>
            <img src={url} alt={name} onError={() => setStatus("error")} style={{ width: "100%", display: "block" }} />
          </PanZoom>
        ) : (
          <img
            src={url}
            alt={name}
            onLoad={() => setStatus("ok")}
            onError={() => setStatus("error")}
            style={{ display: "none" }}
          />
        )}
      </div>
    </div>
  );
}
