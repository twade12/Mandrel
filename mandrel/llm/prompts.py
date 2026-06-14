"""Versioned prompt templates for each pipeline stage.

Each constant is a Python str.format-compatible template.
Keep prompts in this module so they are reviewable and diffable alongside the code.
"""

from __future__ import annotations

# ── S1 — brief → ProductSpec ──────────────────────────────────────────────────

S1_BRIEF_TO_SPEC = """\
You are an expert hardware product engineer. Extract a structured product specification
from the brief below and return it as a single JSON object matching the schema exactly.

BRIEF:
{raw_brief}

FORM FACTOR (if provided): {form_factor}

OUTPUT FORMAT — return ONLY this JSON object, no markdown fences, no extra text:
{{
  "title": "<short product name, ≤ 60 chars>",
  "description": "<one or two sentence description>",
  "functions": ["<primary function 1>", "<primary function 2>"],
  "interfaces": ["USB-C", "I2C"],
  "power": {{
    "supply_voltage_v": 3.3,
    "max_current_ma": 200,
    "battery_capacity_mah": null
  }},
  "environment": "<operating environment, e.g. indoor 0–70°C>",
  "target_cost_usd": null,
  "target_qty": null
}}

RULES:
- interfaces must use standard names: USB-C, I2C, SPI, UART, BLE, WiFi, LoRa, CAN, etc.
- supply_voltage_v is the regulated rail (typically 3.3 or 5.0)
- max_current_ma is the worst-case draw of all loads combined
- Set battery_capacity_mah only if the device is battery-powered
- Return null for any optional field you cannot determine from the brief
"""

# ── S2 — ProductSpec → Architecture block diagram ────────────────────────────

S2_ARCH_GEN = """\
You are an expert hardware architect. Given the product specification below, propose a
block-level architecture for the design and return it as a single JSON object.

PRODUCT SPEC (JSON):
{spec_json}

FORM FACTOR: {form_factor}

OUTPUT FORMAT — return ONLY this JSON object, no markdown fences, no extra text:
{{
  "blocks": [
    {{
      "id": "<short_snake_case_id>",
      "label": "<human-readable label>",
      "proposed_mpn": "<manufacturer part number>",
      "kicad_lib": "<KiCad Library:Symbol reference>"
    }}
  ],
  "connections": [
    {{
      "from_block": "<block_id>",
      "to_block": "<block_id>",
      "signal": "<NET_NAME>"
    }}
  ],
  "rationale": "<2–4 sentences explaining the key architectural decisions>"
}}

KICAD SYMBOL REFERENCES (verified against the KiCad 9 libraries — use exactly as shown):
- RP2040 MCU:        MCU_RaspberryPi:RP2040
- 3.3 V LDO:         Regulator_Linear:MIC5219-3.3YM5
- Temp/humidity:     Sensor_Humidity:SHT30-DIS  (I2C; use MPN SHT30-DIS-B)
- Pressure:          Sensor_Pressure:BMP280
- IMU / motion:      Sensor_Motion:ICM-20948
- USB-C receptacle:  Connector:USB_C_Receptacle_USB2.0_16P
- Generic R:         Device:R
- Generic C:         Device:C

RULES:
- For Feather form factor: MCU must be RP2040; include a 3.3 V LDO (MIC5219-3.3YM5) fed
  from USB 5 V (VBUS), and a USB-C receptacle block.
- Block id values must be valid Python identifiers (no spaces, no hyphens).
- Every connection's from_block and to_block must match an id in the blocks list.
- Include only blocks that are actually needed by the spec — no placeholders.
- Signal names should be valid KiCad net names (no spaces; use underscores).
- Return null for kicad_lib only when the part has no standard KiCad symbol.
- Return ONLY the JSON — all explanation goes in the "rationale" field.
"""

# ── S3 — ProductSpec → SKiDL Python schematic ─────────────────────────────────

