#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# Authored By: Byron Jordan
# Power Supply Engineer
# Advanced Photon Source (APS)
# Argonne National Laboratory
# ---------------------------------------------------------------------------
"""
cdcu_ripple_bands.py

Shared spectral band definitions for CDCU ripple / FFT / PSD analysis.

All analysis modules import ANALYSIS_BANDS and BAND_STR from here so
band definitions live in exactly one place.

Bands
-----
  1 -  10 Hz   : low-frequency / mechanical / thermal coupling
 60 - 120 Hz   : fundamental line frequency + first harmonic
360 - 720 Hz   : higher-order line/switching content
720 - 1200 Hz  : standard high-frequency band containing 1 kHz
"""

from __future__ import annotations
from typing import List, Tuple

# ---------------------------------------------------------------------------
# Band definitions
# ---------------------------------------------------------------------------
# Each entry: (f_low_hz, f_high_hz, label)
ANALYSIS_BANDS: List[Tuple[float, float, str]] = [
    (1.0,   10.0,  "1-10 Hz"),
    (60.0,  120.0, "60-120 Hz"),
    (360.0, 720.0,  "360-720 Hz"),
    (720.0, 1200.0, "720-1200 Hz"),
]

# Compact string form accepted by ripple_psd.parse_bands()
# Format: "lo-hi:label, lo-hi:label, ..."
BAND_STR: str = "1-10:1-10 Hz,60-120:60-120 Hz,360-720:360-720 Hz,720-1200:720-1200 Hz"

# ---------------------------------------------------------------------------
# Column definitions for MGPC / cdcu_monitor CSV
# ---------------------------------------------------------------------------
# Maps a friendly analysis key → CSV column name produced by cdcu_monitor.py
CDCU_SIGNAL_COLS = {
    "MRP_float":  ("MRP_float",   "V",   "MRP – DC Bus Voltage"),
    "MGPC_float": ("MGPC_float",  "A",   "MGPC – Input Current"),
    "MRV_float":  ("MRV_float",   "V",   "MRV – Output Voltage"),
    "MRI_float":  ("MRI_float",   "A",   "MRI – Output Current"),
    "Pin_W":      ("Pin_W",       "W",   "Pin – Input Power"),
    "Pout_W":     ("Pout_W",      "W",   "Pout – Output Power"),
}

# Time column written by cdcu_monitor.py
TIME_COL = "burst_midpoint_s"
