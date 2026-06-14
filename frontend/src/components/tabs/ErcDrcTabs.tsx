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
  return (
    <ViolationsTab
      title="DRC — Design Rules Check"
      result={design?.pcb?.drc_result}
      emptyHint="DRC results appear after S4 (PCB Layout + DRC)."
    />
  );
}
