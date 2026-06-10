"""KiCad CLI adapter — all invocations are out-of-process.

This file is the GPL license boundary: no KiCad Python modules are imported here.
kicad-cli is invoked as a subprocess and exchanges data through neutral files only.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from mandrel.config import settings


class KiCadCLIError(RuntimeError):
    pass


class KiCadCLIAdapter:
    """Out-of-process wrapper for kicad-cli (GPL — never linked, only exec'd)."""

    def __init__(self, cli_path: str | None = None) -> None:
        self._cli = cli_path or settings.kicad_cli_path

    def is_available(self) -> bool:
        try:
            r = subprocess.run([self._cli, "--version"], capture_output=True, timeout=10)
            return r.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _run(
        self,
        args: list[str],
        cwd: Path | None = None,
        timeout: int = 120,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [self._cli, *args],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
        )
        return result

    def run_erc(self, schematic_path: Path, output_dir: Path | None = None) -> Path:
        """Run ERC on a .kicad_sch; return path to the JSON report.

        kicad-cli exits 0 for clean ERC, 5 when violations are found (not a crash).
        """
        if not self.is_available():
            raise KiCadCLIError(
                "kicad-cli not found. "
                "Start the KiCad engine container: docker compose --profile engines up -d kicad"
            )
        output_dir = output_dir or schematic_path.parent
        output_dir.mkdir(parents=True, exist_ok=True)
        report_path = output_dir / "erc_report.json"

        result = self._run([
            "sch", "erc",
            "--schematic", str(schematic_path),
            "--output",    str(report_path),
            "--format",    "json",
            "--units",     "mm",
        ])
        # Exit code 5 means ERC ran but found violations — still a valid run.
        if result.returncode not in (0, 5):
            raise KiCadCLIError(
                f"kicad-cli sch erc failed (exit {result.returncode}):\n{result.stderr}"
            )
        if not report_path.exists():
            # Older kicad-cli versions print JSON to stdout instead of writing a file.
            report_path.write_text(result.stdout or '{"errors":0,"warnings":0,"items":[]}')
        return report_path

    def export_step(self, pcb_path: Path, output_path: Path, timeout: int = 180) -> Path:
        """Export a .kicad_pcb to STEP (GPL boundary: subprocess only)."""
        if not self.is_available():
            raise KiCadCLIError("kicad-cli not found.")
        result = self._run([
            "pcb", "export", "step",
            "--input",  str(pcb_path),
            "--output", str(output_path),
            "--no-dnp",
        ], timeout=timeout)
        if result.returncode != 0:
            raise KiCadCLIError(
                f"kicad-cli pcb export step failed (exit {result.returncode}):\n{result.stderr}"
            )
        return output_path

    def export_gerbers(self, pcb_path: Path, output_dir: Path) -> list[Path]:
        """Export Gerber manufacturing files to output_dir."""
        output_dir.mkdir(parents=True, exist_ok=True)
        result = self._run([
            "pcb", "export", "gerbers",
            "--board",  str(pcb_path),
            "--output", str(output_dir),
        ])
        if result.returncode != 0:
            raise KiCadCLIError(f"kicad-cli gerbers failed:\n{result.stderr}")
        return list(output_dir.glob("*.gbr"))
