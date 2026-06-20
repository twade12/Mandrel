"""Ingestion source adapters."""

from .kicad_design import measure_kicad_pcb
from .text import from_text_file
from .web import from_url

__all__ = ["from_text_file", "from_url", "measure_kicad_pcb"]
