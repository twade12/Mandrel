import { useStore } from "../../state";
import { ArtifactImage } from "./ArtifactImage";

export function SchematicTab() {
  const { design, stageStatus } = useStore();
  const ready = !!design?.schematic?.kicad_sch_path || stageStatus["s3_schematic"] === "passed";
  return <ArtifactImage name="schematic.svg" ready={ready} hint="Schematic appears after S3 (Schematic + ERC)." />;
}
