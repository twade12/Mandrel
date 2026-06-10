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

    # Distributor API keys (empty = distributor integration disabled)
    digikey_client_id: str = ""
    digikey_client_secret: str = ""
    mouser_api_key: str = ""
    octopart_api_key: str = ""
    lcsc_api_key: str = ""

    # Engine paths (out-of-process invocation only — GPL boundary)
    kicad_cli_path: str = "kicad-cli"
    freerouting_jar_path: str = "freerouting.jar"
    freecad_cmd_path: str = "freecadcmd"
    ngspice_path: str = "ngspice"
    calculix_path: str = "ccx"

    # KiCad symbol library path (needed by SKiDL for part lookup)
    # Docker default: /usr/share/kicad/symbols
    # macOS KiCad app: /Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols
    kicad_lib_path: str = "/usr/share/kicad/symbols"


settings = Settings()
