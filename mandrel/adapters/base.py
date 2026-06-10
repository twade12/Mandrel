"""Adapter protocol — wraps out-of-process engine invocations.

All GPL-licensed tools (KiCad, FreeRouting, FreeCAD, CalculiX) are invoked
exclusively through Adapter.invoke(). No GPL symbol may be imported into
Mandrel's own code — this file is the license boundary.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class Adapter(Protocol):
    """Invoke an external tool out-of-process.

    Writes native input files, runs the tool's CLI/headless/JVM,
    reads outputs back. Exchanges data only through neutral files.
    """

    def invoke(self, inputs: dict[str, Path]) -> dict[str, Path]:
        """Run the tool and return a mapping of output-name → output-path."""
        ...
