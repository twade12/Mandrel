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

# ── S3 — ProductSpec → SKiDL Python schematic ─────────────────────────────────

S3_SKIDL_GEN = """\
You are an expert hardware design engineer. Write a complete, runnable SKiDL Python
script that implements the schematic described by the product specification below.

PRODUCT SPEC (JSON):
{spec_json}

FORM FACTOR: Adafruit Feather (50.8 mm × 22.86 mm, 3.3 V system)

REQUIRED CIRCUIT BLOCKS:
1. MCU — choose one appropriate to the spec (e.g. RP2040 for USB + general I/O)
2. 3.3 V LDO — powers the MCU and peripherals from USB 5 V (e.g. MIC5219-3.3YM5)
3. USB-C receptacle — for power + data (use CC resistors if MCU has native USB)
4. Peripheral ICs — one per function listed in spec["functions"], e.g.:
   - temperature/humidity → BME280 (I2C)
   - motion/IMU → ICM-42688-P (I2C/SPI)
5. Bypass/decoupling caps on every VDD pin (100 nF ceramic + 10 µF bulk where needed)
6. I2C pull-up resistors (4.7 kΩ to 3.3 V on SDA/SCL)

OUTPUT DIRECTORY: {output_dir}

SKIDL API REFERENCE:
```python
from skidl import *

# Load a part from KiCad symbol library
u1 = Part("MCU_RaspberryPi_RP2xxx", "RP2040",
          footprint="Package_DFN_QFN:QFN-56-1EP_7x7mm_P0.4mm_EP3.2x3.2mm")
r1 = Part("Device", "R", footprint="Resistor_SMD:R_0402_1005Metric", value="4.7k")
c1 = Part("Device", "C", footprint="Capacitor_SMD:C_0402_1005Metric", value="100nF")

# Define nets
vbus = Net("VBUS")    # USB 5 V input
v3v3 = Net("+3V3")   # regulated 3.3 V rail
gnd  = Net("GND")

# Connect pins
u1["VDD"] += v3v3
u1["GND"] += gnd
r1[1]     += v3v3   # pull-up one end
r1[2]     += i2c_sda

# At the END of your script, call both of these:
generate_schematic(filepath="{output_dir}/schematic.kicad_sch")
generate_netlist(filepath="{output_dir}/netlist.net")
ERC()  # run SKiDL's built-in ERC
```

KICAD SYMBOL LIBRARY NAMES (use exactly as shown):
- RP2040:        MCU_RaspberryPi_RP2xxx:RP2040
- MIC5219-3.3:   Regulator_Linear:MIC5219-3.3YM5
- BME280:        Sensor_Pressure:BME280
- ICM-42688-P:   Sensor_Motion:ICM-42688-P
- USB-C receptacle: Connector_USB:USB_C_Receptacle_USB2.0
- Generic R:     Device:R
- Generic C:     Device:C
- PWR_FLAG:      power:PWR_FLAG

RULES:
- Every net named +3V3 must connect to both the LDO output AND a PWR_FLAG.
- Every net named GND must connect to a PWR_FLAG.
- Add decoupling caps on all VDD/VDDIO pins.
- Do NOT hallucinate library names — use only the ones listed above.
- The last lines of the script MUST be the generate_schematic(), generate_netlist(),
  and ERC() calls shown above.
- Return ONLY the Python code, no markdown, no explanation.
"""
