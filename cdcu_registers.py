#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# Authored By: Byron Jordan
# Power Supply Engineer
# Advanced Photon Source (APS)
# Argonne National Laboratory
# ---------------------------------------------------------------------------
"""
cdcu_registers.py

CDCU fault register (MFTR), status register (MSTR), and warning register
(MWRR) decoders based on the CAEN ELS CDCU Remote Control Manual Rev 1.3.

Provides human-readable decode of the 32-bit hex registers returned by:
    MFTR:?  ->  #MFTR:00000010
    MSTR:?  ->  #MSTR:00000012
    MWRR:?  ->  #MWRR:00000001

Usage
-----
    from cdcu_registers import decode_mftr, decode_mstr, decode_mwrr, active_bits

    faults  = decode_mftr("00000010")
    status  = decode_mstr("00000012")
    warnings = decode_mwrr("00000001")

    # faults["active_names"] -> list of fault names with set bits
    # status["power_state"]  -> "ON" / "OFF" / "WAIT_FOR_OFF"
    # status["loop_mode"]    -> "CC" (current) or "CV" (voltage)
"""

from __future__ import annotations
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# MFTR — Fault Register  (Table 6, Section 4.7.1)
# ---------------------------------------------------------------------------

_MFTR_BITS: Dict[int, str] = {
    0:  "Buck 1 Over-Current",
    1:  "Buck 2 Over-Current",
    2:  "Buck 3 Over-Current",
    3:  "Output Over-Current",
    4:  "DC-Bus Fault",
    5:  "DC-Bus Hardware Fault",
    6:  "Input Over-Current",
    7:  "Input HW Over-Current",
    8:  "Over-Power",
    9:  "Buck Over-Temperature",
    10: "Cap. Bank Over-Temperature",
    11: "Regulation Fault",
    12: "Hardware Fault",
    13: "DCCT Fault",
    14: "Cable Connection Fault",
    15: "Reserved",
    16: "External Magnet Temperature",
    17: "External Interlock 2",
    18: "External Interlock 3",
    19: "Buck Inductor Over-Temperature",
}


def decode_mftr(hex_str: str) -> Dict:
    """
    Decode MFTR hex register string (e.g. '00000010') into a dict:
        {
          "raw_hex":      "00000010",
          "value":        16,
          "active_bits":  [4],
          "active_names": ["DC-Bus Fault"],
          "is_faulted":   True,
        }
    """
    # Capture hex_str here; the next step uses this intermediate result directly.
    hex_str = _strip_prefix(hex_str, "#MFTR:")
    # Protect this hardware or file operation so a failure is reported without obscuring where it happened.
    try:
        # Capture value here; the next step uses this intermediate result directly.
        value = int(hex_str.strip(), 16)
    except ValueError:
        # Hand the finished value back to the caller.
        return {"raw_hex": hex_str, "value": None, "active_bits": [],
                "active_names": ["PARSE ERROR"], "is_faulted": False}

    # Capture active_bits here; the next step uses this intermediate result directly.
    active_bits  = [b for b in _MFTR_BITS if value & (1 << b)]
    # Capture active_names here; the next step uses this intermediate result directly.
    active_names = [_MFTR_BITS[b] for b in active_bits]

    # Hand the finished value back to the caller.
    return {
        "raw_hex":      hex_str.strip(),
        "value":        value,
        "active_bits":  active_bits,
        "active_names": active_names,
        "is_faulted":   bool(active_bits),
    }


# ---------------------------------------------------------------------------
# MSTR — Status Register  (Table 5, Section 4.7.1)
# ---------------------------------------------------------------------------

_POWER_STATE = {0b00: "OFF", 0b01: "ON", 0b11: "WAIT_FOR_OFF"}


