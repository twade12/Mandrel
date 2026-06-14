import { Suspense, useState } from "react";
import { Canvas } from "@react-three/fiber";
import { OrbitControls, Stage, useGLTF } from "@react-three/drei";
import { artifactUrl } from "../../api";
import { useStore } from "../../state";

function Model({ url }: { url: string }) {
  const { scene } = useGLTF(url);
  return <primitive object={scene} />;
}

export function ModelTab() {
  const { activeRunId, design, stageStatus } = useStore();
  const [which, setWhich] = useState<"enclosure.glb" | "board.glb">("enclosure.glb");
  const enclosureReady = !!design?.enclosure?.step_path || stageStatus["s5_enclosure"] === "passed";
  const boardReady = !!design?.pcb?.board_step_path || stageStatus["s4_layout"] === "passed";
  const ready = which === "enclosure.glb" ? enclosureReady : boardReady;

  if (!activeRunId) return <div className="tab"><div className="placeholder">No active run.</div></div>;

  const url = ready ? artifactUrl(activeRunId, which) : null;
  return (
    <div className="tab" style={{ display: "flex", flexDirection: "column" }}>
      <h2 style={{ display: "flex", justifyContent: "space-between" }}>
        3D Model
        <span>
          <button className={"btn btn-ghost"} style={{ padding: "2px 8px", marginRight: 6, color: which === "enclosure.glb" ? "var(--cyan)" : undefined }}
            onClick={() => setWhich("enclosure.glb")}>Enclosure</button>
          <button className={"btn btn-ghost"} style={{ padding: "2px 8px", color: which === "board.glb" ? "var(--cyan)" : undefined }}
            onClick={() => setWhich("board.glb")}>Board</button>
        </span>
      </h2>
      <div className="canvas-wrap" style={{ flex: 1 }}>
        {!url ? (
          <div className="placeholder">{which === "enclosure.glb" ? "Enclosure appears after S5." : "Board model appears after S4."}</div>
        ) : (
          <Canvas key={url} camera={{ position: [0, 60, 90], fov: 45 }}>
            <Suspense fallback={null}>
              <Stage environment="city" intensity={0.5}>
                <Model url={url} />
              </Stage>
            </Suspense>
            <OrbitControls makeDefault />
          </Canvas>
        )}
      </div>
    </div>
  );
}
