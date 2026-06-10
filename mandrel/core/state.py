"""Canonical design state — the single source of truth across all pipeline stages."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ── Shared primitives ─────────────────────────────────────────────────────────


class Violation(BaseModel):
    code: str
    message: str
    severity: str = "error"
    location: str | None = None


class VerifierResult(BaseModel):
    passed: bool
    score: float = 0.0
    violations: list[Violation] = []


# ── Part: always carries a verified MPN ───────────────────────────────────────


class DistributorRef(BaseModel):
    distributor: str  # "digikey" | "mouser" | "octopart" | "lcsc"
    sku: str
    url: str | None = None
    stock_qty: int | None = None
    unit_price_usd: float | None = None


class Part(BaseModel):
    """A component whose MPN has been confirmed real and in stock via distributor API.

    No Part may enter DesignState.bom without in_stock=True and at least one
    distributor_ref. This is the ground-every-part invariant (§0).

    reference/value/footprint are populated by S3 (schematic); manufacturer is
    populated by S6 (sourcing). Both stages fill in their own fields.
    """

    mpn: str
    reference: str = ""          # e.g. "U1", "C3" — set by S3
    manufacturer: str = ""       # set by S6 from distributor API
    value: str = ""              # e.g. "100nF" — set by S3
    footprint: str = ""          # KiCad footprint string — set by S3
    distributor_refs: list[DistributorRef] = []
    in_stock: bool = False
    unit_price_usd: float | None = None


# ── S1: ProductSpec ───────────────────────────────────────────────────────────


class PowerBudget(BaseModel):
    supply_voltage_v: float
    max_current_ma: float
    battery_capacity_mah: float | None = None


class ProductSpec(BaseModel):
    title: str = ""
    description: str = ""
    functions: list[str] = []
    interfaces: list[str] = []  # "USB-C", "I2C", "SPI", etc.
    power: PowerBudget | None = None
    environment: str | None = None
    target_cost_usd: float | None = None
    target_qty: int | None = None
    user_supplied_parts: list[Part] = []
    raw_brief: str = ""


# ── S2: Architecture ──────────────────────────────────────────────────────────


class Block(BaseModel):
    id: str
    label: str
    proposed_mpn: str | None = None   # suggested by S2, verified in S6
    kicad_lib: str | None = None      # "Library:Symbol" for S3 SKiDL generation
    part: Part | None = None          # populated by S6 after distributor verification


class Connection(BaseModel):
    from_block: str
    to_block: str
    signal: str


class Architecture(BaseModel):
    blocks: list[Block] = []
    connections: list[Connection] = []
    parts: list[Part] = []
    bom_preview_cost_usd: float | None = None


# ── S3: Schematic ─────────────────────────────────────────────────────────────


class SchematicArtifact(BaseModel):
    kicad_sch_path: str | None = None
    netlist_path: str | None = None
    skidl_script_path: str | None = None
    erc_result: VerifierResult | None = None


# ── S4: PCB ───────────────────────────────────────────────────────────────────


class PcbArtifact(BaseModel):
    kicad_pcb_path: str | None = None
    gerber_dir: str | None = None
    board_step_path: str | None = None
    pos_file_path: str | None = None
    drc_result: VerifierResult | None = None


# ── S5: Enclosure / fixture ───────────────────────────────────────────────────


class CadArtifact(BaseModel):
    step_path: str | None = None
    stl_path: str | None = None
    script_path: str | None = None
    clearance_result: VerifierResult | None = None
    fem_result: VerifierResult | None = None


# ── S6: BOM ───────────────────────────────────────────────────────────────────


class BomLine(BaseModel):
    part: Part
    quantity: int
    total_price_usd: float | None = None
    lead_time_days: int | None = None


class CostedBom(BaseModel):
    lines: list[BomLine] = []
    total_cost_usd: float | None = None
    all_in_stock: bool = False
    kicost_output_path: str | None = None
    sourcing_verified: bool = False  # True only when real distributor API was used


# ── S7: Handoff ───────────────────────────────────────────────────────────────


class HandoffPackage(BaseModel):
    gerber_zip_path: str | None = None
    bom_csv_path: str | None = None
    pos_csv_path: str | None = None
    assembly_doc_path: str | None = None
    enclosure_step_path: str | None = None
    enclosure_stl_path: str | None = None


# ── Constraints (target form factor + standards) ──────────────────────────────


class FormFactor(StrEnum):
    FEATHER = "feather"
    HAT = "hat"
    MIKROBUS = "mikrobus"
    ARDUINO_SHIELD = "arduino_shield"
    DIN_RAIL = "din_rail"
    CUSTOM = "custom"


class StandardsProfile(StrEnum):
    IPC_2221 = "ipc_2221"
    IPC_7351 = "ipc_7351"
    IPC_2152 = "ipc_2152"


class Constraints(BaseModel):
    form_factor: FormFactor = FormFactor.CUSTOM
    max_board_width_mm: float | None = None
    max_board_height_mm: float | None = None
    max_component_height_mm: float | None = None
    standards: list[StandardsProfile] = []
    reference_enclosure_step_path: str | None = None


# ── Stage run history ─────────────────────────────────────────────────────────


class StageRun(BaseModel):
    stage_name: str
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    started_at: datetime = Field(default_factory=_utcnow)
    completed_at: datetime | None = None
    success: bool | None = None
    verifier_result: VerifierResult | None = None
    error: str | None = None
    artifacts: list[str] = []


# ── Root ──────────────────────────────────────────────────────────────────────


class DesignState(BaseModel):
    project_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    spec: ProductSpec | None = None
    architecture: Architecture | None = None
    schematic: SchematicArtifact | None = None
    pcb: PcbArtifact | None = None
    enclosure: CadArtifact | None = None
    bom: CostedBom | None = None
    handoff: HandoffPackage | None = None
    constraints: Constraints = Field(default_factory=Constraints)
    history: list[StageRun] = []
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
