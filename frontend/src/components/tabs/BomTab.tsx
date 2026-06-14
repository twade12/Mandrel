import { useStore } from "../../state";

export function BomTab() {
  const { design } = useStore();
  const bom = design?.bom;
  if (!bom?.lines?.length) return <div className="tab"><div className="placeholder">No BOM yet.</div></div>;
  return (
    <div className="tab">
      <h2>BOM &amp; Sourcing</h2>
      <div style={{ marginBottom: 12, display: "flex", gap: 10, alignItems: "center" }}>
        <span className={"badge " + (bom.all_in_stock ? "ok" : "warning")}>
          {bom.all_in_stock ? "All in stock" : "Stock gaps"}
        </span>
        {bom.total_cost_usd != null && <span className="muted">${bom.total_cost_usd.toFixed(2)} est.</span>}
        {!bom.sourcing_verified && <span className="badge warning">UNVERIFIED (stub/API)</span>}
      </div>
      <table>
        <thead><tr><th>Ref</th><th>MPN</th><th>Description</th><th>Distributor</th><th>Stock</th><th>Price</th></tr></thead>
        <tbody>
          {bom.lines.map((ln: any, i: number) => {
            const p = ln.part;
            const dist = p.distributor_refs?.[0]?.distributor ?? "—";
            return (
              <tr key={i}>
                <td className="accent">{p.reference ?? "—"}</td>
                <td>{p.mpn}</td>
                <td>{p.value ?? "—"}</td>
                <td>{dist}</td>
                <td><span className={"badge " + (p.in_stock ? "ok" : "error")}>{p.in_stock ? "YES" : "NO"}</span></td>
                <td>{p.unit_price_usd ? "$" + p.unit_price_usd.toFixed(2) : "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
