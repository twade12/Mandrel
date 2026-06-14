import { Violation } from "../../api";

// Shared tabular view for ERC and DRC results.
export function ViolationsTab({
  title,
  result,
  emptyHint,
}: {
  title: string;
  result: { passed?: boolean; score?: number; violations?: Violation[] } | null | undefined;
  emptyHint: string;
}) {
  if (!result) return <div className="tab"><div className="placeholder">{emptyHint}</div></div>;
  const violations = result.violations ?? [];
  const errors = violations.filter((v) => v.severity === "error").length;
  const warnings = violations.filter((v) => v.severity === "warning").length;
  return (
    <div className="tab">
      <h2>{title}</h2>
      <div style={{ marginBottom: 12, display: "flex", gap: 10, alignItems: "center" }}>
        <span className={"badge " + (result.passed ? "ok" : "error")}>
          {result.passed ? "PASS" : "FAIL"}
        </span>
        <span className="muted">score {result.score?.toFixed(2) ?? "—"}</span>
        <span className="badge error">{errors} errors</span>
        <span className="badge warning">{warnings} warnings</span>
      </div>
      {violations.length === 0 ? (
        <div className="placeholder">No violations reported.</div>
      ) : (
        <table>
          <thead><tr><th>Severity</th><th>Code</th><th>Message</th></tr></thead>
          <tbody>
            {violations.map((v, i) => (
              <tr key={i}>
                <td><span className={"badge " + (v.severity === "error" ? "error" : "warning")}>{v.severity}</span></td>
                <td className="accent">{v.code}</td>
                <td>{v.message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
