import { useEffect, useState } from "react";
import { artifactUrl } from "../../api";
import { useStore } from "../../state";

// Renders an SVG artifact served by the backend, polling until it appears
// (the artifact is generated lazily once the relevant stage has run).
export function ArtifactImage({ name, ready, hint }: { name: string; ready: boolean; hint: string }) {
  const { activeRunId } = useStore();
  const [ok, setOk] = useState(false);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    setOk(false);
  }, [activeRunId, name, ready]);

  if (!activeRunId) return <div className="tab"><div className="placeholder">No active run.</div></div>;
  if (!ready) return <div className="tab"><div className="placeholder">{hint}</div></div>;

  const url = `${artifactUrl(activeRunId, name)}?v=${tick}`;
  return (
    <div className="tab" style={{ display: "flex", flexDirection: "column" }}>
      <h2 style={{ display: "flex", justifyContent: "space-between" }}>
        {name}
        <button className="btn btn-ghost" style={{ padding: "2px 8px" }} onClick={() => setTick((t) => t + 1)}>
          ⟳ refresh
        </button>
      </h2>
      <div className="svg-frame" style={{ flex: 1 }}>
        {!ok && <div className="placeholder">loading {name}…</div>}
        <img src={url} alt={name} onLoad={() => setOk(true)} onError={() => setOk(false)}
             style={{ display: ok ? "block" : "none" }} />
      </div>
    </div>
  );
}
