"""SKiDL generation adapter.

SKiDL is MIT-licensed and could run in-process, but LLM-generated code executes
in a subprocess for safety. The subprocess inherits KICAD_SYMBOL_DIR so SKiDL can
resolve part symbols from the installed KiCad library path.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

from mandrel.config import settings


class SKiDLError(RuntimeError):
    pass


class SKiDLAdapter:
    """Runs LLM-generated SKiDL Python scripts in a sandboxed subprocess."""

    def __init__(
        self,
        kicad_lib_path: str | None = None,
        timeout: int = 90,
    ) -> None:
        self._lib_path = kicad_lib_path or settings.kicad_lib_path
        self._timeout = timeout

    def run_script(self, script: str, output_dir: Path) -> dict[str, Path]:
        """Execute a SKiDL Python script; return {stem: path} of generated files.

        The script must call generate_schematic() and generate_netlist() before exit.
        """
        output_dir = output_dir.resolve()  # subprocess cwd — relative paths double up
        output_dir.mkdir(parents=True, exist_ok=True)
        script_path = output_dir / "_skidl_gen.py"

        # Prepend env setup so the subprocess can find KiCad symbol libraries.
        # SKiDL keys its lookup on the KiCad-version-specific variable
        # (KICAD9_SYMBOL_DIR for skidl 2.x), so set every variant.
        preamble = textwrap.dedent(f"""\
            import os, sys
            for _var in (
                "KICAD_SYMBOL_DIR", "KICAD5_SYMBOL_DIR", "KICAD6_SYMBOL_DIR",
                "KICAD7_SYMBOL_DIR", "KICAD8_SYMBOL_DIR", "KICAD9_SYMBOL_DIR",
                "SKIDL_KICAD_LIB_SEARCH_PATHS",
            ):
                os.environ.setdefault(_var, {self._lib_path!r})
        """)
        script_path.write_text(preamble + script, encoding="utf-8")

        env = {
            **os.environ,
            **{
                var: self._lib_path
                for var in (
                    "KICAD_SYMBOL_DIR", "KICAD5_SYMBOL_DIR", "KICAD6_SYMBOL_DIR",
                    "KICAD7_SYMBOL_DIR", "KICAD8_SYMBOL_DIR", "KICAD9_SYMBOL_DIR",
                )
            },
        }
        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            cwd=str(output_dir),
            timeout=self._timeout,
            env=env,
        )
        if result.returncode != 0:
            raise SKiDLError(
                f"SKiDL script failed (exit {result.returncode}):\n"
                f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )

        outputs: dict[str, Path] = {}
        for path in output_dir.iterdir():
            if path.suffix in {".kicad_sch", ".net", ".xml"}:
                outputs[path.stem] = path
        return outputs
