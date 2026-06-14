import { useStore } from "../../state";
import { ArtifactImage } from "./ArtifactImage";

export function PcbLayoutTab() {
  const { design, stageStatus } = useStore();
  const ready = !!design?.pcb?.kicad_pcb_path || stageStatus["s4_layout"] === "passed";
  return <ArtifactImage name="pcb.svg" ready={ready} hint="PCB layout appears after S4 (PCB Layout + DRC)." />;
}