S3_SKIDL_GEN = """\
You are an expert hardware design engineer. Write a complete, runnable SKiDL Python
script that implements the schematic described by the product specification below.

PRODUCT SPEC (JSON):
{spec_json}

APPROVED ARCHITECTURE (from S2 — implement exactly these blocks and connections):
{arch_json}

FORM FACTOR: Adafruit Feather (50.8 mm × 22.86 mm, 3.3 V system)

REQUIRED CIRCUIT BLOCKS:
1. MCU — choose one appropriate to the spec (e.g. RP2040 for USB + general I/O)
2. 3.3 V LDO — powers the MCU and peripherals from USB 5 V (e.g. MIC5219-3.3YM5)
3. USB-C receptacle — for power + data (use CC resistors if MCU has native USB)
4. Peripheral ICs — one per function listed in spec["functions"], e.g.:
   - temperature/humidity → SHT30-DIS (I2C)
   - pressure → BMP280 (I2C/SPI)
   - motion/IMU → ICM-20948 (I2C/SPI)
5. Bypass/decoupling caps on every VDD pin (100 nF ceramic + 10 µF bulk where needed)
6. I2C pull-up resistors (4.7 kΩ to 3.3 V on SDA/SCL)

OUTPUT DIRECTORY: {output_dir}

SKIDL API REFERENCE:
```python
from skidl import *

# Load a part from KiCad symbol library
u1 = Part("MCU_RaspberryPi", "RP2040",
          footprint="Package_DFN_QFN:QFN-56-1EP_7x7mm_P0.4mm_EP3.2x3.2mm")
r1 = Part("Device", "R", footprint="Resistor_SMD:R_0402_1005Metric", value="4.7k")
c1 = Part("Device", "C", footprint="Capacitor_SMD:C_0402_1005Metric", value="100nF")

# Define nets
vbus = Net("VBUS")    # USB 5 V input
v3v3 = Net("+3V3")   # regulated 3.3 V rail
gnd  = Net("GND")

# Connect pins — address IC/connector pins by NAME, only R/C by integer.
# (USB-C and QFN pin "numbers" are strings like A6/B7; integer indexing
# returns None and crashes.)
u1["VDD"] += v3v3
u1["GND"] += gnd
r1[1]     += v3v3   # 2-pin R/C may use [1] and [2]
r1[2]     += i2c_sda

# USB-C receptacle: pin names are VBUS, GND, CC1, CC2, D+, D-, SHIELD
usb["VBUS"]   += vbus
usb["GND"]    += gnd
usb["SHIELD"] += gnd
usb["CC1"]    += cc1   # 5.1k pull-down to GND (UFP sink)
usb["CC2"]    += cc2   # 5.1k pull-down to GND

# At the END of your script, use EXACTLY this closing block
# (note: generate_netlist takes file_ — not filepath):
ERC()
generate_netlist(file_="{output_dir}/netlist.net")
try:
    # auto_stub=True is required: it converts nets to global labels and skips
    # SKiDL's (broken) wire router, producing a valid skidl.kicad_sch.
    generate_schematic(auto_stub=True)
except Exception as exc:
    print(f"schematic generation skipped: {{exc}}")
```

KICAD SYMBOL LIBRARY NAMES (verified against the KiCad 9 libraries — use exactly as shown):
- RP2040:          MCU_RaspberryPi:RP2040
- MIC5219-3.3:     Regulator_Linear:MIC5219-3.3YM5
- Temp/humidity:   Sensor_Humidity:SHT30-DIS
- Pressure:        Sensor_Pressure:BMP280
- IMU / motion:    Sensor_Motion:ICM-20948
- USB-C receptacle: Connector:USB_C_Receptacle_USB2.0_16P
- Generic R:       Device:R
- Generic C:       Device:C
- PWR_FLAG:        power:PWR_FLAG

VERIFIED PIN NAMES (use exactly these — no other names exist on these symbols):
- RP2040: IOVDD, DVDD, USB_VDD, ADC_AVDD, VREG_VIN, VREG_VOUT, GND,
  GPIO0..GPIO29, USB_DP, USB_DM, XIN, XOUT, RUN, SWCLK, SWDIO, TESTEN,
  QSPI_SCLK, QSPI_SD0..QSPI_SD3, ~{{QSPI_SS}}.
  Power: IOVDD/USB_VDD/ADC_AVDD/VREG_VIN → +3V3; VREG_VOUT → DVDD; GND → GND;
  TESTEN → GND; RUN → 10k pull-up to +3V3. I2C: pick GPIO4 (SDA) and GPIO5 (SCL).
- MIC5219-3.3YM5: IN, OUT, GND, EN, BP.  (EN → IN; BP → 470 pF cap to GND or leave)
- SHT30-DIS: VDD, VSS, SDA, SCL, ADDR, ALERT, R, ~{{RESET}}.
  (VSS → GND; ADDR → GND; nRESET/R may float)
- BMP280: VDD, VDDIO, GND, SCK, SDI, SDO, CSB.
  (I2C mode: SCK=SCL, SDI=SDA, CSB → VDDIO, SDO → GND)
- ICM-20948: VDD, VDDIO, GND, SCL/SCLK, SDA/SDI, SDO/AD0, INT1, REGOUT, FSYNC,
  AUX_CL, AUX_DA, ~{{CS}}.  (I2C mode: ~{{CS}} → VDDIO; REGOUT → 100 nF to GND)
- USB_C_Receptacle_USB2.0_16P: VBUS, GND, SHIELD, CC1, CC2, D+, D-, SBU1, SBU2.
- PWR_FLAG: one pin — flag[1].

VERIFIED FOOTPRINTS (use exactly these in the footprint= argument — symbol
names are NOT footprint names):
- RP2040:    Package_DFN_QFN:QFN-56-1EP_7x7mm_P0.4mm_EP3.2x3.2mm
- MIC5219 (SOT-23-5): Package_TO_SOT_SMD:SOT-23-5
- SHT30-DIS: Sensor_Humidity:Sensirion_DFN-8-1EP_2.5x2.5mm_P0.5mm_EP1.1x1.7mm
- BMP280:    Package_LGA:Bosch_LGA-8_2.5x2.5mm_P0.65mm_ClockwisePinNumbering
- ICM-20948: Sensor_Motion:InvenSense_QFN-24_3x3mm_P0.4mm
- USB-C 16P: Connector_USB:USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal
- R 0402:    Resistor_SMD:R_0402_1005Metric
- C 0402:    Capacitor_SMD:C_0402_1005Metric
- C 0603:    Capacitor_SMD:C_0603_1608Metric
- PWR_FLAG:  no footprint (virtual part — omit the footprint= argument)

RULES:
- Every net named +3V3 must connect to both the LDO output AND a PWR_FLAG.
- Every net named GND must connect to a PWR_FLAG.
- Add decoupling caps on all VDD/VDDIO pins.
- Address pins on ICs and connectors by NAME (u["VDD"]); integer indexing is
  allowed only on 2-pin R/C parts.
- Part() takes library and symbol as SEPARATE arguments:
  Part("Connector", "USB_C_Receptacle_USB2.0_16P") — never the combined
  "Lib:Symbol" string.
- Do NOT hallucinate library names — use only the ones listed above.
- The last lines of the script MUST be the closing block shown above (ERC, then
  generate_netlist with file_=, then the guarded generate_schematic call).
- Return ONLY the Python code, no markdown, no explanation.
"""

