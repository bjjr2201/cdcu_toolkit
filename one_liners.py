#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# Authored By: Byron Jordan
# Power Supply Engineer
# Advanced Photon Source (APS)
# Argonne National Laboratory
# ---------------------------------------------------------------------------
"""
one_liners.py

Launch cdcu_monitor.py for every reachable supply in a cabinet simultaneously.
Each supply runs in its own subprocess so crashes and timeouts are fully isolated.

Usage
-----
    # All reachable supplies in Test_1, sector B400A, 120 s:
    python one_liners.py --cabinet Test_1 --sector B400A

    # Specific IPs only:
    python one_liners.py --cabinet Test_1 --sector B400A \
        --ips 192.168.1.2 192.168.7.2

    # Custom duration and output directory:
    python one_liners.py --cabinet Cab_1 --sector S01 \
        --duration 300 --outdir /data/runs/S01_2025-08-01

    # Skip post-run ripple analysis (faster turnaround):
    python one_liners.py --cabinet Test_1 --sector B400A --no-analysis

    # Dry run - show what would be launched without connecting:
    python one_liners.py --cabinet Test_1 --sector B400A --dry-run

    # List all cabinets and their IPs then exit:
    python one_liners.py --list

Reachability
------------
Each IP is probed with a short TCP connect before launching.  Supplies that
do not respond within PROBE_TIMEOUT seconds are skipped with a clear warning;
no subprocess is spawned, no CSV is created, and the run continues for the
remaining supplies.

Output layout
-------------
    <outdir>/
        cdcu_192_168_1_2.csv
        cdcu_192_168_1_2_live.png
        cdcu_192_168_1_2_stdout.log
        cdcu_192_168_7_2.csv
        ...

Dependencies
------------
    cdcu_monitor.py              (must be in the same directory)
    cdcu_load_map.py
    load_map_with_magnetid.json
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PORT           = 10001   # CDCU TCP port
PROBE_TIMEOUT  = 2.0     # seconds — TCP connect probe before launching subprocess
LAUNCH_STAGGER = 0.15    # seconds between consecutive process launches

_HERE          = os.path.dirname(os.path.abspath(__file__))
MONITOR_SCRIPT = os.path.join(_HERE, "cdcu_monitor.py")
LOAD_MAP_FILE  = os.path.join(_HERE, "load_map_with_magnetid.json")

def _format_runtime(seconds: float) -> str:
    """Return elapsed time in seconds and HH:MM:SS.s form."""
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60.0
    return f"{seconds:.3f} s ({hours:02d}:{minutes:02d}:{secs:04.1f})"


# ---------------------------------------------------------------------------
# Reachability probe
# ---------------------------------------------------------------------------

def probe_ip(ip: str, port: int = PORT, timeout: float = PROBE_TIMEOUT) -> bool:
    """
    Return True if a TCP connection to ip:port succeeds within *timeout* s.
    Confirms the CDCU unit is powered and network-accessible before we
    commit a subprocess and CSV file to it.
    """
    # Protect this hardware or file operation so a failure is reported without obscuring where it happened.
    try:
        # Use a context manager so the file or resource is closed cleanly on every exit path.
        with socket.create_connection((ip, port), timeout=timeout):
            # Hand the finished value back to the caller.
            return True
    except (OSError, socket.timeout):
        # Hand the finished value back to the caller.
        return False


# ---------------------------------------------------------------------------
# Cabinet IP resolution
# ---------------------------------------------------------------------------

def resolve_ips(
    cabinet: str,
    sector: str,
    load_map_file: str,
    requested_ips: Optional[List[str]] = None,
) -> List[Tuple[str, dict]]:
    """
    Return a list of (ip, load_entry) tuples for the cabinet.

    If *requested_ips* is given, only those IPs are returned (still looked
    up in the load map for metadata).  Otherwise all IPs in the cabinet are
    returned.
    """
    # Protect this hardware or file operation so a failure is reported without obscuring where it happened.
    try:
        # Import this dependency locally because it is only needed on this execution path.
        from cdcu_load_map import CdcuLoadMap
    except ImportError:
        # Write this status to the console so the operator can follow the run in real time.
        print("[one_liners] ERROR: cdcu_load_map.py not found.", file=sys.stderr)
        # Carry out this step before advancing to the next part of the function.
        sys.exit(1)

    # Do not judge full-load performance until the load is high enough to make that comparison meaningful.
    if not os.path.isfile(load_map_file):
        # Write this status to the console so the operator can follow the run in real time.
        print(f"[one_liners] ERROR: Load map not found: {load_map_file}", file=sys.stderr)
        # Carry out this step before advancing to the next part of the function.
        sys.exit(1)

    # Capture lm here; the next step uses this intermediate result directly.
    lm = CdcuLoadMap(load_map_file)

    # Capture available_cabinets here; the next step uses this intermediate result directly.
    available_cabinets = lm.list_cabinets()
    # Take this branch only when the stated operating condition is true.
    if cabinet not in available_cabinets:
        # Write this status to the console so the operator can follow the run in real time.
        print(f"[one_liners] ERROR: Cabinet '{cabinet}' not in load map.", file=sys.stderr)
        # Write this status to the console so the operator can follow the run in real time.
        print(f"  Available: {available_cabinets}", file=sys.stderr)
        # Carry out this step before advancing to the next part of the function.
        sys.exit(1)

    # Capture all_ips here; the next step uses this intermediate result directly.
    all_ips = lm.list_ips(cabinet)

    # Take this branch only when the stated operating condition is true.
    if requested_ips:
        # Capture unknown here; the next step uses this intermediate result directly.
        unknown = [ip for ip in requested_ips if ip not in all_ips]
        # Take this branch only when the stated operating condition is true.
        if unknown:
            # Write this status to the console so the operator can follow the run in real time.
            print(f"[one_liners] WARNING: IPs not registered under "
                  f"'{cabinet}', will be skipped: {unknown}")
        # Capture target_ips here; the next step uses this intermediate result directly.
        target_ips = [ip for ip in requested_ips if ip in all_ips]
    else:
        # Capture target_ips here; the next step uses this intermediate result directly.
        target_ips = all_ips

    # Hand the finished value back to the caller.
    return [(ip, lm.lookup_soft(cabinet, ip, sector=sector) or {})
            for ip in target_ips]


# ---------------------------------------------------------------------------
# Subprocess command builder
# ---------------------------------------------------------------------------

def build_command(
    ip: str,
    cabinet: str,
    sector: str,
    duration: float,
    interval: float,
    outdir: str,
    no_analysis: bool,
) -> List[str]:
    """Build the argv list for one cdcu_monitor.py invocation."""
    # Capture cmd here; the next step uses this intermediate result directly.
    cmd = [
        sys.executable, MONITOR_SCRIPT,
        "--host",     ip,
        "--cabinet",  cabinet,
        "--sector",   sector,
        "--duration", str(duration),
        "--interval", str(interval),
        "--outdir",   outdir,
        "--no-plot",               # always headless when launched by one_liners
    ]
    # Take this branch only when the stated operating condition is true.
    if no_analysis:
        # Add this observation to the ordered history so the sequence is preserved.
        cmd.append("--no-analysis")
    # Hand the finished value back to the caller.
    return cmd


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    _program_start_mono = time.perf_counter()
    _program_start_local = datetime.now()
    # Capture ap here; the next step uses this intermediate result directly.
    ap = argparse.ArgumentParser(
        description="Run cdcu_monitor.py for every reachable supply in a cabinet.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    # Carry out this step before advancing to the next part of the function.
    ap.add_argument("--cabinet",  default=None,          metavar="NAME",
                    help="Cabinet name in load map (e.g. Cab_1, Test_1, E-Lab)")
    # Carry out this step before advancing to the next part of the function.
    ap.add_argument("--sector",   default="",            metavar="STR",
                    help="Sector string substituted for {SECTOR} (e.g. S01, B400A)")
    # Carry out this step before advancing to the next part of the function.
    ap.add_argument("--ips",      nargs="+",             metavar="IP", default=None,
                    help="Restrict to specific IPs (default: all IPs in cabinet)")
    # Carry out this step before advancing to the next part of the function.
    ap.add_argument("--duration", default=120.0,         type=float, metavar="SEC",
                    help="Logging duration per supply in seconds")
    # Carry out this step before advancing to the next part of the function.
    ap.add_argument("--interval", default=0.40,          type=float, metavar="SEC",
                    help="Polling interval per supply in seconds")
    # Carry out this step before advancing to the next part of the function.
    ap.add_argument("--outdir",   default=".",           metavar="DIR",
                    help="Root output directory for all CSV and PNG files")
    # Carry out this step before advancing to the next part of the function.
    ap.add_argument("--no-analysis", action="store_true",
                    help="Skip post-run ripple/FFT/PSD analysis")
    # Carry out this step before advancing to the next part of the function.
    ap.add_argument("--probe-timeout", default=PROBE_TIMEOUT, type=float,
                    metavar="SEC",
                    help="TCP probe timeout before skipping an IP")
    # Carry out this step before advancing to the next part of the function.
    ap.add_argument("--list",     action="store_true",
                    help="List all cabinets and IPs in the load map then exit")
    # Carry out this step before advancing to the next part of the function.
    ap.add_argument("--dry-run",  action="store_true",
                    help="Show what would be launched without connecting")
    # Carry out this step before advancing to the next part of the function.
    ap.add_argument("--load-map", default=LOAD_MAP_FILE, metavar="FILE",
                    help="Path to load_map_with_magnetid.json")
    # Parse the command-line settings supplied by the operator.
    args = ap.parse_args()

    # ── --list mode ───────────────────────────────────────────────────────────
    # Take this branch only when the stated operating condition is true.
    if args.list:
        # Protect this hardware or file operation so a failure is reported without obscuring where it happened.
        try:
            # Import this dependency locally because it is only needed on this execution path.
            from cdcu_load_map import CdcuLoadMap
            # Capture lm here; the next step uses this intermediate result directly.
            lm = CdcuLoadMap(args.load_map)
            # Write this status to the console so the operator can follow the run in real time.
            print(f"\nLoad map: {args.load_map}\n")
            # Walk the collection in order so every item receives the same treatment.
            for cab in lm.list_cabinets():
                # Capture ips here; the next step uses this intermediate result directly.
                ips = lm.list_ips(cab)
                # Write this status to the console so the operator can follow the run in real time.
                print(f"  {cab}  ({len(ips)} supplies)")
                # Walk the collection in order so every item receives the same treatment.
                for ip in ips:
                    # Capture e here; the next step uses this intermediate result directly.
                    e = lm.lookup_soft(cab, ip, sector=args.sector) or {}
                    # Capture mid here; the next step uses this intermediate result directly.
                    mid   = e.get("magnet_id", "")
                    # Capture ldesc here; the next step uses this intermediate result directly.
                    ldesc = e.get("load_desc", "")
                    # Capture raw_v here; the next step uses this intermediate result directly.
                    raw_v = e.get("raw_V")
                    # Capture v_out here; the next step uses this intermediate result directly.
                    v_out = e.get("v_out_rating")
                    # Capture vstr here; the next step uses this intermediate result directly.
                    vstr  = (f"  Vbus={raw_v}V  Vout_rated={v_out}V"
                             if raw_v is not None else "")
                    # Write this status to the console so the operator can follow the run in real time.
                    print(f"    {ip}  |  {(mid or '?'):20s}  |  {ldesc}{vstr}")
                # Write this status to the console so the operator can follow the run in real time.
                print()
        except Exception as exc:
            # Write this status to the console so the operator can follow the run in real time.
            print(f"[one_liners] ERROR reading load map: {exc}", file=sys.stderr)
            # Hand the finished value back to the caller.
            return 1
        # Hand the finished value back to the caller.
        return 0

    # ── Cabinet is required for all other modes ───────────────────────────────
    # Take this branch only when the stated operating condition is true.
    if not args.cabinet:
        # Carry out this step before advancing to the next part of the function.
        ap.error("--cabinet is required (or use --list to see all cabinets)")

    # Take this branch only when the stated operating condition is true.
    if not os.path.isfile(MONITOR_SCRIPT):
        # Write this status to the console so the operator can follow the run in real time.
        print(f"[one_liners] ERROR: cdcu_monitor.py not found at {MONITOR_SCRIPT}",
              file=sys.stderr)
        # Hand the finished value back to the caller.
        return 1

    # ── Resolve IPs from load map ─────────────────────────────────────────────
    # Capture supplies here; the next step uses this intermediate result directly.
    supplies = resolve_ips(
        cabinet=args.cabinet,
        sector=args.sector,
        load_map_file=args.load_map,
        requested_ips=args.ips,
    )

    # Take this branch only when the stated operating condition is true.
    if not supplies:
        # Write this status to the console so the operator can follow the run in real time.
        print(f"[one_liners] No supplies found for cabinet '{args.cabinet}'.",
              file=sys.stderr)
        # Hand the finished value back to the caller.
        return 1

    # Create the output directory now so the following writes have a valid destination.
    os.makedirs(args.outdir, exist_ok=True)

    # ── Header ────────────────────────────────────────────────────────────────
    # Write this status to the console so the operator can follow the run in real time.
    print(f"\n{'='*65}")
    # Write this status to the console so the operator can follow the run in real time.
    print(f"  one_liners.py  —  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    # Write this status to the console so the operator can follow the run in real time.
    print(f"  Cabinet : {args.cabinet}   Sector : {args.sector or '(none)'}")
    # Write this status to the console so the operator can follow the run in real time.
    print(f"  Live plot/data duration setting: {_format_runtime(args.duration)}")
    print(f"  Poll interval setting          : {args.interval} s")
    # Write this status to the console so the operator can follow the run in real time.
    print(f"  Outdir  : {os.path.abspath(args.outdir)}")
    # Write this status to the console so the operator can follow the run in real time.
    print(f"  Supplies in map : {len(supplies)}")
    # Write this status to the console so the operator can follow the run in real time.
    print(f"{'='*65}\n")

    # ── Probe reachability, then launch ──────────────────────────────────────
    # Carry out this step before advancing to the next part of the function.
    procs:   List[Tuple[str, dict, subprocess.Popen, str]] = []  # ip, entry, proc, log
    # Carry out this step before advancing to the next part of the function.
    skipped: List[Tuple[str, str]] = []
    launch_times: Dict[str, float] = {}
    completion_times: Dict[str, float] = {}

    # Walk the collection in order so every item receives the same treatment.
    for ip, entry in supplies:
        # Capture magnet_id here; the next step uses this intermediate result directly.
        magnet_id = entry.get("magnet_id", "")
        # Capture load_desc here; the next step uses this intermediate result directly.
        load_desc = entry.get("load_desc", "")
        # Capture raw_v here; the next step uses this intermediate result directly.
        raw_v     = entry.get("raw_V")
        # Capture v_out here; the next step uses this intermediate result directly.
        v_out     = entry.get("v_out_rating")
        # Capture label here; the next step uses this intermediate result directly.
        label     = magnet_id or ip

        # ── Print what we know about this supply before probing ────────────
        # Write this status to the console so the operator can follow the run in real time.
        print(f"  {ip}")
        # Take this branch only when the stated operating condition is true.
        if magnet_id:
            # Write this status to the console so the operator can follow the run in real time.
            print(f"    Magnet ID : {magnet_id}")
        # Do not judge full-load performance until the load is high enough to make that comparison meaningful.
        if load_desc:
            # Write this status to the console so the operator can follow the run in real time.
            print(f"    Load      : {load_desc}")
        # Take this branch only when the stated operating condition is true.
        if raw_v is not None:
            # Write this status to the console so the operator can follow the run in real time.
            print(f"    Vbus={raw_v}V  Vout_rated={v_out}V")

        # Take this branch only when the stated operating condition is true.
        if args.dry_run:
            # Capture cmd here; the next step uses this intermediate result directly.
            cmd = build_command(ip, args.cabinet, args.sector,
                                args.duration, args.interval,
                                args.outdir, args.no_analysis)
            # Write this status to the console so the operator can follow the run in real time.
            print(f"    [dry-run] {' '.join(cmd)}\n")
            # Skip this item and continue with the next valid candidate.
            continue

        # ── TCP probe ─────────────────────────────────────────────────────
        # Write this field to the report in the same order an engineer will review it.
        sys.stdout.write(f"    Probing TCP {ip}:{PORT} ... ")
        # Carry out this step before advancing to the next part of the function.
        sys.stdout.flush()
        # Take this branch only when the stated operating condition is true.
        if not probe_ip(ip, PORT, args.probe_timeout):
            # Write this status to the console so the operator can follow the run in real time.
            print("UNREACHABLE — skipped\n")
            # Add this observation to the ordered history so the sequence is preserved.
            skipped.append((ip, label))
            # Skip this item and continue with the next valid candidate.
            continue
        # Write this status to the console so the operator can follow the run in real time.
        print("reachable")

        # ── Launch subprocess ──────────────────────────────────────────────
        # Capture cmd here; the next step uses this intermediate result directly.
        cmd = build_command(ip, args.cabinet, args.sector,
                            args.duration, args.interval,
                            args.outdir, args.no_analysis)
        # Resolve log_path once so later file operations use the same location.
        log_path = os.path.join(args.outdir,
                                f"cdcu_{ip.replace('.', '_')}_stdout.log")
        # Capture log_fh here; the next step uses this intermediate result directly.
        log_fh = open(log_path, "w", encoding="utf-8")
        # Capture proc here; the next step uses this intermediate result directly.
        proc = subprocess.Popen(
            cmd,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            # New session: Ctrl+C on one_liners.py won't race with child
            # SIGINT handlers; we manage shutdown manually below.
            start_new_session=True,
        )
        # Add this observation to the ordered history so the sequence is preserved.
        procs.append((ip, entry, proc, log_path))
        launch_times[ip] = time.perf_counter()
        # Write this status to the console so the operator can follow the run in real time.
        print(f"    Launched  PID {proc.pid}  →  {log_path}\n")

        # Stagger launches so all units don't burst-query the network
        # at exactly the same millisecond
        # Carry out this step before advancing to the next part of the function.
        time.sleep(LAUNCH_STAGGER)

    # Take this branch only when the stated operating condition is true.
    if args.dry_run:
        # Hand the finished value back to the caller.
        return 0

    # Take this branch only when the stated operating condition is true.
    if not procs:
        # Write this status to the console so the operator can follow the run in real time.
        print(f"[one_liners] No reachable supplies — nothing to do.")
        # Take this branch only when the stated operating condition is true.
        if skipped:
            # Write this status to the console so the operator can follow the run in real time.
            print(f"  Skipped: {[ip for ip, _ in skipped]}")
        # Hand the finished value back to the caller.
        return 1

    # Write this status to the console so the operator can follow the run in real time.
    print(f"{'='*65}")
    # Write this status to the console so the operator can follow the run in real time.
    print(f"  {len(procs)} monitor(s) running in parallel")
    # Take this branch only when the stated operating condition is true.
    if skipped:
        # Write this status to the console so the operator can follow the run in real time.
        print(f"  Skipped (unreachable): {[ip for ip, _ in skipped]}")
    # Write this status to the console so the operator can follow the run in real time.
    print(f"  Press Ctrl+C to stop all.\n")

    # ── Wait for all children, printing a live status line ───────────────────
    # Capture start_wall here; the next step uses this intermediate result directly.
    start_wall = time.monotonic()
    # Capture interrupted here; the next step uses this intermediate result directly.
    interrupted = False

    # Protect this hardware or file operation so a failure is reported without obscuring where it happened.
    try:
        # Stay in this loop until the stated completion condition changes.
        while True:
            _now = time.perf_counter()
            for _ip, _entry, _proc, _log in procs:
                if _proc.poll() is not None and _ip not in completion_times:
                    completion_times[_ip] = _now
            # Capture alive here; the next step uses this intermediate result directly.
            alive = [(ip, e, p, lg) for ip, e, p, lg in procs if p.poll() is None]
            # Take this branch only when the stated operating condition is true.
            if not alive:
                # The required item is resolved, so leave this loop now.
                break
            # Capture elapsed here; the next step uses this intermediate result directly.
            elapsed = time.monotonic() - start_wall
            # Capture done here; the next step uses this intermediate result directly.
            done    = len(procs) - len(alive)
            # Capture alive_ips here; the next step uses this intermediate result directly.
            alive_ips = ", ".join(ip for ip, _, _, _ in alive)
            # Write this field to the report in the same order an engineer will review it.
            sys.stdout.write(
                f"\r  {elapsed:5.0f}s  |  {done}/{len(procs)} done  "
                f"|  running: {alive_ips}   "
            )
            # Carry out this step before advancing to the next part of the function.
            sys.stdout.flush()
            # Carry out this step before advancing to the next part of the function.
            time.sleep(2.0)

    except KeyboardInterrupt:
        # Capture interrupted here; the next step uses this intermediate result directly.
        interrupted = True
        # Write this status to the console so the operator can follow the run in real time.
        print(f"\n\n  Ctrl+C — sending SIGTERM to {len(procs)} child process(es) ...")
        # Walk the collection in order so every item receives the same treatment.
        for ip, _, proc, _ in procs:
            # Take this branch only when the stated operating condition is true.
            if proc.poll() is None:
                # Protect this hardware or file operation so a failure is reported without obscuring where it happened.
                try:
                    # Carry out this step before advancing to the next part of the function.
                    proc.terminate()
                    # Write this status to the console so the operator can follow the run in real time.
                    print(f"    SIGTERM → PID {proc.pid}  ({ip})")
                except OSError:
                    # No action is required in this branch; keep the control flow explicit.
                    pass

        # Give children up to 8 s to flush CSV, close socket, save PNG
        # Capture deadline here; the next step uses this intermediate result directly.
        deadline = time.monotonic() + 8.0
        # Walk the collection in order so every item receives the same treatment.
        for ip, _, proc, _ in procs:
            # Capture remaining here; the next step uses this intermediate result directly.
            remaining = max(0.0, deadline - time.monotonic())
            # Protect this hardware or file operation so a failure is reported without obscuring where it happened.
            try:
                # Carry out this step before advancing to the next part of the function.
                proc.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                # Write this status to the console so the operator can follow the run in real time.
                print(f"    SIGKILL → PID {proc.pid}  ({ip})")
                # Carry out this step before advancing to the next part of the function.
                proc.kill()

    # ── Final summary ─────────────────────────────────────────────────────────
    _summary_now = time.perf_counter()
    for _ip, _entry, _proc, _log in procs:
        if _ip not in completion_times and _proc.poll() is not None:
            completion_times[_ip] = _summary_now
    elapsed_total = _summary_now - _program_start_mono
    # Write this status to the console so the operator can follow the run in real time.
    print(f"\n\n{'='*65}")
    # Write this status to the console so the operator can follow the run in real time.
    print(f"  Run complete — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    # Write this status to the console so the operator can follow the run in real time.
    print(f"  Total program runtime: {_format_runtime(elapsed_total)}")
    print(f"  Program start: {_program_start_local.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Program finish: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    # Write this status to the console so the operator can follow the run in real time.
    print(f"{'='*65}")

    # Capture all_ok here; the next step uses this intermediate result directly.
    all_ok = True
    # Walk the collection in order so every item receives the same treatment.
    for ip, entry, proc, log_path in procs:
        # Capture rc here; the next step uses this intermediate result directly.
        rc  = proc.returncode if proc.returncode is not None else proc.wait()
        # Capture mid here; the next step uses this intermediate result directly.
        mid = entry.get("magnet_id", "")
        # Capture lbl here; the next step uses this intermediate result directly.
        lbl = entry.get("load_desc", "")[:40]
        # Carry out this step before advancing to the next part of the function.
        status = "OK " if rc == 0 else f"EXIT {rc}"
        # Take this branch only when the stated operating condition is true.
        if rc != 0:
            # Capture all_ok here; the next step uses this intermediate result directly.
            all_ok = False
        # Resolve csv_path once so later file operations use the same location.
        csv_path = os.path.join(args.outdir, f"cdcu_{ip.replace('.','_')}.csv")
        # Resolve png_path once so later file operations use the same location.
        png_path = os.path.join(args.outdir, f"cdcu_{ip.replace('.','_')}_live.png")
        # Write this status to the console so the operator can follow the run in real time.
        print(f"\n  {ip}  {mid or lbl}")
        # Write this status to the console so the operator can follow the run in real time.
        print(f"    Status : {status}")
        _launch_t = launch_times.get(ip)
        _done_t = completion_times.get(ip, time.perf_counter())
        if _launch_t is not None:
            print(f"    Runtime: {_format_runtime(_done_t - _launch_t)}")
        # Write this status to the console so the operator can follow the run in real time.
        print(f"    CSV    : {csv_path}")
        # Write this status to the console so the operator can follow the run in real time.
        print(f"    PNG    : {png_path}")
        # Write this status to the console so the operator can follow the run in real time.
        print(f"    Log    : {log_path}")

    # Take this branch only when the stated operating condition is true.
    if skipped:
        # Write this status to the console so the operator can follow the run in real time.
        print(f"\n  Skipped (unreachable at probe time):")
        # Walk the collection in order so every item receives the same treatment.
        for ip, label in skipped:
            # Write this status to the console so the operator can follow the run in real time.
            print(f"    {ip}  {label}")

    # Write this status to the console so the operator can follow the run in real time.
    print(f"\n  Live plot/data duration setting per supply: {_format_runtime(args.duration)}")
    print(f"  Total runtime from one_liners start to finish: {_format_runtime(time.perf_counter() - _program_start_mono)}")
    print(f"  All outputs in: {os.path.abspath(args.outdir)}\n")

    # Take this branch only when the stated operating condition is true.
    if interrupted:
        # Hand the finished value back to the caller.
        return 130  # conventional Ctrl+C exit code
    # Hand the finished value back to the caller.
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
