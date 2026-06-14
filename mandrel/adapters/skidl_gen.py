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
        kicad_footprint_path: str | None = None,
    ) -> None:
        self._lib_path = kicad_lib_path or settings.kicad_lib_path
        self._footprint_path = kicad_footprint_path or getattr(
            settings, "kicad_footprint_path", "/usr/share/kicad/footprints"
        )
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
        # (KICAD9_SYMBOL_DIR for skidl 2.x), so set every variant. Also point
        # the footprint dir so auto_stub's power symbols resolve.
        preamble = textwrap.dedent(f"""\
            import os, sys
            for _var in (
                "KICAD_SYMBOL_DIR", "KICAD5_SYMBOL_DIR", "KICAD6_SYMBOL_DIR",
                "KICAD7_SYMBOL_DIR", "KICAD8_SYMBOL_DIR", "KICAD9_SYMBOL_DIR",
                "SKIDL_KICAD_LIB_SEARCH_PATHS",
            ):
                os.environ.setdefault(_var, {self._lib_path!r})
            os.environ.setdefault("KICAD9_FOOTPRINT_DIR", {self._footprint_path!r})

            import skidl as _skidl

            # 1. Normalize a common LLM slip: Part("Lib:Symbol", ...) instead of
            #    Part("Lib", "Symbol", ...). MUST be a Part SUBCLASS, not a
            #    function — SKiDL's schematic router does `isinstance(p, Part)`
            #    after `from skidl import Part`, and a function isn't a type
            #    (crashes generate_schematic). A subclass stays a valid type.
            _OrigPart = _skidl.Part

            class _NormalizedPart(_OrigPart):
                def __init__(self, lib=None, name=None, *args, **kwargs):
                    if isinstance(lib, str) and ":" in lib:
                        _lib, _sym = lib.split(":", 1)
                        if name is None or name == _sym or name == lib:
                            lib, name = _lib, _sym
                        else:
                            lib = _lib
                    super().__init__(lib, name, *args, **kwargs)

                def __getitem__(self, key):
                    # Tolerate a common LLM slip: addressing a single-pin part
                    # (PWR_FLAG, test points) by a made-up name like ["flag"]
                    # instead of [1]. Only single-pin parts fall back; multi-pin
                    # parts keep normal behavior so real errors aren't masked.
                    try:
                        result = super().__getitem__(key)
                    except Exception:
                        result = None
                    if result is None and isinstance(key, str):
                        pins = self.get_pins()
                        if pins is not None:
                            if not isinstance(pins, (list, tuple)):
                                pins = [pins]
                            if len(pins) == 1:
                                return pins[0]
                    return result

            _skidl.Part = _NormalizedPart

            # 2. Force auto_stub on generate_schematic: SKiDL's wire auto-router
            #    is broken for non-trivial designs (py3.12), but auto_stub
            #    converts nets to global labels and skips routing, producing a
            #    valid openable .kicad_sch. Enforced here so a bare
            #    generate_schematic() call still gets it.
            _orig_gen_sch = _skidl.generate_schematic

            def _gen_schematic(*args, **kwargs):
                kwargs.setdefault("auto_stub", True)
                _inject_pwr_flags()
                return _orig_gen_sch(*args, **kwargs)

            _skidl.generate_schematic = _gen_schematic

            # 3. Auto-inject PWR_FLAG on power nets. PWR_FLAG is mechanical ERC
            #    boilerplate, and the LLM repeatedly crashes the script trying to
            #    wire it (pwr_flag["flag"], pwr_flag.flag[1], ...). The prompt now
            #    tells the model NEVER to touch PWR_FLAG; Mandrel adds them here,
            #    just before netlist/schematic generation, so power nets are
            #    flagged regardless of what the script wrote.
            _POWER_NET_NAMES = {
                "+3V3", "+3.3V", "3V3", "GND", "VBUS", "+5V", "5V",
                "VCC", "VDD", "VDDA", "VDDIO", "+1V8", "VSYS",
            }
            _flagged = set()

            def _inject_pwr_flags():
                import builtins as _bi
                _circuit = getattr(_bi, "default_circuit", None)
                if _circuit is None:
                    return
                for _net in list(_circuit.nets):
                    _nm = getattr(_net, "name", "") or ""
                    if _nm in _POWER_NET_NAMES and _nm not in _flagged:
                        _flagged.add(_nm)
                        try:
                            _f = _NormalizedPart("power", "PWR_FLAG")
                            _f[1] += _net
                        except Exception as _e:
                            print("PWR_FLAG inject skipped for", _nm, _e, file=sys.stderr)

            _orig_gen_netlist = _skidl.generate_netlist

            def _gen_netlist(*args, **kwargs):
                _inject_pwr_flags()
                return _orig_gen_netlist(*args, **kwargs)

            _skidl.generate_netlist = _gen_netlist
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