# ── S4 — placement proposal for LLM-assisted PCB layout ──────────────────────

S4_PLACEMENT_GEN = """\
You are an expert PCB layout engineer. Propose component placements for the PCB
described below and return a JSON array of placement objects.

BOARD DIMENSIONS: {board_l_mm} mm × {board_w_mm} mm  (origin at lower-left corner)
FORM FACTOR: {form_factor}

The board outline, mounting holes, and the USB-C receptacle are already placed
by a fixed template — DO NOT place them. The USB-C connector occupies the LEFT
short edge. You place ONLY the components listed below, and ALL of them must fall
inside this keep-in rectangle (mm): x in [{keep_in_x0}, {keep_in_x1}],
y in [{keep_in_y0}, {keep_in_y1}]. Anything outside it collides with the
connector, the mounting holes, or the board edge.

COMPONENTS (from netlist; "size_mm": [width, height] is each part's real
courtyard bounding box, measured from its KiCad footprint):
{components_json}

ARCHITECTURE (for context):
{arch_json}

OUTPUT FORMAT — return ONLY a JSON array, no markdown fences, no extra text:
[
  {{
    "ref":          "<reference designator, e.g. U1>",
    "x_mm":         <x position from left edge, float>,
    "y_mm":         <y position from top edge, float>,
    "rotation_deg": <0 | 90 | 180 | 270>,
    "side":         "front"
  }}
]

PLACEMENT RULES:
1. All components must be on the "front" side unless stated otherwise.
2. EVERY part's centroid must lie inside the keep-in rectangle given above.
3. MCU (largest IC) goes roughly in the centre of the keep-in area; it is the
   anchor everything else clusters around.
4. LDO and power input parts: place toward the LEFT of the keep-in area, nearest
   the USB-C connector. Sensors: toward the RIGHT.
5. Decoupling capacitors: place 1.5–3 mm from the IC they serve (NOT inside its
   courtyard — the IC body occupies its full size_mm).
6. Pull-up resistors: place near (not under) the MCU.
7. Spread parts across the FULL width and length of the keep-in rectangle — do
   not cluster them in one corner and do not leave large empty regions. The goal
   is an even, compact, routable distribution like a real Feather board.
8. Orientation: ICs at 0°. Two-pin passives (R/C) may use 0° or 90°. Keep
   rotations sensible — no arbitrary angles.
9. NO OVERLAP — the most-violated rule. For EVERY pair of parts A and B:
   |xA − xB| ≥ (wA + wB)/2 + 0.5  OR  |yA − yB| ≥ (hA + hB)/2 + 0.5
   where [w, h] is each part's size_mm. Check every pair before answering.
10. Return every reference from the components list — do not omit any.

Return ONLY the JSON array.
"""