def decode_mstr(hex_str: str) -> Dict:
    """
    Decode MSTR hex register string (e.g. '00000012') into a dict:
        {
          "raw_hex":        "00000012",
          "value":          18,
          "power_state":    "ON",          # bits [1:0]
          "is_faulted":     False,         # bit [2]
          "has_warning":    False,         # bit [3]
          "loop_mode":      "CV",          # bit [4]  0=CC, 1=CV
          "is_local":       False,         # bit [6]
          "setpoint_mode":  "NORMAL",      # bit [9]  0=NORMAL, 1=WAVEFORM
        }
    """
    # Capture hex_str here; the next step uses this intermediate result directly.
    hex_str = _strip_prefix(hex_str, "#MSTR:")
    # Protect this hardware or file operation so a failure is reported without obscuring where it happened.
    try:
        # Capture value here; the next step uses this intermediate result directly.
        value = int(hex_str.strip(), 16)
    except ValueError:
        # Hand the finished value back to the caller.
        return {"raw_hex": hex_str, "value": None, "power_state": "UNKNOWN"}

    # Capture ps_bits here; the next step uses this intermediate result directly.
    ps_bits = value & 0b11
    # Capture power_state here; the next step uses this intermediate result directly.
    power_state = _POWER_STATE.get(ps_bits, f"RESERVED({ps_bits:02b})")

    # Hand the finished value back to the caller.
    return {
        "raw_hex":       hex_str.strip(),
        "value":         value,
        "power_state":   power_state,
        "is_faulted":    bool(value & (1 << 2)),
        "has_warning":   bool(value & (1 << 3)),
        "loop_mode":     "CV" if (value & (1 << 4)) else "CC",
        "is_local":      bool(value & (1 << 6)),
        "setpoint_mode": "WAVEFORM" if (value & (1 << 9)) else "NORMAL",
    }


# ---------------------------------------------------------------------------
# MWRR — Warning Register  (Table 7, Section 4.7.2)
# ---------------------------------------------------------------------------

_MWRR_BITS: Dict[int, str] = {
    0: "Water Leakage Warning",
}


def decode_mwrr(hex_str: str) -> Dict:
    """
    Decode MWRR hex register string (e.g. '00000001') into a dict:
        {
          "raw_hex":      "00000001",
          "value":        1,
          "active_bits":  [0],
          "active_names": ["Water Leakage Warning"],
          "has_warning":  True,
        }
    """
    # Capture hex_str here; the next step uses this intermediate result directly.
    hex_str = _strip_prefix(hex_str, "#MWRR:")
    # Protect this hardware or file operation so a failure is reported without obscuring where it happened.
    try:
        # Capture value here; the next step uses this intermediate result directly.
        value = int(hex_str.strip(), 16)
    except ValueError:
        # Hand the finished value back to the caller.
        return {"raw_hex": hex_str, "value": None, "active_bits": [],
                "active_names": ["PARSE ERROR"], "has_warning": False}

    # Capture active_bits here; the next step uses this intermediate result directly.
    active_bits  = [b for b in _MWRR_BITS if value & (1 << b)]
    # Capture active_names here; the next step uses this intermediate result directly.
    active_names = [_MWRR_BITS[b] for b in active_bits] or []

    # Hand the finished value back to the caller.
    return {
        "raw_hex":      hex_str.strip(),
        "value":        value,
        "active_bits":  active_bits,
        "active_names": active_names,
        "has_warning":  bool(active_bits),
    }


# ---------------------------------------------------------------------------
# Convenience: pretty-print summary
# ---------------------------------------------------------------------------

