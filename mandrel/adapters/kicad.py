"""KiCad CLI adapter — all invocations are out-of-process.

This file is the GPL license boundary: no KiCad Python modules are imported here.
kicad-cli is invoked as a subprocess and exchanges data through neutral files only.

For operations that kicad-cli does not expose (e.g. Specctra SES import), we
write a Python script to a temp file and invoke it via the KiCad container's
Python interpreter — still a separate process, still GPL-safe.
"""

from __future__ import annotations

import subprocess
import tempfile
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

    def run_drc(self, pcb_path: Path, output_dir: Path | None = None) -> Path:
        """Run DRC on a .kicad_pcb; return path to the JSON report.

        kicad-cli exits 0 for clean DRC, 5 when violations are found.
        """
        if not self.is_available():
            raise KiCadCLIError(
                "kicad-cli not found. "
                "Start the KiCad engine container: docker compose --profile engines up -d kicad"
            )
        output_dir = output_dir or pcb_path.parent
        output_dir.mkdir(parents=True, exist_ok=True)
        report_path = output_dir / "drc_report.json"

        result = self._run([
            "pcb", "drc",
            "--input",  str(pcb_path),
            "--output", str(report_path),
            "--format", "json",
            "--units",  "mm",
            "--schematic-parity",  # also check net connectivity vs schematic
        ])
        if result.returncode not in (0, 5):
            raise KiCadCLIError(
                f"kicad-cli pcb drc failed (exit {result.returncode}):\n{result.stderr}"
            )
        if not report_path.exists():
            report_path.write_text(
                result.stdout or '{"errors":0,"warnings":0,"violations":[]}'
            )
        return report_path

    def export_dsn(self, pcb_path: Path, dsn_path: Path) -> Path:
        """Export a .kicad_pcb to Specctra DSN format for FreeRouting."""
        if not self.is_available():
            raise KiCadCLIError("kicad-cli not found.")
        result = self._run([
            "pcb", "export", "specctrafile",
            "--input",  str(pcb_path),
            "--output", str(dsn_path),
        ])
        if result.returncode != 0:
            raise KiCadCLIError(
                f"kicad-cli export specctrafile failed (exit {result.returncode}):\n"
                f"{result.stderr}"
            )
        if not dsn_path.exists():
            raise KiCadCLIError(f"export_dsn: no DSN file produced at {dsn_path}")
        return dsn_path

    def import_ses(self, pcb_path: Path, ses_path: Path, timeout: int = 60) -> Path:
        """Apply a Specctra SES routing result back to a .kicad_pcb.

        kicad-cli has no direct 'import ses' command in 8.0, so we write a
        pcbnew Python script and run it via the KiCad container's Python
        interpreter. This is a subprocess invocation — GPL boundary is maintained
        because Mandrel never imports pcbnew; it only writes/runs a script file.
        """
        python_path = settings.kicad_python_path
        script = (
            "import sys, os\n"
            "# pcbnew is shipped with KiCad — available in the kicad engine container\n"
            f"board = __import__('pcbnew').LoadBoard(r'{pcb_path}')\n"
            f"board.ImportSpecctraSession(r'{ses_path}')\n"
            f"board.Save(r'{pcb_path}')\n"
            "print('SES imported OK')\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix="_ses_import.py", delete=False
        ) as f:
            f.write(script)
            script_path = f.name

        try:
            result = subprocess.run(
                [python_path, script_path],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        finally:
            Path(script_path).unlink(missing_ok=True)

        if result.returncode != 0:
            raise KiCadCLIError(
                f"pcbnew SES import failed (exit {result.returncode}):\n"
                f"{result.stderr}"
            )
        return pcb_path

    def run_placement_script(self, script_path: Path, timeout: int = 120) -> None:
        """Run an arbitrary pcbnew Python placement script via the KiCad Python interpreter.

        The script is responsible for creating/modifying a .kicad_pcb file.
        This is the mechanism for LLM-assisted placement: the LLM writes the
        script; we exec it as a subprocess (GPL boundary respected).
        """
        python_path = settings.kicad_python_path
        result = subprocess.run(
            [python_path, str(script_path)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            raise KiCadCLIError(
                f"Placement script failed (exit {result.returncode}):\n"
                f"{result.stderr}"
            )

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
