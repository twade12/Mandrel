import { useStore } from "../../state";
import { ViolationsTab } from "./ViolationsTab";

export function ErcTab() {
  const { design } = useStore();
  return (
    <ViolationsTab
      title="ERC — Electrical Rules Check"
      result={design?.schematic?.erc_result}
      emptyHint="ERC results appear after S3 (Schematic + ERC)."
    />
  );
}

export function DrcTab() {
  const { design } = useStore();
  const rationale: any[] = design?.pcb?.placement_rationale ?? [];
  return (
    <div style={{ height: "100%", overflow: "auto" }}>
      <ViolationsTab
        title="DRC — Design Rules Check"
        result={design?.pcb?.drc_result}
        emptyHint="DRC results appear after S4 (PCB Layout + DRC)."
      />
      {rationale.length > 0 && <RationaleView rationale={rationale} />}
    </div>
  );
}

const STATUS_BADGE: Record<string, string> = { fail: "error", pass: "ok", considered: "warning" };

function RationaleView({ rationale }: { rationale: any[] }) {
  return (
    <div className="tab" style={{ paddingTop: 0 }}>
      <h2>Why this layout — design-rule rationale</h2>
      <p className="muted" style={{ fontSize: 11, marginTop: -6 }}>
        Best-practice rules the knowledge base applied to this placement, what was
        measured, and whether each was met.
      </p>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {rationale.map((r, i) => (
          <div key={i} style={{ border: "1px solid var(--border)", borderRadius: 6, padding: "8px 10px" }}>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <span className={"badge " + (STATUS_BADGE[r.status] ?? "warning")}>
                {r.status === "considered" ? "considered" : r.status.toUpperCase()}
              </span>
              <span className="muted" style={{ fontSize: 10, textTransform: "uppercase" }}>
                {r.category} · {r.severity}
              </span>
            </div>
            <div style={{ fontSize: 12, margin: "4px 0" }}>{r.statement}</div>
            {r.findings?.filter((f: any) => f.detail).map((f: any, j: number) => (
              <div key={j} className={f.ok ? "muted" : "text-error"} style={{ fontSize: 11, fontFamily: "var(--font)" }}>
                {f.ok ? "✓ " : "✗ "}{f.detail}
              </div>
            ))}
            {r.rationale && <div className="muted" style={{ fontSize: 10, marginTop: 4, fontStyle: "italic" }}>{r.rationale}</div>}
          </div>
        ))}
      </div>
    </div>
  );
}