def fault_summary(mftr_hex: str, mstr_hex: str = "", mwrr_hex: str = "") -> str:
    """
    Return a compact multi-line summary string for logging / PDF headers.

        MFTR: 00000010  →  DC-Bus Fault
        MSTR: 00000012  →  ON | CC | NORMAL
        MWRR: 00000000  →  No warnings
    """
    # Carry out this step before advancing to the next part of the function.
    lines: List[str] = []

    # Capture f here; the next step uses this intermediate result directly.
    f = decode_mftr(mftr_hex)
    # Take this branch only when the stated operating condition is true.
    if f["active_names"]:
        # Add this observation to the ordered history so the sequence is preserved.
        lines.append(f"MFTR: {f['raw_hex']}  →  " + "; ".join(f["active_names"]))
    else:
        # Add this observation to the ordered history so the sequence is preserved.
        lines.append(f"MFTR: {f['raw_hex']}  →  No faults")

    # Take this branch only when the stated operating condition is true.
    if mstr_hex:
        # Capture s here; the next step uses this intermediate result directly.
        s = decode_mstr(mstr_hex)
        # Add this observation to the ordered history so the sequence is preserved.
        lines.append(
            f"MSTR: {s['raw_hex']}  →  "
            f"{s['power_state']} | {s['loop_mode']} | {s['setpoint_mode']}"
        )

    # Take this branch only when the stated operating condition is true.
    if mwrr_hex:
        # Capture w here; the next step uses this intermediate result directly.
        w = decode_mwrr(mwrr_hex)
        # Take this branch only when the stated operating condition is true.
        if w["active_names"]:
            # Add this observation to the ordered history so the sequence is preserved.
            lines.append(f"MWRR: {w['raw_hex']}  →  " + "; ".join(w["active_names"]))
        else:
            # Add this observation to the ordered history so the sequence is preserved.
            lines.append(f"MWRR: {w['raw_hex']}  →  No warnings")

    # Hand the finished value back to the caller.
    return "\n".join(lines)


def active_bits(hex_str: str) -> List[int]:
    """Return list of set bit positions in a hex register string."""
    # Protect this hardware or file operation so a failure is reported without obscuring where it happened.
    try:
        # Capture v here; the next step uses this intermediate result directly.
        v = int(_strip_prefix(hex_str).strip(), 16)
        # Hand the finished value back to the caller.
        return [i for i in range(32) if v & (1 << i)]
    except ValueError:
        # Hand the finished value back to the caller.
        return []


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _strip_prefix(s: str, prefix: str = "") -> str:
    """Strip a leading '#XXX:' echo prefix if present."""
    # Capture s here; the next step uses this intermediate result directly.
    s = s.strip()
    # Take this branch only when the stated operating condition is true.
    if prefix and s.upper().startswith(prefix.upper()):
        # Hand the finished value back to the caller.
        return s[len(prefix):]
    # Generic: strip any leading '#WORD:' pattern
    # Take this branch only when the stated operating condition is true.
    if s.startswith("#") and ":" in s:
        # Hand the finished value back to the caller.
        return s.split(":", 1)[1]
    # Hand the finished value back to the caller.
    return s


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli() -> None:
    # Import this dependency locally because it is only needed on this execution path.
    import argparse
    # Capture ap here; the next step uses this intermediate result directly.
    ap = argparse.ArgumentParser(
        description="Decode CDCU MFTR/MSTR/MWRR register hex strings."
    )
    # Carry out this step before advancing to the next part of the function.
    ap.add_argument("--mftr", default="", help="MFTR hex e.g. 00000010")
    # Carry out this step before advancing to the next part of the function.
    ap.add_argument("--mstr", default="", help="MSTR hex e.g. 00000012")
    # Carry out this step before advancing to the next part of the function.
    ap.add_argument("--mwrr", default="", help="MWRR hex e.g. 00000001")
    # Parse the command-line settings supplied by the operator.
    args = ap.parse_args()

    # Take this branch only when the stated operating condition is true.
    if not any([args.mftr, args.mstr, args.mwrr]):
        # Demo
        # Write this status to the console so the operator can follow the run in real time.
        print("Demo decode:\n")
        # Write this status to the console so the operator can follow the run in real time.
        print(fault_summary("00000010", "00000012", "00000001"))
        # Write this status to the console so the operator can follow the run in real time.
        print()
        # Import this dependency locally because it is only needed on this execution path.
        import json
        # Write this status to the console so the operator can follow the run in real time.
        print("MFTR detail:", json.dumps(decode_mftr("00000010"), indent=2))
        # Write this status to the console so the operator can follow the run in real time.
        print("MSTR detail:", json.dumps(decode_mstr("00000012"), indent=2))
        # Write this status to the console so the operator can follow the run in real time.
        print("MWRR detail:", json.dumps(decode_mwrr("00000001"), indent=2))
        # Return to the caller; there is no additional value to pass back.
        return

    # Write this status to the console so the operator can follow the run in real time.
    print(fault_summary(
        args.mftr or "00000000",
        args.mstr,
        args.mwrr,
    ))


if __name__ == "__main__":
    _cli()
