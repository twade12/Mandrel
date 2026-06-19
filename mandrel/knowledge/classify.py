"""Classify a netlist component into a coarse functional PartClass.

Used to retrieve the design rules relevant to the parts actually on a board.
Heuristic: reference-designator prefix + value + footprint + symbol name.
"""

from __future__ import annotations

import re

_VALUE_CAP_DECOUPLE = re.compile(r"^\s*(\d+(\.\d+)?)\s*(n|p)f", re.I)  # nF/pF → decoupling
_VALUE_CAP_BULK = re.compile(r"^\s*(\d+(\.\d+)?)\s*(u|µ|m)f", re.I)    # µF/mF → bulk


def classify(component: dict) -> str:
    """Return a PartClass string for a {ref, value, footprint} component dict."""
    ref = (component.get("ref") or "").upper()
    value = (component.get("value") or "")
    fp = (component.get("footprint") or "").upper()
    val_u = value.upper()

    prefix = re.match(r"^[A-Z]+", ref)
    p = prefix.group(0) if prefix else ""

    # Connectors / USB
    if "USB_C" in fp or "USB" in val_u:
        return "usb"
    if p in ("J", "P", "CN", "X") or "CONN" in fp:
        return "connector"

    # Crystals / oscillators
    if p in ("Y", "X") or "CRYSTAL" in fp or "XTAL" in val_u or "MHZ" in val_u or "KHZ" in val_u:
        return "crystal"

    # Capacitors: decoupling (nF/pF) vs bulk (µF+)
    if p == "C":
        if _VALUE_CAP_BULK.match(value):
            return "bulk_cap"
        return "decoupling_cap"

    # Resistors
    if p == "R":
        return "resistor"

    if p in ("L", "FB"):
        return "inductor"
    if p == "D":
        return "diode"
    if p in ("LED",) or "LED" in val_u:
        return "led"
    if p == "AE" or "ANTENNA" in fp:
        return "antenna"

    # ICs — refine by value/symbol
    if p == "U":
        if "RP2040" in val_u or "STM32" in val_u or "ATMEGA" in val_u or "ESP32" in val_u or "MCU" in val_u:
            return "mcu"
        if "MIC5219" in val_u or "LDO" in val_u or "AMS1117" in val_u or "REG" in val_u:
            return "ldo"
        if any(s in val_u for s in ("SHT", "BMP", "BME", "ICM", "MPU", "LIS", "SENSOR", "ADC")):
            return "sensor"
        return "ic"

    return "unknown"


def classify_all(components: list[dict]) -> list[str]:
    """Distinct sorted PartClasses present in a component list."""
    return sorted({classify(c) for c in components})
