#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# Authored By: Byron Jordan
# Power Supply Engineer
# Advanced Photon Source (APS)
# Argonne National Laboratory
# ---------------------------------------------------------------------------
"""Magnet load characterization helpers for the CDCU toolkit.

The load map carries the magnet nameplate resistance and inductance in the
load description.  This module converts those values into structured numbers
and compares them with values estimated from live CDCU measurements.

Steady-state resistance is estimated from V/I only when the current is large
enough to make the ratio useful.  Dynamic inductance is estimated from
V = R*I + L*dI/dt.  The inductance estimate is intentionally identified as an
estimate because live Ethernet polling is much slower than the CDCU PMM data
and the four monitor values are not sampled simultaneously.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class MagnetNameplate:
    """Structured magnet ratings recovered from one load-map entry."""
    resistance_ohm: Optional[float] = None
    inductance_h: Optional[float] = None


def _finite(value) -> bool:
    """Return True only when *value* can be represented as a finite float."""
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def parse_nameplate(load_entry: Optional[dict]) -> MagnetNameplate:
    """Read magnet R/L from explicit load-map fields or the legacy load_desc text.

    Future load maps may provide numeric fields directly.  Existing APS maps
    store the values in text such as ``Resistance: 0.064 Ohm; Inductance:
    16.9 mH``.  Explicit numeric fields take precedence when present.
    """
    entry = load_entry or {}

    r = entry.get("magnet_resistance_ohm", entry.get("resistance_ohm"))
    l_h = entry.get("magnet_inductance_h", entry.get("inductance_h"))
    l_mh = entry.get("magnet_inductance_mH", entry.get("inductance_mH"))

    resistance = float(r) if _finite(r) else None
    inductance = float(l_h) if _finite(l_h) else None
    if inductance is None and _finite(l_mh):
        inductance = float(l_mh) / 1000.0

    desc = str(entry.get("load_desc", "") or "")

    if resistance is None:
        match = re.search(r"Resistance\s*:\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*(?:Ohm|Ω)?", desc, re.I)
        if match:
            resistance = float(match.group(1))

    if inductance is None:
        match = re.search(r"Inductance\s*:\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*(mH|H)?", desc, re.I)
        if match:
            value = float(match.group(1))
            unit = (match.group(2) or "H").lower()
            inductance = value / 1000.0 if unit == "mh" else value

    return MagnetNameplate(resistance_ohm=resistance, inductance_h=inductance)


def measured_resistance(v_out_v: float, i_out_a: float, min_abs_current_a: float = 1.0) -> float:
    """Return the steady-state DC load resistance V/I in ohms."""
    if not (_finite(v_out_v) and _finite(i_out_a)):
        return math.nan
    if abs(float(i_out_a)) < float(min_abs_current_a):
        return math.nan
    return abs(float(v_out_v) / float(i_out_a))


def estimate_didt(previous_t_s: float, previous_i_a: float, current_t_s: float, current_i_a: float) -> float:
    """Estimate dI/dt from two consecutive live-monitor samples."""
    if not all(_finite(v) for v in (previous_t_s, previous_i_a, current_t_s, current_i_a)):
        return math.nan
    dt = float(current_t_s) - float(previous_t_s)
    if dt <= 0.0:
        return math.nan
    return (float(current_i_a) - float(previous_i_a)) / dt


def estimated_inductance(v_out_v: float, i_out_a: float, didt_a_per_s: float,
                         resistance_ohm: float, min_abs_didt_a_per_s: float = 1.0) -> float:
    """Estimate magnet inductance from L=(V-RI)/(dI/dt), returned in henries."""
    if not all(_finite(v) for v in (v_out_v, i_out_a, didt_a_per_s, resistance_ohm)):
        return math.nan
    if abs(float(didt_a_per_s)) < float(min_abs_didt_a_per_s):
        return math.nan
    return (float(v_out_v) - float(resistance_ohm) * float(i_out_a)) / float(didt_a_per_s)


def deviation(measured: float, reference: Optional[float]) -> Tuple[float, float, float]:
    """Return measured-reference as absolute value, percent, and ppm of reference."""
    if not _finite(measured) or reference is None or not _finite(reference) or float(reference) == 0.0:
        return math.nan, math.nan, math.nan
    delta = float(measured) - float(reference)
    pct = 100.0 * delta / abs(float(reference))
    ppm = 1.0e6 * delta / abs(float(reference))
    return delta, pct, ppm


def extrapolate_at_current(resistance_ohm: float, target_current_a: float) -> Tuple[float, float]:
    """Return predicted steady-state magnet voltage and I^2R power at target current."""
    if not (_finite(resistance_ohm) and _finite(target_current_a)):
        return math.nan, math.nan
    current = abs(float(target_current_a))
    resistance = abs(float(resistance_ohm))
    return current * resistance, current * current * resistance


def max_slew_rate(v_supply_max_v: float, target_current_a: float,
                  resistance_ohm: float, inductance_h: float) -> float:
    """Estimate positive dI/dt headroom at target current from (Vmax-I*R)/L."""
    if not all(_finite(v) for v in (v_supply_max_v, target_current_a, resistance_ohm, inductance_h)):
        return math.nan
    if float(inductance_h) <= 0.0:
        return math.nan
    headroom = float(v_supply_max_v) - abs(float(target_current_a)) * abs(float(resistance_ohm))
    return headroom / float(inductance_h)
