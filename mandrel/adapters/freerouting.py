"""FreeRouting adapter — GPL boundary: invoked via `java -jar freerouting.jar`.

Exchange format: Specctra DSN in → Specctra SES out.
Mandrel never imports any FreeRouting class; data moves only through neutral files.

FreeRouting CLI flags (>= 1.7 / ghcr.io release):
  -de <file>   input DSN file
  -do <file>   output SES file
  -mp <n>      max autorouter passes (default 100)
  -s           non-interactive / batch mode
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from mandrel.config import settings


class FreeRoutingError(RuntimeError):
    pass


class FreeRoutingAdapter:
    """Invoke FreeRouting JAR out-of-process for DSN→SES autorouting."""

    def __init__(self, jar_path: str | None = None) -> None:
        self._jar = jar_path or settings.freerouting_jar_path

    def is_available(self) -> bool:
        try:
            r = subprocess.run(
                ["java", "-version"],
                capture_output=True, timeout=10,
            )
            if r.returncode != 0:
                return False
            return Path(self._jar).exists()
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return False

    def route(
        self,
        dsn_path: Path,
        ses_path: Path,
        max_passes: int = 100,
        timeout: int = 300,
    ) -> Path:
        """Route dsn_path and write the SES result to ses_path.

        Raises FreeRoutingError if the JAR is missing, routing fails,
        or no SES file is produced within the timeout.
        """
        if not self.is_available():
            raise FreeRoutingError(
                f"FreeRouting JAR not found at: {self._jar}\n"
                "Start the engine container: "
                "docker compose --profile engines up -d freerouting"
            )
        result = subprocess.run(
            [
                "java", "-jar", self._jar,
                "-de", str(dsn_path),
                "-do", str(ses_path),
                "-mp", str(max_passes),
                "-s",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            raise FreeRoutingError(
                f"FreeRouting failed (exit {result.returncode}):\n"
                f"{result.stderr or result.stdout}"
            )
        if not ses_path.exists():
            raise FreeRoutingError(
                f"FreeRouting exited 0 but produced no SES file at {ses_path}"
            )
        return ses_path
