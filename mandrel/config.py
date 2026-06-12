from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MANDREL_", env_file=".env", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://mandrel:mandrel@localhost:5432/mandrel"

    # Artifact storage
    workspace_dir: Path = Path("./workspace")

    # MinIO
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "mandrel"
    minio_secret_key: str = "mandrel123"
    minio_bucket: str = "mandrel-artifacts"

    # LLM (OpenAI-compatible; default = Ollama local)
    llm_base_url: str = "http://localhost:11434/v1"
    llm_model: str = "gemma4:26b"
    llm_api_key: str = ""
    # Read timeout for a single completion. Local models generating long code
    # (S3 SKiDL scripts) can easily exceed 120 s — default generously.
    llm_timeout_s: float = 600.0
    # Reasoning models (gemma4, qwen3, deepseek-r1) burn the whole max_tokens
    # budget thinking before emitting content. "none" disables thinking for
    # Mandrel's structured-output tasks; set to "" to leave the model default.
    llm_reasoning_effort: str = "none"

    # Distributor API keys (empty = stub client used; real keys enable live grounding)
    # Nexar / Octopart: register at nexar.com to get client_id + client_secret
    nexar_client_id: str = ""
    nexar_client_secret: str = ""
    # Digikey / Mouser: reserved for future direct integrations
    digikey_client_id: str = ""
    digikey_client_secret: str = ""
    mouser_api_key: str = ""

    # Engine paths (out-of-process invocation only — GPL boundary)
    kicad_cli_path: str = "kicad-cli"
    # Python interpreter that has pcbnew in its path (KiCad container or system install).
    # Used for operations kicad-cli doesn't expose (SES import, placement scripts).
    kicad_python_path: str = "python3"
    freerouting_jar_path: str = "freerouting.jar"
    freecad_cmd_path: str = "freecadcmd"
    ngspice_path: str = "ngspice"
    calculix_path: str = "ccx"

    # KiCad symbol library path (needed by SKiDL for part lookup)
    # Docker default: /usr/share/kicad/symbols
    # macOS KiCad app: /Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols
    kicad_lib_path: str = "/usr/share/kicad/symbols"
    # KiCad footprint library path (S4 placement loads .pretty dirs from here)
    kicad_footprint_path: str = "/usr/share/kicad/footprints"


settings = Settings()
