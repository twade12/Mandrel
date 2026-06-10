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
        output_dir.mkdir(parents=True, exist_ok=True)
        script_path = output_dir / "_skidl_gen.py"

        # Prepend env setup so the subprocess can find KiCad symbol libraries.
        preamble = textwrap.dedent(f"""\
            import os, sys
            os.environ.setdefault("KICAD_SYMBOL_DIR", {self._lib_path!r})
            os.environ.setdefault(
                "SKIDL_KICAD_LIB_SEARCH_PATHS",
                {self._lib_path!r},
            )
        """)
        script_path.write_text(preamble + script, encoding="utf-8")

        env = {
            **os.environ,
            "KICAD_SYMBOL_DIR": self._lib_path,
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
