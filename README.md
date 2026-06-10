# Mandrel

An open-source orchestration engine that turns a product idea into a verified, manufacturable electronics design and its matching enclosure or MCAD fixture.

Mandrel drives best-in-class open-source design engines (KiCad, FreeRouting, build123d/FreeCAD, ngspice, CalculiX) through neutral interchange files, holds a single canonical design state, and gates every stage with a deterministic verifier. The LLM proposes; verifiers and humans dispose.

**License:** Apache-2.0. GPL tools (KiCad, FreeRouting, FreeCAD, CalculiX) are invoked out-of-process only — never linked.

## Quick start

```bash
# Prerequisites: Docker, uv, Ollama with gemma4:26b pulled
cp .env.example .env            # edit keys and paths
docker compose up -d            # postgres + minio
uv sync
uv run alembic upgrade head
uv run pytest
```

## Pipeline stages

| # | Stage | Gate |
|---|---|---|
| 1 | Intent capture → `ProductSpec` | schema valid + human checkpoint |
| 2 | Architecture + grounded part selection | all MPNs real & in stock |
| 3 | Schematic (SKiDL → KiCad) | ERC clean + human checkpoint |
| 4 | PCB layout (FreeRouting) | DRC clean |
| 5 | Enclosure (board STEP → build123d) | clearance/fit passes |
| 6 | BOM + sourcing | every line resolves to stock |
| 7 | Manufacturing handoff | fab DFM + human checkpoint |

## Engine containers

Engine containers (KiCad, FreeCAD, FreeRouting) are optional and require `--profile engines`:

```bash
docker compose --profile engines up -d
```

## Architecture principles

- **Process boundary = license boundary.** No GPL library is ever imported into Mandrel's Python code.
- **Verification-first.** No stage advances until a deterministic verifier passes.
- **Ground every part.** No MPN enters a design until confirmed real and in stock via distributor API.
- **Human checkpoints** at spec, schematic, and fit.
