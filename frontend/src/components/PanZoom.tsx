import { useRef, useState, WheelEvent, PointerEvent, useCallback } from "react";

// Lightweight pan/zoom container (no deps): wheel to zoom toward the cursor,
// drag to pan, double-click to reset. Used by the PCB and Schematic tabs.
export function PanZoom({ children }: { children: React.ReactNode }) {
  const [t, setT] = useState({ x: 0, y: 0, k: 1 });
  const drag = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null);

  const onWheel = useCallback((e: WheelEvent) => {
    e.preventDefault();
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const px = e.clientX - rect.left;
    const py = e.clientY - rect.top;
    setT((cur) => {
      const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
      const k = Math.min(20, Math.max(0.2, cur.k * factor));
      // keep the point under the cursor stationary
      const x = px - (px - cur.x) * (k / cur.k);
      const y = py - (py - cur.y) * (k / cur.k);
      return { x, y, k };
    });
  }, []);

  const onPointerDown = (e: PointerEvent) => {
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    drag.current = { x: e.clientX, y: e.clientY, ox: t.x, oy: t.y };
  };
  const onPointerMove = (e: PointerEvent) => {
    if (!drag.current) return;
    setT((cur) => ({
      ...cur,
      x: drag.current!.ox + (e.clientX - drag.current!.x),
      y: drag.current!.oy + (e.clientY - drag.current!.y),
    }));
  };
  const onPointerUp = () => { drag.current = null; };

  return (
    <div
      style={{ width: "100%", height: "100%", overflow: "hidden", cursor: "grab", position: "relative" }}
      onWheel={onWheel}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onDoubleClick={() => setT({ x: 0, y: 0, k: 1 })}
    >
      <div style={{
        transform: `translate(${t.x}px, ${t.y}px) scale(${t.k})`,
        transformOrigin: "0 0",
        width: "100%",
      }}>
        {children}
      </div>
      <div style={{
        position: "absolute", bottom: 6, right: 8, fontSize: 10,
        color: "var(--muted)", pointerEvents: "none",
      }}>
        {(t.k * 100).toFixed(0)}% · scroll=zoom drag=pan dbl-click=reset
      </div>
    </div>
  );
}
