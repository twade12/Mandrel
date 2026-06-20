import { DockviewReact, DockviewReadyEvent, IDockviewPanelProps } from "dockview-react";
import { useStore } from "../state";
import { DeviceSpecsTab } from "./tabs/DeviceSpecsTab";
import { SchematicTab } from "./tabs/SchematicTab";
import { PcbLayoutTab } from "./tabs/PcbLayoutTab";
import { ModelTab } from "./tabs/ModelTab";
import { BomTab } from "./tabs/BomTab";
import { ErcTab, DrcTab } from "./tabs/ErcDrcTabs";

// dockview renders panel bodies from this component map by key. Each wrapper
// pulls live design state from the store, so panels update as the run streams.
const components: Record<string, React.FC<IDockviewPanelProps>> = {
  specs: () => <DeviceSpecsTab />,
  schematic: () => <SchematicTab />,
  erc: () => <ErcTab />,
  pcb: () => <PcbLayoutTab />,
  drc: () => <DrcTab />,
  model: () => <ModelTab />,
  bom: () => <BomTab />,
};

function onReady(event: DockviewReadyEvent) {
  const api = event.api;
  const specs = api.addPanel({ id: "specs", component: "specs", title: "Device Specs" });
  const schematic = api.addPanel({ id: "schematic", component: "schematic", title: "Schematic" });
  api.addPanel({ id: "erc", component: "erc", title: "ERC" });
  // PCB opens to the right of the spec/schematic group → VS-Code-style split.
  const pcb = api.addPanel({
    id: "pcb", component: "pcb", title: "PCB Layout",
    position: { referencePanel: specs.id, direction: "right" },
  });
  api.addPanel({ id: "drc", component: "drc", title: "DRC", position: { referencePanel: pcb.id, direction: "within" } });
  api.addPanel({ id: "model", component: "model", title: "3D Model", position: { referencePanel: pcb.id, direction: "within" } });
  api.addPanel({ id: "bom", component: "bom", title: "BOM + Sourcing", position: { referencePanel: pcb.id, direction: "within" } });
  specs.api.setActive();
  void schematic;
}

export function Dock() {
  const { theme } = useStore();
  return (
    <DockviewReact
      components={components}
      onReady={onReady}
      className={theme === "light" ? "dockview-theme-light" : "dockview-theme-dark"}
    />
  );
}
