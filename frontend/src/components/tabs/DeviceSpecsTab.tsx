import { useStore } from "../../state";

export function DeviceSpecsTab() {
  const { design } = useStore();
  const spec = design?.spec;
  const arch = design?.architecture;
  if (!spec) return <div className="tab"><div className="placeholder">No spec yet — run the pipeline.</div></div>;
  return (
    <div className="tab">
      <h2>Product Spec</h2>
      <div className="kv">
        <span className="k">Title</span><span className="accent">{spec.title}</span>
        <span className="k">Description</span><span>{spec.description}</span>
        {spec.functions?.length > 0 && (
          <>
            <span className="k">Functions</span>
            <span>{spec.functions.join(", ")}</span>
          </>
        )}
        {spec.interfaces?.length > 0 && (
          <>
            <span className="k">Interfaces</span>
            <span>{spec.interfaces.join(", ")}</span>
          </>
        )}
        {spec.power && (
          <>
            <span className="k">Power</span>
            <span>{spec.power.supply_voltage_v} V · {spec.power.max_current_ma} mA max</span>
          </>
        )}
        {spec.environment && (<><span className="k">Environment</span><span>{spec.environment}</span></>)}
      </div>

      {arch?.blocks?.length > 0 && (
        <>
          <h2 style={{ marginTop: 24 }}>Architecture</h2>
          <table>
            <thead><tr><th>Block</th><th>Label</th><th>Proposed MPN</th></tr></thead>
            <tbody>
              {arch.blocks.map((b: any) => (
                <tr key={b.id}><td className="accent">{b.id}</td><td>{b.label}</td><td>{b.proposed_mpn ?? "—"}</td></tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
