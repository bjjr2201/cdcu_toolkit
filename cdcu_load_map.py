#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# Authored By: Byron Jordan
# Power Supply Engineer
# Advanced Photon Source (APS)
# Argonne National Laboratory
# ---------------------------------------------------------------------------
"""
cdcu_load_map.py

Load map resolver for the CDCU tool-chain.

Reads load_map_with_magnetid.json and resolves a (cabinet, ip, sector) tuple
to a fully-substituted metadata dict for use in cdcu_monitor.py and the
ripple analysis pipeline.

JSON schema (load_map_with_magnetid.json):
{
  "Cab_1": {
    "192.168.3.2": {
      "dcbus_ref_V":  "40",       <- expected DC bus voltage (V)
      "idc_ref_A":    "",         <- rated DC output current (A), if known
      "load_desc":    "Magnet: {SECTOR}BQ1; ...",
      "magnet_id":    "{SECTOR}:BQ1",
      "raw_V":        "40",       <- raw bus voltage
      "v_out_rating": "45",       <- rated output voltage (V)
      "vout_ref_V":   ""          <- set-point output voltage, if known
    },
    ...
  },
  ...
}

The {SECTOR} placeholder is substituted with the sector string you pass
at runtime (e.g. "S01", "L1127", "P01", etc.).

Usage
-----
    from cdcu_load_map import CdcuLoadMap

    lm = CdcuLoadMap("load_map_with_magnetid.json")
    entry = lm.lookup("Cab_1", "192.168.3.2", sector="S01")
    # entry["load_desc"]   -> "Magnet: S01BQ1; DMM_Q1; ..."
    # entry["magnet_id"]   -> "S01:BQ1"
    # entry["raw_V"]       -> 40.0
    # entry["v_out_rating"]-> 45.0
    # entry["dcbus_ref_V"] -> 40.0  (or None if blank)
    # entry["idc_ref_A"]   -> None  (blank in JSON)
    # entry["vout_ref_V"]  -> None  (blank in JSON)

    # List helpers
    lm.list_cabinets()            -> ["Cab_1", "Cab_2", ...]
    lm.list_ips("Cab_1")          -> ["192.168.1.2", ...]
    lm.find_by_ip("192.168.3.2")  -> [(cabinet, ip, entry), ...]  across all cabs
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------
LoadEntry = Dict[str, Any]


class CdcuLoadMap:
    """
    Wraps load_map_with_magnetid.json with lookup, substitution, and
    helper methods for use across the CDCU tool-chain.
    """

    # Fields that should be coerced to float (empty string → None)
    _FLOAT_FIELDS = ("dcbus_ref_V", "idc_ref_A", "raw_V", "v_out_rating", "vout_ref_V")

    def __init__(self, json_path: str) -> None:
        # Take this branch only when the stated operating condition is true.
        if not os.path.isfile(json_path):
            # Raise a specific error instead of allowing bad input to propagate into the analysis.
            raise FileNotFoundError(f"Load map not found: {json_path}")
        # Use a context manager so the file or resource is closed cleanly on every exit path.
        with open(json_path, "r", encoding="utf-8") as fh:
            # Carry out this step before advancing to the next part of the function.
            self._data: Dict[str, Dict[str, Dict[str, str]]] = json.load(fh)
        # Carry out this step before advancing to the next part of the function.
        self._path = json_path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def lookup(
        self,
        cabinet: str,
        ip: str,
        sector: str = "",
    ) -> LoadEntry:
        """
        Return a fully-resolved metadata dict for (cabinet, ip).

        All '{SECTOR}' placeholders in string fields are replaced with *sector*.
        Numeric fields are coerced to float; blank strings become None.

        Raises KeyError if cabinet or IP is not found.
        """
        # Initialize cab_data as the working collection for this part of the run.
        cab_data = self._data.get(cabinet)
        # Take this branch only when the stated operating condition is true.
        if cab_data is None:
            # Capture available here; the next step uses this intermediate result directly.
            available = list(self._data.keys())
            # Raise a specific error instead of allowing bad input to propagate into the analysis.
            raise KeyError(
                f"Cabinet '{cabinet}' not found in load map.\n"
                f"Available: {available}"
            )
        # Capture raw_entry here; the next step uses this intermediate result directly.
        raw_entry = cab_data.get(ip)
        # Take this branch only when the stated operating condition is true.
        if raw_entry is None:
            # Capture available here; the next step uses this intermediate result directly.
            available = list(cab_data.keys())
            # Raise a specific error instead of allowing bad input to propagate into the analysis.
            raise KeyError(
                f"IP '{ip}' not found in cabinet '{cabinet}'.\n"
                f"Available IPs: {available}"
            )

        # Hand the finished value back to the caller.
        return self._resolve(raw_entry, sector)

    def lookup_soft(
        self,
        cabinet: str,
        ip: str,
        sector: str = "",
    ) -> Optional[LoadEntry]:
        """
        Like lookup() but returns None instead of raising KeyError when the
        cabinet/IP combination is absent.  Safe to use when the IP may not
        be in the map yet.
        """
        # Protect this hardware or file operation so a failure is reported without obscuring where it happened.
        try:
            # Hand the finished value back to the caller.
            return self.lookup(cabinet, ip, sector)
        except KeyError:
            # Hand the finished value back to the caller.
            return None

    def list_cabinets(self) -> List[str]:
        """Return all cabinet names in the load map."""
        # Hand the finished value back to the caller.
        return list(self._data.keys())

    def list_ips(self, cabinet: str) -> List[str]:
        """Return all IPs registered under *cabinet*."""
        # Initialize cab_data as the working collection for this part of the run.
        cab_data = self._data.get(cabinet, {})
        # Hand the finished value back to the caller.
        return list(cab_data.keys())

    def find_by_ip(
        self,
        ip: str,
        sector: str = "",
    ) -> List[Tuple[str, str, LoadEntry]]:
        """
        Search all cabinets for *ip*.  Returns a list of
        (cabinet, ip, resolved_entry) tuples — there may be multiple
        matches because the same IP subnet is reused per cabinet.
        """
        # Carry out this step before advancing to the next part of the function.
        results: List[Tuple[str, str, LoadEntry]] = []
        # Walk the collection in order so every item receives the same treatment.
        for cab, ips in self._data.items():
            # Take this branch only when the stated operating condition is true.
            if ip in ips:
                # Add this observation to the ordered history so the sequence is preserved.
                results.append((cab, ip, self._resolve(ips[ip], sector)))
        # Hand the finished value back to the caller.
        return results

    def all_entries(
        self, sector: str = ""
    ) -> List[Tuple[str, str, LoadEntry]]:
        """
        Iterate over every (cabinet, ip, resolved_entry) in the map.
        Useful for bulk operations.
        """
        # Carry out this step before advancing to the next part of the function.
        out: List[Tuple[str, str, LoadEntry]] = []
        # Walk the collection in order so every item receives the same treatment.
        for cab, ips in self._data.items():
            # Walk the collection in order so every item receives the same treatment.
            for ip, raw in ips.items():
                # Add this observation to the ordered history so the sequence is preserved.
                out.append((cab, ip, self._resolve(raw, sector)))
        # Hand the finished value back to the caller.
        return out

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve(self, raw: Dict[str, str], sector: str) -> LoadEntry:
        """Apply {SECTOR} substitution and numeric coercion to a raw entry."""
        # Carry out this step before advancing to the next part of the function.
        entry: LoadEntry = {}
        # Walk the collection in order so every item receives the same treatment.
        for k, v in raw.items():
            # Take this branch only when the stated operating condition is true.
            if isinstance(v, str):
                # Substitute sector placeholder
                # Capture v_sub here; the next step uses this intermediate result directly.
                v_sub = v.replace("{SECTOR}", sector)
                # Coerce numeric fields
                # Take this branch only when the stated operating condition is true.
                if k in self._FLOAT_FIELDS:
                    # Capture entry[k] here; the next step uses this intermediate result directly.
                    entry[k] = _to_float_or_none(v_sub)
                else:
                    # Capture entry[k] here; the next step uses this intermediate result directly.
                    entry[k] = v_sub
            else:
                # Capture entry[k] here; the next step uses this intermediate result directly.
                entry[k] = v
        # Hand the finished value back to the caller.
        return entry


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------

def _to_float_or_none(s: str) -> Optional[float]:
    """Return float(s) or None if s is empty / non-numeric."""
    # Capture s here; the next step uses this intermediate result directly.
    s = s.strip()
    # Take this branch only when the stated operating condition is true.
    if not s:
        # Hand the finished value back to the caller.
        return None
    # Protect this hardware or file operation so a failure is reported without obscuring where it happened.
    try:
        # Hand the finished value back to the caller.
        return float(s)
    except ValueError:
        # Hand the finished value back to the caller.
        return None


def load_map_from_env_or_default(
    env_var: str = "CDCU_LOAD_MAP",
    default_path: str = "load_map_with_magnetid.json",
) -> Optional["CdcuLoadMap"]:
    """
    Convenience loader used by cdcu_monitor.py.

    Checks the environment variable *env_var* first, then falls back to
    *default_path* in the current working directory.  Returns None (with a
    warning) if neither path exists, so the monitor can still run without
    a load map.
    """
    # Resolve path once so later file operations use the same location.
    path = os.environ.get(env_var, default_path)
    # Take this branch only when the stated operating condition is true.
    if os.path.isfile(path):
        # Protect this hardware or file operation so a failure is reported without obscuring where it happened.
        try:
            # Capture lm here; the next step uses this intermediate result directly.
            lm = CdcuLoadMap(path)
            # Write this status to the console so the operator can follow the run in real time.
            print(f"[cdcu_load_map] Loaded: {path}")
            # Hand the finished value back to the caller.
            return lm
        except Exception as exc:
            # Write this status to the console so the operator can follow the run in real time.
            print(f"[cdcu_load_map] WARNING: Could not load '{path}': {exc}")
            # Hand the finished value back to the caller.
            return None
    else:
        # Write this status to the console so the operator can follow the run in real time.
        print(
            f"[cdcu_load_map] Load map not found at '{path}'. "
            f"Running without load metadata. "
            f"Set {env_var}=<path> or place load_map_with_magnetid.json in the "
            f"working directory to enable auto-population."
        )
        # Hand the finished value back to the caller.
        return None


# ---------------------------------------------------------------------------
# CLI helper  (python cdcu_load_map.py --cabinet Cab_1 --ip 192.168.3.2 --sector S01)
# ---------------------------------------------------------------------------

def _cli() -> None:
    # Import this dependency locally because it is only needed on this execution path.
    import argparse

    # Capture ap here; the next step uses this intermediate result directly.
    ap = argparse.ArgumentParser(
        description="Query the CDCU load map from the command line."
    )
    # Carry out this step before advancing to the next part of the function.
    ap.add_argument("--map", default="load_map_with_magnetid.json",
                    help="Path to load_map_with_magnetid.json")
    # Carry out this step before advancing to the next part of the function.
    ap.add_argument("--cabinet", default=None, help="Cabinet name (e.g. Cab_1)")
    # Carry out this step before advancing to the next part of the function.
    ap.add_argument("--ip",      default=None, help="IP address (e.g. 192.168.3.2)")
    # Carry out this step before advancing to the next part of the function.
    ap.add_argument("--sector",  default="",   help="Sector string to substitute for {SECTOR}")
    # Carry out this step before advancing to the next part of the function.
    ap.add_argument("--list",    action="store_true", help="List all cabinets and IPs")
    # Parse the command-line settings supplied by the operator.
    args = ap.parse_args()

    # Capture lm here; the next step uses this intermediate result directly.
    lm = CdcuLoadMap(args.map)

    # Take this branch only when the stated operating condition is true.
    if args.list:
        # Walk the collection in order so every item receives the same treatment.
        for cab in lm.list_cabinets():
            # Write this status to the console so the operator can follow the run in real time.
            print(f"\n{cab}:")
            # Walk the collection in order so every item receives the same treatment.
            for ip in lm.list_ips(cab):
                # Capture entry here; the next step uses this intermediate result directly.
                entry = lm.lookup(cab, ip, args.sector)
                # Write this status to the console so the operator can follow the run in real time.
                print(f"  {ip}  |  {entry.get('magnet_id','')}  |  {entry.get('load_desc','')}")
        # Return to the caller; there is no additional value to pass back.
        return

    # Take this branch only when the stated operating condition is true.
    if args.cabinet and args.ip:
        # Capture entry here; the next step uses this intermediate result directly.
        entry = lm.lookup(args.cabinet, args.ip, args.sector)
        # Write this status to the console so the operator can follow the run in real time.
        print(f"\nResolved entry for {args.cabinet} / {args.ip} (sector='{args.sector}'):")
        # Walk the collection in order so every item receives the same treatment.
        for k, v in entry.items():
            # Write this status to the console so the operator can follow the run in real time.
            print(f"  {k:20s}: {v}")
        # Return to the caller; there is no additional value to pass back.
        return

    # Take this branch only when the stated operating condition is true.
    if args.ip and not args.cabinet:
        # Start a clean result container for this analysis pass.
        results = lm.find_by_ip(args.ip, args.sector)
        # Take this branch only when the stated operating condition is true.
        if not results:
            # Write this status to the console so the operator can follow the run in real time.
            print(f"IP {args.ip} not found in any cabinet.")
        # Walk the collection in order so every item receives the same treatment.
        for cab, ip, entry in results:
            # Write this status to the console so the operator can follow the run in real time.
            print(f"\nFound in {cab} / {ip}:")
            # Walk the collection in order so every item receives the same treatment.
            for k, v in entry.items():
                # Write this status to the console so the operator can follow the run in real time.
                print(f"  {k:20s}: {v}")
        # Return to the caller; there is no additional value to pass back.
        return

    # Carry out this step before advancing to the next part of the function.
    ap.print_help()


if __name__ == "__main__":
    _cli()
