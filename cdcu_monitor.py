# ---------------------------------------------------------------------------
# Authored By: Byron Jordan
# Power Supply Engineer
# Advanced Photon Source (APS)
# Argonne National Laboratory
# ---------------------------------------------------------------------------
import os
import socket
import time
import csv
import math
import json
import statistics
import matplotlib.pyplot as plt
from collections import deque
from datetime import datetime, timezone

# Program-level runtime clock.  This starts before argument parsing, network
# connection, startup PMM, live polling, final PMM, analysis, and report writing.
_PROGRAM_START_MONO = time.perf_counter()
_PROGRAM_START_LOCAL = datetime.now()

def _format_runtime(seconds: float) -> str:
    """Return elapsed seconds as both numeric seconds and HH:MM:SS.s."""
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60.0
    return f"{seconds:.3f} s ({hours:02d}:{minutes:02d}:{secs:04.1f})"

try:
    from cdcu_registers import decode_mftr, decode_mstr, fault_summary
    _REGISTERS_AVAILABLE = True
except ImportError:
    _REGISTERS_AVAILABLE = False

try:
    import cdcu_diagnostics
    _DIAGNOSTICS_AVAILABLE = True
except ImportError:
    _DIAGNOSTICS_AVAILABLE = False

try:
    import magnet_load_diagnostics
    _MAGNET_DIAGNOSTICS_AVAILABLE = True
except ImportError:
    _MAGNET_DIAGNOSTICS_AVAILABLE = False

# ============================================================
# USER SETTINGS
# ============================================================
HOST = ""          # Replace with your CDCU IP
# HOST = "192.168.3.2"          # Replace with your CDCU IP
# HOST    = "192.168.7.2"         # Replace with your CDCU IP
PORT    = 10001                 # Verify the correct TCP port
DURATION = 30                  # seconds
INTERVAL = 0.0007                 # seconds between burst acquisitions
SOCKET_TIMEOUT = 2.0            # seconds
CSV_FILE = "cdcu_measured_log.csv"
PNG_FILE = "cdcu_measured_live_plot.png"

# ── Load map settings ─────────────────────────────────────────────────────
# Carry out this step before advancing to the next part of the function.
# Carry out this step before advancing to the next part of the function.
# Example: CABINET = "Cab_1", SECTOR = "S01"  → magnet_id "S01:BQ1"
# Capture CABINET here; the next step uses this intermediate result directly.
CABINET          = ""          # e.g. "Cab_1", "Cab_2", "E-Lab", "Test_1"
SECTOR           = ""            # e.g. "S01", "P01", "L1127"
LOAD_MAP_FILE    = "load_map_with_magnetid.json"

# ── PMM spectral analysis ─────────────────────────────────────────────────
# FFT/PSD is intentionally restricted to PMM captures.  Live Ethernet polling
# remains available for slow diagnostics, trends, efficiency, and fault status,
# but polling samples are not sent to the FFT/PSD engine.
RUN_RIPPLE_ANALYSIS = True

# ── Post-Mortem Monitor (PMM) settings ────────────────────────────────────
# Sequence (matches cdcu_pmm_force_fault_fft_win.py):
#   PMM:TRIG → PMM:RESET (arm) → PMM:FORCE → poll PMM:READY:? → fetch → PMM:RESET (rearm)
#
# PMM:FORCE software-triggers the buffer immediately after arming —
# no delay, no fault needed. The supply is already at steady state.
#
# PMM buffer spec (CAEN CDCU manual Rev 1.3, Section 4.12):
#   - 100,001 samples at 100 µs fixed rate → Fs = 10 kHz, Nyquist = 5 kHz
#   - Resolves all three bands: 1–10 Hz, 60–120 Hz, 360–720 Hz ✓
#   - Channels: 0 = Vout, 1 = Iout, 2 = Iset (Setpoint Current)
#   - Firmware response prefix: #PPM: (handled automatically)
#
# PMM_PRE_FAULT_S  : seconds of pre-force data in the 10 s window (range 0–10)
# PMM_WAIT_TIMEOUT : max seconds to wait for PMM:READY=1 after PMM:FORCE
RUN_PMM            = True    # enable PMM capture on every run
PMM_PRE_FAULT_S    = 5.0     # 5 s pre-trigger, approximately 5 s post-trigger
PMM_WAIT_TIMEOUT   = 10.0    # allow the forced PMM time to finish its post-trigger record
PMM_FAULT_READY_TIMEOUT = 7.5  # allow a hardware-triggered PMM to finish before fetch
PMM_FINAL_TRIGGER_LEAD_S = 0.25  # force the final PMM just before live polling reaches its timeout

# ── MRID write-back ────────────────────────────────────────────────────────
# If True and load map resolves a magnet_id, write it to the unit's
# internal Module ID (parameter #30) via MWG:30 + MSAVE on connect.
# This embeds the magnet name in the unit display and MRID readback.
# Requires admin privileges (default password: PS-ADMIN).
WRITE_MRID_ON_CONNECT = False

# ============================================================
# CLI ARGUMENT PARSING
# Overrides USER SETTINGS when run from the command line or
# via one_liners.py.  All arguments are optional; hardcoded
# defaults above are used when not supplied.
# ============================================================
import argparse as _ap
import subprocess as _subprocess
import sys as _sys
import threading as _threading
import signal as _signal


def _normalize_hosts(values):
    """Return a de-duplicated host list while accepting space- or comma-separated input."""
    hosts = []
    seen = set()
    for value in values or []:
        for host in str(value).split(","):
            host = host.strip()
            if host and host not in seen:
                seen.add(host)
                hosts.append(host)
    return hosts



def _create_parallel_dashboard(hosts, outdir):
    """Create one consolidated 2-column live dashboard for up to eight CDCU supplies."""
    from collections import deque as _deque
    n = len(hosts)
    ncols = 2
    nrows = max(1, (n + 1) // 2)
    # Scale the window with row count while keeping a practical desktop aspect ratio.
    fig = plt.figure(figsize=(16, min(13.5, 4.0 * nrows)))
    try:
        fig.canvas.manager.set_window_title(f"CDCU Multi-IP Live Monitor — {n} Supplies")
    except Exception:
        pass
    outer = fig.add_gridspec(nrows, ncols, hspace=0.36, wspace=0.20)
    fig.suptitle(f"CDCU Multi-IP Live Monitor — {n} Supplies", fontsize=14, fontweight="bold")
    states = {}

    for idx, host in enumerate(hosts):
        row, col = divmod(idx, ncols)
        inner = outer[row, col].subgridspec(4, 1, hspace=0.10)
        axes = [fig.add_subplot(inner[j, 0]) for j in range(4)]
        axes[0].set_title(f"{host} — waiting for live telemetry", loc="left", fontsize=8, fontweight="bold")
        for ax in axes:
            ax.grid(True, alpha=0.20)
            ax.tick_params(labelsize=5)
        axes[0].set_ylabel("W", fontsize=6)
        axes[1].set_ylabel("V / A", fontsize=6)
        axes[2].set_ylabel("Eff %", fontsize=6)
        axes[2].set_ylim(0, 105)
        axes[3].set_ylabel("°C", fontsize=6)
        axes[3].set_xlabel("Time (s)", fontsize=6)
        for ax in axes[:3]:
            ax.tick_params(labelbottom=False)

        line_pin, = axes[0].plot([], [], label="Pin")
        line_pout, = axes[0].plot([], [], label="Pout")
        e_lines = {}
        for key, label in [("mrp_v", "Vbus"), ("mgpc_a", "Ibus"), ("mrv_v", "Vout"), ("mri_a", "Iout")]:
            e_lines[key], = axes[1].plot([], [], label=label)
        line_eff, = axes[2].plot([], [], label="Efficiency")
        temp_lines = {}
        for key, label in [("MRT", "Max"), ("MRT:1", "Buck"), ("MRT:2", "Caps"), ("MRT:3", "ADC/Shunt"), ("MRT:4", "Carrier")]:
            temp_lines[key], = axes[3].plot([], [], label=label)
        axes[0].legend(loc="upper left", fontsize=5, ncol=2)
        axes[1].legend(loc="upper left", fontsize=5, ncol=4)
        axes[2].legend(loc="upper left", fontsize=5)
        axes[3].legend(loc="upper left", fontsize=5, ncol=3)

        states[host] = {
            "axes": axes,
            "t": _deque(maxlen=900),
            "pin": _deque(maxlen=900), "pout": _deque(maxlen=900),
            "mrp_v": _deque(maxlen=900), "mgpc_a": _deque(maxlen=900),
            "mrv_v": _deque(maxlen=900), "mri_a": _deque(maxlen=900),
            "eff": _deque(maxlen=900),
            "temps": {k: _deque(maxlen=900) for k in temp_lines},
            "line_pin": line_pin, "line_pout": line_pout,
            "e_lines": e_lines, "line_eff": line_eff, "temp_lines": temp_lines,
            "last_t": None,
            "last_cycling": False,
        }

    # Hide an unused tile for odd supply counts.
    if n % 2:
        ax_blank = fig.add_subplot(outer[nrows - 1, 1])
        ax_blank.axis("off")
    fig.subplots_adjust(left=0.055, right=0.99, bottom=0.045, top=0.95)
    plt.ion()
    plt.show(block=False)
    # Maximize the one dashboard window on common Windows/Tk backends when supported.
    try:
        manager = plt.get_current_fig_manager()
        if hasattr(manager, "window") and hasattr(manager.window, "state"):
            manager.window.state("zoomed")
    except Exception:
        pass
    return fig, states


def _update_parallel_dashboard(fig, states, snapshot_files):
    """Load atomic child snapshots and refresh the consolidated dashboard."""
    for host, path in snapshot_files.items():
        st = states.get(host)
        if st is None or not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                snap = json.load(fh)
        except Exception:
            continue
        t = snap.get("t_s")
        if t is None or t == st["last_t"]:
            continue
        t = float(t)
        prev_t = st["last_t"]
        is_cycling = bool(snap.get("is_magnet_cycling", False))
        if is_cycling and prev_t is not None and t > float(prev_t):
            for ax in st["axes"]:
                ax.axvspan(float(prev_t), t, facecolor=CYCLING_SHADE_COLOR,
                           alpha=CYCLING_SHADE_ALPHA, zorder=0)
        st["last_t"] = t
        st["last_cycling"] = is_cycling
        st["t"].append(float(t))
        for key, target in [("pin_w", "pin"), ("pout_w", "pout"),
                            ("mrp_v", "mrp_v"), ("mgpc_a", "mgpc_a"),
                            ("mrv_v", "mrv_v"), ("mri_a", "mri_a")]:
            val = snap.get(key)
            st[target].append(float("nan") if val is None else float(val))
        ev = snap.get("eff_pct")
        st["eff"].append(float("nan") if ev is None else float(ev))
        temps = snap.get("temperatures_c") or {}
        for key, dq in st["temps"].items():
            tv = temps.get(key)
            dq.append(float("nan") if tv is None else float(tv))

        tvals = list(st["t"])
        st["line_pin"].set_data(tvals, list(st["pin"]))
        st["line_pout"].set_data(tvals, list(st["pout"]))
        for key, line in st["e_lines"].items():
            line.set_data(tvals, list(st[key]))
        st["line_eff"].set_data(tvals, list(st["eff"]))
        for key, line in st["temp_lines"].items():
            line.set_data(tvals, list(st["temps"][key]))

        axes = st["axes"]
        for ax in (axes[0], axes[1], axes[3]):
            ax.relim()
            ax.autoscale_view()
        if tvals:
            xmin, xmax = min(tvals), max(tvals)
            if xmax <= xmin:
                xmax = xmin + 1.0
            for ax in axes:
                ax.set_xlim(xmin, xmax)
        magnet = snap.get("magnet_id") or ""
        fault = snap.get("fault") or ""
        state = snap.get("state") or ""
        title = f"{host}"
        if magnet:
            title += f"  |  {magnet}"
        if is_cycling:
            title += "  |  CYCLING"
        elif state:
            title += f"  |  {state}"
        if fault:
            title += f"  |  {fault}"
        axes[0].set_title(title, loc="left", fontsize=8, fontweight="bold")
    try:
        fig.canvas.draw_idle()
        fig.canvas.flush_events()
        plt.pause(0.001)
    except Exception:
        pass


def _run_parallel_hosts(args) -> int:
    """
    Launch one independent cdcu_monitor.py process per IP address.

    Each child executes the normal single-supply code path, so PMM capture,
    live plotting, temperature monitoring, diagnostics, FFT/PSD, PDFs, CSVs,
    fault handling, magnet-load calculations, and runtime reporting are the
    same as when that IP is run by itself.
    """
    hosts = _normalize_hosts(args.hosts)
    if not hosts:
        print("[cdcu_monitor] No valid IP addresses were supplied to --hosts.", file=_sys.stderr)
        return 2
    if args.host:
        print("[cdcu_monitor] Use either --host or --hosts, not both.", file=_sys.stderr)
        return 2

    if args.dcbus_spectrum_csv and len(hosts) > 1:
        print("[cdcu_monitor] --dcbus-spectrum-csv currently supports single-host runs only; "
              "each supply requires its own synchronized hardware capture.", file=_sys.stderr)
        return 2

    parent_start_mono = time.perf_counter()
    parent_start_local = datetime.now()
    script_path = os.path.abspath(__file__)
    os.makedirs(args.outdir, exist_ok=True)
    log_dir = os.path.join(args.outdir, "parallel_logs")
    os.makedirs(log_dir, exist_ok=True)
    dashboard_mode = bool((not args.no_plot) and (not args.individual_plots))
    dashboard_dir = os.path.join(args.outdir, ".parallel_dashboard")
    snapshot_files = {}
    if dashboard_mode:
        os.makedirs(dashboard_dir, exist_ok=True)
        for ip in hosts:
            snapshot_files[ip] = os.path.join(dashboard_dir, f"cdcu_{ip.replace('.', '_')}.json")
            try:
                os.remove(snapshot_files[ip])
            except FileNotFoundError:
                pass

    print("\n" + "=" * 78)
    print("  CDCU PARALLEL MONITOR")
    print(f"  Program start                  : {parent_start_local.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Supplies requested             : {len(hosts)}")
    print(f"  IP addresses                   : {', '.join(hosts)}")
    print(f"  Live plot/data duration/supply : {_format_runtime(args.duration)}")
    print(f"  Poll interval/supply           : {args.interval} s")
    if args.no_plot:
        _plot_mode_text = "OFF"
    elif dashboard_mode:
        _plot_mode_text = f"ON — consolidated 2 x {(len(hosts)+1)//2} dashboard"
    else:
        _plot_mode_text = "ON — one window per supply"
    print(f"  Live plots                     : {_plot_mode_text}")
    print(f"  Output root                    : {os.path.abspath(args.outdir)}")
    print("=" * 78 + "\n")

    processes = []
    print_lock = _threading.Lock()

    def _stream_output(ip, proc, log_path):
        """Mirror one child's terminal output to its log and prefix it in the parent terminal."""
        try:
            with open(log_path, "w", encoding="utf-8", buffering=1) as log_fh:
                if proc.stdout is None:
                    return
                for line in proc.stdout:
                    log_fh.write(line)
                    with print_lock:
                        print(f"[{ip}] {line}", end="", flush=True)
        except Exception as exc:
            with print_lock:
                print(f"[{ip}] [parallel-output] {exc}", file=_sys.stderr, flush=True)

    for ip in hosts:
        cmd = [
            _sys.executable,
            script_path,
            "--host", ip,
            "--cabinet", args.cabinet,
            "--sector", args.sector,
            "--duration", str(args.duration),
            "--interval", str(args.interval),
            "--outdir", args.outdir,
        ]
        if args.no_analysis:
            cmd.append("--no-analysis")
        if args.no_plot:
            cmd.append("--no-plot")
        elif dashboard_mode:
            # Children retain the complete single-supply workflow but suppress their own GUI.
            # Live telemetry is mirrored into one parent-managed dashboard window instead.
            cmd.extend(["--no-plot", "--dashboard-file", snapshot_files[ip]])

        # The child monitor writes Unicode section separators and engineering symbols.
        # On Windows, a redirected Python stdout stream can otherwise fall back to the
        # legacy cp1252 code page and raise UnicodeEncodeError before monitoring starts.
        # Force UTF-8 for the child pipe and keep it unbuffered so the parent sees the
        # full single-supply terminal output in real time.
        child_env = os.environ.copy()
        child_env["PYTHONIOENCODING"] = "utf-8"
        child_env["PYTHONUTF8"] = "1"
        child_env["PYTHONUNBUFFERED"] = "1"

        popen_kwargs = dict(
            stdout=_subprocess.PIPE,
            stderr=_subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=child_env,
        )
        if os.name == "nt":
            # Give each supply its own Windows process group so Ctrl+C handling
            # in the parent does not race with every child at the same time.
            popen_kwargs["creationflags"] = _subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True

        launch_mono = time.perf_counter()
        proc = _subprocess.Popen(cmd, **popen_kwargs)
        log_path = os.path.join(log_dir, f"cdcu_{ip.replace('.', '_')}_stdout.log")
        reader = _threading.Thread(
            target=_stream_output,
            args=(ip, proc, log_path),
            name=f"cdcu-output-{ip}",
            daemon=True,
        )
        reader.start()
        processes.append({
            "ip": ip,
            "proc": proc,
            "reader": reader,
            "log": log_path,
            "launch_mono": launch_mono,
            "finish_mono": None,
        })
        print(f"[parallel] Launched {ip}  PID={proc.pid}  Log={log_path}")
        # Small stagger prevents every supply from issuing startup PMM/network
        # commands in the same millisecond while remaining effectively simultaneous.
        time.sleep(0.15)

    dashboard_fig = None
    dashboard_states = None
    if dashboard_mode:
        try:
            dashboard_fig, dashboard_states = _create_parallel_dashboard(hosts, args.outdir)
            print(f"[parallel] Consolidated dashboard opened: 2 x {(len(hosts)+1)//2} supply layout")
        except Exception as exc:
            print(f"[parallel] Dashboard creation failed; monitoring continues headless: {exc}")
            dashboard_mode = False

    interrupted = False
    try:
        while True:
            alive = 0
            now = time.perf_counter()
            for item in processes:
                proc = item["proc"]
                if proc.poll() is None:
                    alive += 1
                elif item["finish_mono"] is None:
                    item["finish_mono"] = now
            if dashboard_mode and dashboard_fig is not None and dashboard_states is not None:
                _update_parallel_dashboard(dashboard_fig, dashboard_states, snapshot_files)
            if alive == 0:
                break
            time.sleep(0.20)
    except KeyboardInterrupt:
        interrupted = True
        print("\n[parallel] Ctrl+C received — stopping all active supply monitors...")
        for item in processes:
            proc = item["proc"]
            if proc.poll() is not None:
                continue
            try:
                if os.name == "nt":
                    proc.send_signal(_signal.CTRL_BREAK_EVENT)
                else:
                    proc.terminate()
            except Exception:
                try:
                    proc.terminate()
                except Exception:
                    pass
        deadline = time.perf_counter() + 10.0
        for item in processes:
            proc = item["proc"]
            if proc.poll() is None:
                remaining = max(0.0, deadline - time.perf_counter())
                try:
                    proc.wait(timeout=remaining)
                except _subprocess.TimeoutExpired:
                    proc.kill()

    finish_mono = time.perf_counter()
    finish_local = datetime.now()
    all_ok = True

    if dashboard_mode and dashboard_fig is not None:
        try:
            _update_parallel_dashboard(dashboard_fig, dashboard_states, snapshot_files)
            _dashboard_png = os.path.join(args.outdir, "cdcu_parallel_dashboard_final.png")
            dashboard_fig.savefig(_dashboard_png, dpi=150, bbox_inches="tight")
            print(f"[parallel] Final consolidated dashboard saved: {_dashboard_png}")
            plt.close(dashboard_fig)
        except Exception as exc:
            print(f"[parallel] Dashboard final-save warning: {exc}")

    print("\n" + "=" * 78)
    print("  PARALLEL MONITOR RUNTIME SUMMARY")
    print(f"  Live plot/data duration setting : {_format_runtime(args.duration)} per supply")
    for item in processes:
        proc = item["proc"]
        rc = proc.returncode if proc.returncode is not None else proc.wait()
        if item["finish_mono"] is None:
            item["finish_mono"] = time.perf_counter()
        runtime = item["finish_mono"] - item["launch_mono"]
        status = "OK" if rc == 0 else f"EXIT {rc}"
        all_ok = all_ok and (rc == 0)
        print(f"  {item['ip']:15s}  {status:8s}  runtime={_format_runtime(runtime)}")
        print(f"      terminal log: {item['log']}")
    print(f"  Total runtime, program start -> finish: {_format_runtime(finish_mono - parent_start_mono)}")
    print(f"  Program start : {parent_start_local.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Program finish: {finish_local.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 78 + "\n")

    for item in processes:
        item["reader"].join(timeout=1.0)

    if interrupted:
        return 130
    return 0 if all_ok else 1


_parser = _ap.ArgumentParser(
    description="CDCU live monitor — run one supply or multiple supplies simultaneously.",
    formatter_class=_ap.ArgumentDefaultsHelpFormatter,
)
_parser.add_argument("--host",     default=HOST,     metavar="IP",
                     help="Single CDCU IP address")
_parser.add_argument("--hosts",    nargs="+",       metavar="IP", default=None,
                     help="Multiple CDCU IP addresses to run simultaneously; each gets the complete single-supply monitor workflow")
_parser.add_argument("--cabinet",  default=CABINET,  metavar="NAME",
                     help="Cabinet name in load map (e.g. Cab_1, Test_1)")
_parser.add_argument("--sector",   default=SECTOR,   metavar="STR",
                     help="Sector string to substitute {SECTOR} (e.g. S01, B400A)")
_parser.add_argument("--duration", default=DURATION, type=float, metavar="SEC",
                     help="Live plot/data duration in seconds per supply")
_parser.add_argument("--interval", default=INTERVAL, type=float, metavar="SEC",
                     help="Polling interval in seconds per supply")
_parser.add_argument("--outdir",   default=".",      metavar="DIR",
                     help="Output root directory for all supply results")
_parser.add_argument("--no-analysis", action="store_true",
                     help="Skip optional post-run report assembly; startup/fault/final PMM captures are still analyzed immediately")
_parser.add_argument("--no-plot",     action="store_true",
                     help="Suppress live matplotlib windows for all supplies (headless / batch use)")
_parser.add_argument("--individual-plots", action="store_true",
                     help="Multi-IP only: use one normal live-plot window per supply instead of the consolidated dashboard")
_parser.add_argument("--dashboard-file", default=None, help=_ap.SUPPRESS)
_parser.add_argument("--dcbus-spectrum-csv", default=None, metavar="CSV",
                     help="Optional hardware-timed 100,001-sample/10 kHz DCBus capture CSV (MRP/MGPC). Replaces Set Current FFT/PSD in the final spectral report.")
_parser.add_argument("--dcbus-assume-10khz", action="store_true",
                     help="Allow DCBus CSV without time_s only when the acquisition hardware is known to sample at exactly 10 kHz.")
_args = _parser.parse_args()

# Multi-supply mode is a launcher only.  Each child process re-enters this same
# file with --host and therefore executes the exact normal single-supply path.
if _args.hosts:
    raise SystemExit(_run_parallel_hosts(_args))

# Apply parsed values — these override the hardcoded USER SETTINGS above
import os as _os
HOST      = _args.host
CABINET   = _args.cabinet
SECTOR    = _args.sector
DURATION  = _args.duration
INTERVAL  = _args.interval
_OUTDIR   = _args.outdir
_os.makedirs(_OUTDIR, exist_ok=True)

# Derive output file paths from outdir + host (so parallel runs don't collide)
_host_tag = HOST.replace(".", "_")
CSV_FILE  = _os.path.join(_OUTDIR, f"cdcu_{_host_tag}.csv")
PNG_FILE  = _os.path.join(_OUTDIR, f"cdcu_{_host_tag}_live.png")

if _args.no_analysis:
    RUN_RIPPLE_ANALYSIS = False
_HEADLESS = _args.no_plot
_DASHBOARD_FILE = _args.dashboard_file
_DASHBOARD_MIN_WRITE_INTERVAL_S = 0.20
_dashboard_last_write_mono = 0.0


def _write_dashboard_snapshot(payload):
    """Atomically publish a compact live-telemetry snapshot for the multi-IP dashboard."""
    global _dashboard_last_write_mono
    if not _DASHBOARD_FILE:
        return
    now = time.perf_counter()
    if now - _dashboard_last_write_mono < _DASHBOARD_MIN_WRITE_INTERVAL_S:
        return
    _dashboard_last_write_mono = now
    try:
        os.makedirs(os.path.dirname(os.path.abspath(_DASHBOARD_FILE)), exist_ok=True)
        tmp = _DASHBOARD_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, separators=(",", ":"), allow_nan=False)
        os.replace(tmp, _DASHBOARD_FILE)
    except Exception:
        # Dashboard publishing is presentation-only and must never interrupt monitoring.
        pass

MAX_POINTS = 30000

# ============================================================
# LIVE MONITOR SIGNAL SELECTION
# ============================================================
# Add, remove, or comment out entries here.  This is the only block a user
# should need to edit when changing the normal live-polling signal set.
#
# numeric=True  -> parse the reply as a number and make it available to plots.
# plot=True     -> show the numeric signal on the Electrical Values panel.
#
# MRP, MGPC, MRV, and MRI are used by the power/efficiency diagnostics.  The
# monitor will still run if one is removed, but the derived calculations that
# depend on that signal will report NaN rather than inventing a value.
SIGNALS = {
    "MRP":  {"label": "DC Bus Voltage",          "unit": "V",   "numeric": True,  "plot": True},
    "MGPC": {"label": "Input Current",           "unit": "A",   "numeric": True,  "plot": True},
    "MRV":  {"label": "Output Voltage",          "unit": "V",   "numeric": True,  "plot": True},
    "MRI":  {"label": "Output Current",           "unit": "A",   "numeric": True,  "plot": True},
    "SN":   {"label": "Serial Number",           "unit": "",    "numeric": False, "plot": False},
    "MSRI": {"label": "Current Ramp Slew Rate",  "unit": "A/s", "numeric": True,  "plot": False},
    "MFTR": {"label": "Fault Register",          "unit": "",    "numeric": False, "plot": False},
    "MRW":  {"label": "Estimated Active Power", "unit": "W",   "numeric": True,  "plot": False},
    "VER":  {"label": "Firmware Version",        "unit": "",    "numeric": False, "plot": False},

    # CAEN Remote Control Manual Rev. 1.3 temperature channels.
    # MRT returns the maximum internal temperature. MRT:1 through MRT:4 expose
    # the individual temperature sensors. temperature_plot=True keeps these
    # signals together on the dedicated temperature figure instead of mixing
    # degrees Celsius with voltage/current traces on the Electrical Values plot.
    "MRT":   {"label": "Maximum Internal Temperature", "unit": "degC", "numeric": True, "plot": False, "temperature_plot": True},
    "MRT:1": {"label": "Buck Temperature",             "unit": "degC", "numeric": True, "plot": False, "temperature_plot": True},
    "MRT:2": {"label": "Capacitor Bank Temperature",   "unit": "degC", "numeric": True, "plot": False, "temperature_plot": True},
    "MRT:3": {"label": "ADC and Shunt Temperature",    "unit": "degC", "numeric": True, "plot": False, "temperature_plot": True},
    "MRT:4": {"label": "Carrier Board Temperature",    "unit": "degC", "numeric": True, "plot": False, "temperature_plot": True},

    # Example addition:
    # "MRID": {"label": "Magnet ID", "unit": "", "numeric": False, "plot": False},
}

commands = list(SIGNALS.keys())
temperature_commands = [
    cmd for cmd, cfg in SIGNALS.items()
    if cfg.get("numeric", False) and cfg.get("temperature_plot", False)
]

# Magnet-cycling visualization settings.  The live plots remain dynamic; this
# overlay only marks intervals where the measured output current is actively
# moving.  Operators can tune the threshold without editing code by setting:
#     $env:CDCU_CYCLING_DIDT_THRESHOLD_A_PER_S = "0.5"
CYCLING_DIDT_THRESHOLD_A_PER_S = float(
    os.environ.get("CDCU_CYCLING_DIDT_THRESHOLD_A_PER_S", "0.5")
)
CYCLING_SHADE_ALPHA = 0.10
CYCLING_SHADE_COLOR = "gold"


def _parse_cdcu_field(raw: str) -> str:
    """Strip '#PREFIX:' from a CDCU response; return value after the last ':'."""
    # Capture raw here; the next step uses this intermediate result directly.
    raw = str(raw).strip()
    # Take this branch only when the stated operating condition is true.
    if "NAK" in raw or "ERR" in raw or not raw:
        # Hand the finished value back to the caller.
        return ""
    # Hand the finished value back to the caller.
    return raw.split(":")[-1].strip()


def _magnet_name_from_load_desc(magnet_id: str, load_desc: str) -> str:
    """
    If magnet_id ends with ':' (bare sector prefix, no name), extract the
    magnet type name from the second semicolon-delimited token of load_desc.
    Example:
        magnet_id = "B400A:"
        load_desc = "Magnet: B400A_slot_7; DMM_Q4; Resistance: ..."
        → returns "DMM_Q4"
    If magnet_id already has a name, returns it unchanged.
    """
    # Take this branch only when the stated operating condition is true.
    if not magnet_id.endswith(":"):
        # Hand the finished value back to the caller.
        return magnet_id
    # Do not judge full-load performance until the load is high enough to make that comparison meaningful.
    if not load_desc:
        # Hand the finished value back to the caller.
        return magnet_id
    # Capture parts here; the next step uses this intermediate result directly.
    parts = [p.strip() for p in load_desc.split(";")]
    # parts[0] = "Magnet: B400A_slot_7", parts[1] = "DMM_Q4", ...
    # Capture name here; the next step uses this intermediate result directly.
    name = parts[1] if len(parts) > 1 else ""
    # Hand the finished value back to the caller.
    return name if name else magnet_id


# ============================================================
# LOAD MAP LOOKUP
# ============================================================
_load_entry = None   # populated below if CABINET is set

if CABINET is not None:
    try:
        from cdcu_load_map import CdcuLoadMap, load_map_from_env_or_default
        _lm = load_map_from_env_or_default(default_path=LOAD_MAP_FILE)
        if _lm is not None:
            _load_entry = _lm.lookup_soft(CABINET, HOST, sector=SECTOR)
            if _load_entry:
                print(f"[cdcu_monitor] Load map resolved:")
                print(f"  Cabinet   : {CABINET}")
                print(f"  IP        : {HOST}")
                print(f"  Magnet ID : {_load_entry.get('magnet_id', '')}")
                print(f"  Load desc : {_load_entry.get('load_desc', '')}")
                print(f"  Raw V     : {_load_entry.get('raw_V', '')}")
                print(f"  Vout rating: {_load_entry.get('v_out_rating', '')}")
            else:
                print(f"[cdcu_monitor] WARNING: Cabinet '{CABINET}' / IP '{HOST}' "
                      f"not found in load map. Proceeding without load metadata.")
    except ImportError:
        print("[cdcu_monitor] cdcu_load_map.py not found. "
              "Proceeding without load metadata.")

# Convenience accessors used in metadata and plots
LOAD_DESC   = (_load_entry or {}).get("load_desc", "")
_raw_magnet_id = (_load_entry or {}).get("magnet_id", "")
# If magnet_id is bare (e.g. "B400A:"), extract the type name from load_desc
MAGNET_ID   = _magnet_name_from_load_desc(_raw_magnet_id, LOAD_DESC)
# NOTE: RAW_V is the "DC Bus:" display value shown in the live-plot footer,
# the CSV metadata header, and the PDF report identity block (meta["raw_V"]).
# It is a LIVE MEASURED quantity (the parsed #MRP:? register), not a load-map
# field — the load map has no "MRP" key, so the previous lookup here
# (_load_entry.get("MRP")) always silently returned None. It is set from a
# connect-time MRP:? query below, then refined to the run's mean measured
# value once the polling loop completes.
RAW_V       = None                                   # float or None — set from live MRP below
V_OUT_RATING = (_load_entry or {}).get("v_out_rating") # float or None
DCBUS_REF_V  = (_load_entry or {}).get("dcbus_ref_V")  # float or None
IDC_REF_A    = (_load_entry or {}).get("idc_ref_A")    # float or None

# Magnet nameplate values are carried by the load map. Existing APS load-map
# entries store resistance and inductance in load_desc; the helper also accepts
# future explicit numeric fields without changing the monitor.
if _MAGNET_DIAGNOSTICS_AVAILABLE:
    _MAGNET_NAMEPLATE = magnet_load_diagnostics.parse_nameplate(_load_entry)
    MAGNET_R_NAMEPLATE_OHM = _MAGNET_NAMEPLATE.resistance_ohm
    MAGNET_L_NAMEPLATE_H = _MAGNET_NAMEPLATE.inductance_h
else:
    MAGNET_R_NAMEPLATE_OHM = None
    MAGNET_L_NAMEPLATE_H = None

if MAGNET_R_NAMEPLATE_OHM is not None:
    print(f"[cdcu_monitor] Magnet nameplate R: {MAGNET_R_NAMEPLATE_OHM*1e3:.3f} mOhm")
if MAGNET_L_NAMEPLATE_H is not None:
    print(f"[cdcu_monitor] Magnet nameplate L: {MAGNET_L_NAMEPLATE_H*1e3:.3f} mH")

# ============================================================
# HELPERS
# ============================================================
def send_command(sock, command):
    # Capture full_command here; the next step uses this intermediate result directly.
    full_command = f"{command}:?\r".encode()
    # Carry out this step before advancing to the next part of the function.
    sock.sendall(full_command)
    # Initialize data as the working collection for this part of the run.
    data = sock.recv(1024)
    # Hand the finished value back to the caller.
    return data.decode(errors="replace").strip()

def parse_float(value):
    """
    Parse CDCU responses like:
        #MRP:39.26
        #MGPC:-0.53
        #MRV:5.1051512
        #MRI:74.999908
    """
    # Protect this hardware or file operation so a failure is reported without obscuring where it happened.
    try:
        # Capture text here; the next step uses this intermediate result directly.
        text = str(value).strip()
        # Take this branch only when the stated operating condition is true.
        if "NAK" in text or "ERR" in text or text == "":
            # Return NaN to mark this point unusable without inventing a numeric result.
            return math.nan
        # Take this branch only when the stated operating condition is true.
        if ":" in text:
            # Capture text here; the next step uses this intermediate result directly.
            text = text.split(":")[-1].strip()
        # Hand the finished value back to the caller.
        return float(text)
    except Exception:
        # Return NaN to mark this point unusable without inventing a numeric result.
        return math.nan

def safe_power(voltage, current):
    """Compute power magnitude = |V * I| when both inputs are valid."""
    # Reject invalid telemetry here; downstream math is only useful with finite values.
    if math.isnan(voltage) or math.isnan(current):
        # Return NaN to mark this point unusable without inventing a numeric result.
        return math.nan
    # Hand the finished value back to the caller.
    return abs(voltage * current)

def calculate_efficiency_percent(vout, iout, vbus, ibus):
    """
    Measured converter efficiency using power magnitudes:
        Pin  = |Vbus * Ibus|
        Pout = |Vout * Iout|
        eta% = 100 * Pout / Pin
    """
    # Reject invalid telemetry here; downstream math is only useful with finite values.
    if any(math.isnan(x) for x in [vout, iout, vbus, ibus]):
        # Return NaN to mark this point unusable without inventing a numeric result.
        return math.nan
    # Calculate DC input power from the measured bus voltage and current.
    pin = abs(vbus * ibus)
    # Calculate delivered output power from the measured output voltage and current.
    pout = abs(vout * iout)
    # Take this branch only when the stated operating condition is true.
    if pin <= 0:
        # Return NaN to mark this point unusable without inventing a numeric result.
        return math.nan
    # Hand the finished value back to the caller.
    return 100.0 * (pout / pin)

def clip_efficiency_percent(eff_pct, low=0.0, high=105.0):
    # Reject invalid telemetry here; downstream math is only useful with finite values.
    if math.isnan(eff_pct):
        # Return NaN to mark this point unusable without inventing a numeric result.
        return math.nan
    # Hand the finished value back to the caller.
    return max(low, min(high, eff_pct))


def _pct_and_ppm(pct):
    """Return (percent, ppm) for engineering reporting; 1% = 10,000 ppm."""
    # Reject invalid telemetry here; downstream math is only useful with finite values.
    if pct is None or (isinstance(pct, float) and math.isnan(pct)):
        # Return NaN to mark this point unusable without inventing a numeric result.
        return math.nan, math.nan
    # Hand the finished value back to the caller.
    return float(pct), float(pct) * 1.0e4


def _analyze_pmm_immediately(pmm_df, *, capture_kind, capture_index, timestamp,
                             run_dir, prefix, fault_order=None):
    """Immediately analyze one PMM capture and persist machine/human-readable summaries.

    This is intentionally called synchronously after BOTH the initial forced PMM and
    every hardware fault-triggered PMM capture. It does not wait for the end-of-run
    analysis. The returned dict is also retained for the final combined report.
    """
    # Make sure enough samples are available before running the calculation.
    if pmm_df is None or len(pmm_df) < 64:
        # Hand the finished value back to the caller.
        return {}
    # Protect this hardware or file operation so a failure is reported without obscuring where it happened.
    try:
        # Import this dependency locally because it is only needed on this execution path.
        import cdcu_ripple_psd as _pmm_psd
        # Import this dependency locally because it is only needed on this execution path.
        from cdcu_ripple_bands import BAND_STR
        # Import this dependency locally because it is only needed on this execution path.
        import math as _m

        # Build a deterministic label for this PMM capture and its analysis files.
        tag = f"{capture_kind}_{capture_index:02d}"
        # Resolve the directory where this analysis stage will write its products.
        outdir = _os.path.join(run_dir, "analysis", "pmm", tag)
        # Create the output directory now so the following writes have a valid destination.
        _os.makedirs(outdir, exist_ok=True)
        # Resolve the local APS/Argonne branding image used by the report output.
        logo = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                             "ANL_RGB-APS-fullname_horiz.png")
        # Capture col_map here; the next step uses this intermediate result directly.
        # PMM Set Current is intentionally not spectrally analyzed. The report slot is
        # reserved for the DCBus input-voltage/current spectral analysis when a valid
        # 10 kHz hardware-timed DCBus capture is available.
        col_map = {
            "vout_V": ("V", "PMM Output Voltage"),
            "iout_A": ("A", "PMM Output Current"),
        }
        # Start a clean result container for this analysis pass.
        results = {}
        # Walk the collection in order so every item receives the same treatment.
        for col, (unit, label) in col_map.items():
            # Take this branch only when the stated operating condition is true.
            if col not in pmm_df.columns:
                # Skip this item and continue with the next valid candidate.
                continue
            # Keep only the time axis and active PMM channel, then remove unusable rows.
            sub = pmm_df[["time_s", col]].dropna().reset_index(drop=True)
            # Make sure enough samples are available before running the calculation.
            if len(sub) < 64:
                # Skip this item and continue with the next valid candidate.
                continue
            # Resolve ppm against full scale when the CDCU model provides a rated quantity.
            dc = float(sub[col].mean())
            _spec = cdcu_diagnostics.get_model_spec(_MODEL_STR) if _DIAGNOSTICS_AVAILABLE else None
            if _spec and col in ("iout_A", "iset_A"):
                ppm_ref = float(_spec["rated_A"])
                ppm_ref_label = "full scale (rated current)"
            elif _spec and col == "vout_V":
                ppm_ref = float(_spec["rated_V"])
                ppm_ref_label = "full scale (rated voltage)"
            else:
                ppm_ref = dc if (_m.isfinite(dc) and dc != 0) else None
                ppm_ref_label = "operating point (DC mean)" if ppm_ref is not None else "undefined"
            # Resolve ch_dir once so later file operations use the same location.
            ch_dir = _os.path.join(outdir, col)
            # Capture comp here; the next step uses this intermediate result directly.
            comp = _os.path.join(ch_dir, f"{prefix}_{tag}_{col}_report.png")
            # Capture res here; the next step uses this intermediate result directly.
            res = _pmm_psd.analyze_series_for_reports(
                df=sub, time_col="time_s", value_col=col, outdir=ch_dir,
                ppm_ref=ppm_ref, ppm_ref_label=ppm_ref_label, bands=BAND_STR, sig_threshold_ppm=12.0,
                label=label, quantity_unit=unit, window="hann",
                nperseg=_pmm_psd.recommended_welch_nperseg(len(sub), target=16384), overlap=0.5,
                auto_scale_freq=True, load_desc=LOAD_DESC or None,
                acq_timestamp=timestamp or None, logo_path=logo,
                composite_png=comp, file_prefix=f"{prefix}_{tag}",
            )
            # Capture results[col] here; the next step uses this intermediate result directly.
            results[col] = res

        # Assemble the capture metadata and analysis results into one record.
        summary = {
            "capture_kind": capture_kind,
            "capture_index": capture_index,
            "timestamp": timestamp or "",
            "sample_count": int(len(pmm_df)),
            "fault_cascade": list(fault_order or []),
            "fault_occurred": bool(fault_order),
            "channels_analyzed": list(results.keys()),
        }
        # Include compact metrics returned by analyzer when JSON serializable.
        def clean(v):
            # Take this branch only when the stated operating condition is true.
            if isinstance(v, dict): return {str(k): clean(x) for k,x in v.items()}
            # Take this branch only when the stated operating condition is true.
            if isinstance(v, (list, tuple)): return [clean(x) for x in v]
            # Take this branch only when the stated operating condition is true.
            if isinstance(v, (str, int, bool)) or v is None: return v
            # Protect this hardware or file operation so a failure is reported without obscuring where it happened.
            try:
                # Capture f here; the next step uses this intermediate result directly.
                f=float(v)
                # Hand the finished value back to the caller.
                return f if math.isfinite(f) else None
            except Exception:
                # Hand the finished value back to the caller.
                return str(v)
        # Capture summary["analysis"] here; the next step uses this intermediate result directly.
        summary["analysis"] = clean(results)
        # Build the JSON-summary path for this capture.
        js = _os.path.join(outdir, f"{prefix}_{tag}_summary.json")
        # Use a context manager so the file or resource is closed cleanly on every exit path.
        with open(js, "w", encoding="utf-8") as fh:
            # Carry out this step before advancing to the next part of the function.
            json.dump(summary, fh, indent=2)
        # Build the text-summary path for this capture.
        txt = _os.path.join(outdir, f"{prefix}_{tag}_summary.txt")
        # Use a context manager so the file or resource is closed cleanly on every exit path.
        with open(txt, "w", encoding="utf-8") as fh:
            # Write this field to the report in the same order an engineer will review it.
            fh.write(f"PMM capture: {capture_kind} #{capture_index}\n")
            # Write this field to the report in the same order an engineer will review it.
            fh.write(f"Timestamp: {timestamp or 'unknown'}\n")
            # Write this field to the report in the same order an engineer will review it.
            fh.write(f"Samples: {len(pmm_df)}\n")
            # Act only when this fault condition is present at this point in the sequence.
            if fault_order:
                # Write this field to the report in the same order an engineer will review it.
                fh.write("FAULT OCCURRED: YES\n")
                # Write this field to the report in the same order an engineer will review it.
                fh.write("Fault cascade (first observed -> last observed):\n")
                # Walk the collection in order so every item receives the same treatment.
                for i, name in enumerate(fault_order, 1):
                    # Write this field to the report in the same order an engineer will review it.
                    fh.write(f"  {i}. {name}\n")
            else:
                # State the role of a non-fault PMM without implying that every non-fault
                # capture is the startup baseline.
                if capture_kind == "initial":
                    fh.write("FAULT OCCURRED: NO (startup baseline PMM)\n")
                elif capture_kind == "final":
                    fh.write("FAULT OCCURRED: NO (end-of-run comparison PMM)\n")
                else:
                    fh.write("FAULT OCCURRED: NO\n")
            # Write this field to the report in the same order an engineer will review it.
            fh.write(f"Channels analyzed: {', '.join(results) or 'none'}\n")
        # Write this status to the console so the operator can follow the run in real time.
        print(f"[cdcu_monitor] Immediate PMM analysis complete: {txt}")
        # Hand the finished value back to the caller.
        return {"summary": summary, "results": results, "dir": outdir}
    except Exception as exc:
        # Write this status to the console so the operator can follow the run in real time.
        print(f"[cdcu_monitor] Immediate PMM analysis failed: {exc}")
        # Hand the finished value back to the caller.
        return {"error": str(exc)}

# ============================================================
# DATA STORAGE
# ============================================================
time_data  = deque(maxlen=MAX_POINTS)
mrp_data   = deque(maxlen=MAX_POINTS)
mgpc_data  = deque(maxlen=MAX_POINTS)
mrv_data   = deque(maxlen=MAX_POINTS)
mri_data   = deque(maxlen=MAX_POINTS)
pin_data   = deque(maxlen=MAX_POINTS)
pout_data  = deque(maxlen=MAX_POINTS)
eff_data   = deque(maxlen=MAX_POINTS)
ibus_err_data = deque(maxlen=MAX_POINTS)   # diagnostic: IBUS_pct_error history
raw_history = {cmd: deque(maxlen=MAX_POINTS) for cmd in commands}
# Generic numeric histories support user-added live signals without requiring
# another code change elsewhere in the monitor.
signal_data = {
    cmd: deque(maxlen=MAX_POINTS)
    for cmd, cfg in SIGNALS.items()
    if cfg.get("numeric", False)
}

# ============================================================
# LIVE PLOT SETUP
# ============================================================
import matplotlib
if _HEADLESS:
    matplotlib.use("Agg")   # non-interactive backend — no window, no display needed

plt.ion()
fig, axes = plt.subplots(4, 1, figsize=(14, 13.5), sharex=True)

# ── Title block ───────────────────────────────────────────────────────────
# Primary title: magnet ID (or fallback to IP)
plot_title = MAGNET_ID if MAGNET_ID else f"CDCU Live — {HOST}"
fig.suptitle(plot_title, fontsize=14, fontweight="bold", y=0.985)

# Secondary subtitle: load description — positioned below suptitle with clear gap
if LOAD_DESC:
    fig.text(0.5, 0.952, LOAD_DESC, ha="center", fontsize=9,
             color="dimgray", style="italic")

line_pin,  = axes[0].plot([], [], label="Pin = |MRP × MGPC| (W)")
line_pout, = axes[0].plot([], [], label="Pout = |MRV × MRI| (W)")
axes[0].set_title("Power", loc="left", fontsize=10)
axes[0].set_ylabel("Power (W)")
axes[0].grid(True)
axes[0].legend(loc="upper left")

# Build the Electrical Values panel from SIGNALS rather than hard-coding four
# traces.  A newly added numeric signal appears here when plot=True.
electrical_lines = {}
for _cmd, _cfg in SIGNALS.items():
    if not (_cfg.get("numeric", False) and _cfg.get("plot", False)):
        continue
    _unit = _cfg.get("unit", "")
    _legend = f"{_cmd} ({_cfg.get('label', _cmd)})"
    if _unit:
        _legend += f" [{_unit}]"
    electrical_lines[_cmd], = axes[1].plot([], [], label=_legend)
axes[1].set_title("Electrical Values", loc="left", fontsize=10)
axes[1].set_ylabel("Measured Value")
axes[1].grid(True)
if electrical_lines:
    axes[1].legend(loc="upper left")

line_eff,  = axes[2].plot([], [], label="Efficiency (%) [clipped 0–105]",
                           color="blue")
axes[2].set_title("Efficiency", loc="left", fontsize=10)
axes[2].set_ylabel("Efficiency (%)")
axes[2].set_ylim(0, 105)
axes[2].grid(True)
axes[2].legend(loc="upper left")

# The temperature channels share a dedicated fourth panel in the same live
# monitor window.  Keeping temperatures on their own axis preserves a useful
# °C scale while allowing the operator to review power, electrical values,
# efficiency, and thermal behavior without moving between windows.
temperature_lines = {}
for _cmd, _cfg in SIGNALS.items():
    if not (_cfg.get("numeric", False) and _cfg.get("temperature_plot", False)):
        continue
    _legend = f"{_cmd} — {_cfg.get('label', _cmd)}"
    temperature_lines[_cmd], = axes[3].plot([], [], label=_legend)

axes[3].set_title("CDCU Internal Temperatures", loc="left", fontsize=10)
axes[3].set_xlabel("Time (s)")
axes[3].set_ylabel("Temperature (°C)")
axes[3].grid(True)
if temperature_lines:
    axes[3].legend(loc="upper left")

# Leave room at the bottom for the footer (logo + metadata + timestamp).
fig.tight_layout(rect=[0, 0.10, 1, 0.945])

# ============================================================
# MAIN
# ============================================================
run_start_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
_live_start_mono = None
_live_actual_duration_s = math.nan

print("\n── Runtime Configuration ─────────────────────────────────────")
print(f"[runtime] Program start: {_PROGRAM_START_LOCAL.strftime('%Y-%m-%d %H:%M:%S')}")
print(f"[runtime] Live plot/data duration setting: {_format_runtime(DURATION)}")
print(f"[runtime] Poll interval setting: {INTERVAL:.6f} s")

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.settimeout(SOCKET_TIMEOUT)
    s.connect((HOST, PORT))

    # ── Optional MRID write-back ──────────────────────────────────────────
    if WRITE_MRID_ON_CONNECT and MAGNET_ID:
        try:
            # Elevate to admin, write Module ID, save to non-volatile memory
            for cmd in [f"PASSWORD:PS-ADMIN", f"MWG:30:{MAGNET_ID}", "MSAVE", "PASSWORD:USER"]:
                s.sendall(f"{cmd}\r".encode())
                resp = s.recv(1024).decode(errors="replace").strip()
                print(f"[cdcu_monitor] MRID write-back '{cmd}' -> {resp}")
        except Exception as exc:
            print(f"[cdcu_monitor] MRID write-back failed: {exc}")

    # ── Query VER + SN on connect (before CSV/PNG paths are finalized) ─────────
    # VER response:  #VER:3.1.4   → version = "3.1.4"
    # SN response:   #SN:CDCU-300:19Y0002  → model = "CDCU-300", sn = "19Y0002"
    _VER_RAW = ""
    _SN_EARLY = ""
    _SN_FULL  = ""   # e.g. "CDCU-300:19Y0002"
    _VER_STR = ""    # e.g. "3.1.4"
    _MODEL_STR = ""  # e.g. "CDCU-300"
    try:
        _ver_resp = ""
        _sn_resp_early = ""
        s.sendall(b"VER:?\r"); import time as _t2; _t2.sleep(0.05)
        _ver_resp = s.recv(1024).decode(errors="replace").strip()
        s.sendall(b"SN:?\r");  _t2.sleep(0.05)
        _sn_resp_early = s.recv(1024).decode(errors="replace").strip()
        s.sendall(b"MRP:?\r"); _t2.sleep(0.05)
        _mrp_resp_early = s.recv(1024).decode(errors="replace").strip()

        # Parse VER: #VER:3.1.4
        if _ver_resp and "NAK" not in _ver_resp and "ERR" not in _ver_resp:
            _VER_RAW = _ver_resp
            _VER_STR = _ver_resp.split(":")[-1].strip()

        # Parse SN: #SN:CDCU-300:19Y0002
        # _MODEL_STR = "CDCU-300"  _SN_EARLY = "19Y0002"
        # _SN_FULL   = "CDCU-300:19Y0002"  (used in title)
        if _sn_resp_early and "NAK" not in _sn_resp_early and "ERR" not in _sn_resp_early:
            _sn_parts = _sn_resp_early.lstrip("#").split(":", 2)
            # _sn_parts = ["SN", "CDCU-300", "19Y0002"]
            if len(_sn_parts) >= 3:
                _MODEL_STR = _sn_parts[1].strip()
                _SN_EARLY  = _sn_parts[2].strip()
                _SN_FULL   = f"{_MODEL_STR}:{_SN_EARLY}"
            elif len(_sn_parts) == 2:
                _SN_EARLY = _sn_parts[1].strip()
                _SN_FULL  = _SN_EARLY
            else:
                _SN_FULL = ""

        # Parse MRP: #MRP:39.26 -> live DC-bus voltage at connect time.
        # Seeds RAW_V ("DC Bus:" display value) with a real live measurement
        # instead of the old (always-None) load-map lookup. Refined again to
        # the run's mean measured value after the polling loop completes.
        _mrp_early = parse_float(_mrp_resp_early)
        if not math.isnan(_mrp_early):
            RAW_V = _mrp_early

        print(f"[cdcu_monitor] VER: {_VER_STR or '(unknown)'}  "
              f"Model: {_MODEL_STR or '(unknown)'}  "
              f"SN: {_SN_EARLY or '(unknown)'}  "
              f"DCBUS V (connect): "
              f"{f'{RAW_V:.3f}' if RAW_V is not None else '(unknown)'}")
    except Exception as _ver_exc:
        print(f"[cdcu_monitor] VER/SN/MRP query failed: {_ver_exc}")

    # ── Diagnostics setup: per-model efficiency reference + plateau detector ──
    # eta_reference: used in the I_IN,expected power-balance model. A
    # per-supply override can be supplied via an optional "eta_reference_pct"
    # field in load_map_with_magnetid.json (0-100); absent by default, in
    # which case the per-model nameplate table in cdcu_diagnostics.py is used.
    _eta_override_raw = (_load_entry or {}).get("eta_reference_pct")
    try:
        _ETA_OVERRIDE_FRAC = (
            float(_eta_override_raw) / 100.0
            if _eta_override_raw not in (None, "") else None
        )
    except (TypeError, ValueError):
        _ETA_OVERRIDE_FRAC = None

    if _DIAGNOSTICS_AVAILABLE:
        try:
            _ETA_REFERENCE, _ETA_REFERENCE_SOURCE = cdcu_diagnostics.eta_reference_details(
                _MODEL_STR, override=_ETA_OVERRIDE_FRAC)
        except ValueError as _eta_exc:
            print(f"[cdcu_monitor] WARNING: {_eta_exc}; ignoring invalid override.")
            _ETA_REFERENCE, _ETA_REFERENCE_SOURCE = cdcu_diagnostics.eta_reference_details(
                _MODEL_STR, override=None)
        _INVESTIGATE_BELOW = cdcu_diagnostics.investigate_threshold_for_model(_MODEL_STR)
        _INVESTIGATE_BELOW_PCT = (_INVESTIGATE_BELOW * 100.0
                                  if not math.isnan(_INVESTIGATE_BELOW) else math.nan)
        _plateau = cdcu_diagnostics.PlateauDetector()
        print(f"[cdcu_monitor] Diagnostics: model={_MODEL_STR or '(unknown)'}  "
              f"eta_reference={_ETA_REFERENCE * 100.0:.2f}% "
              f"({_ETA_REFERENCE_SOURCE})  "
              f"CAEN full-load minimum={_INVESTIGATE_BELOW_PCT:.2f}%")
    else:
        _ETA_REFERENCE = math.nan
        _ETA_REFERENCE_SOURCE = "unknown"
        _INVESTIGATE_BELOW_PCT = math.nan
        _plateau = None
        print("[cdcu_monitor] cdcu_diagnostics.py not found — "
              "I_IN_expected/%Error/efficiency-health diagnostics disabled.")

    # Fault-edge tracking for immediate PMM re-acquisition on trip (see
    # _pmm_obj usage inside the polling loop below).
    _was_faulted = False
    _fault_event_count = 0
    _seen_fault_names = set()
    _fault_cascade = []            # ordered by first observation
    _fault_first_seen_s = {}
    _pmm_capture_analyses = []

    # ── Derive structured run directory and shared filename prefix ────────────
    # Directory: {OUTDIR}/{SN_FULL}/{SECTOR}/{CABINET}/
    # Prefix:    {SN_FULL}_{SECTOR}_{CABINET}_{HOST}_{TIMESTAMP}
    #
    # Every file this run produces uses the same prefix so they sort and
    # identify together:
    #   {PREFIX}.csv
    #   {PREFIX}_live.png
    #   reports/{PREFIX}_combined.pdf
    #   reports/{PREFIX}_ripple_summary.pdf  etc.
    #   analysis/{PREFIX}_MRV_float_fft.png  etc.
    #   analysis/pmm/{PREFIX}_pmm_vout_V_fft.png  etc.

    _ts_tag    = datetime.now().strftime("%Y%m%d_%H%M%S")
    # SN_FULL for directory name: use hyphen form (CDCU-300:19Y0002 → CDCU-300_19Y0002)
    _sn_dir    = (_SN_FULL or _SN_EARLY or "SN").replace(":", "_")
    _sec_dir   = SECTOR  or "noSector"
    _cab_dir   = CABINET or "noCabinet"
    _host_tag  = HOST.replace(".", "_")
    # Prefix uses the same SN dir form so filenames match their folder path
    _PREFIX    = f"{_sn_dir}_{_sec_dir}_{_cab_dir}_{_host_tag}_{_ts_tag}"
    # Structured run directory: {OUTDIR}/{SN}/{SECTOR}/{CABINET}/
    _RUN_DIR   = _os.path.join(_OUTDIR, _sn_dir, _sec_dir, _cab_dir)
    _os.makedirs(_RUN_DIR, exist_ok=True)
    CSV_FILE  = _os.path.join(_RUN_DIR, f"{_PREFIX}.csv")
    PNG_FILE  = _os.path.join(_RUN_DIR, f"{_PREFIX}_live.png")

    # ── Update live plot title: {SECTOR} {CABINET} {HOST} {full SN} {VER} ─────
    _title_parts = [p for p in [SECTOR, CABINET, HOST,
                                 _SN_FULL, _VER_STR] if p]
    _title_initial = "  ".join(_title_parts) if _title_parts else f"CDCU Live — {HOST}"
    fig.suptitle(_title_initial, fontsize=12, fontweight="bold", y=0.985)
    if not _HEADLESS:
        plt.pause(0.001)

    # ── PMM acquisition — runs FIRST, before polling loop ────────────────────
    # Sequence: arm → wait for trigger → fetch → rearm → then polling starts.
    # The socket remains open throughout; polling starts immediately after
    # PMM completes (or times out) regardless of outcome.
    _pmm_df        = None
    _pmm_timestamp = ""
    _pmm_results   = {}
    _pmm_obj       = None   # set below if RUN_PMM succeeds; reused in the
                             # polling loop for fault-triggered re-acquisition
    _final_pmm_forced = False
    _final_pmm_force_time = None

    if RUN_PMM:
        try:
            from cdcu_pmm import PmmAcquisition, PMM_FS_HZ, PMM_CHANNELS
            print(f"\n── PMM Acquisition ─────────────────────────────────────────────")
            print(f"[cdcu_monitor] PMM:RESET → PMM:FORCE → fetch  "
                  f"(pre={PMM_PRE_FAULT_S:.1f}s  timeout={PMM_WAIT_TIMEOUT:.0f}s)")
            _pmm_obj = PmmAcquisition(s, recv_timeout=30.0)
            _pmm_obj.set_trigger_position(PMM_PRE_FAULT_S)
            if _pmm_obj.arm():
                print("[cdcu_monitor] PMM armed. Sending PMM:FORCE ...")
                if _pmm_obj.force():
                    print(f"[cdcu_monitor] PMM:FORCE sent. "
                          f"Waiting up to {PMM_WAIT_TIMEOUT:.0f}s for READY=1 ...")
                    if _pmm_obj.wait_ready(timeout=PMM_WAIT_TIMEOUT, verbose=True):
                        _pmm_timestamp = _pmm_obj.timestamp()
                        _pmm_df = _pmm_obj.fetch_dataframe()
                        print(f"[cdcu_monitor] PMM fetched: {len(_pmm_df)} samples "
                              f"at {PMM_FS_HZ:.0f} Hz")
                        if _pmm_timestamp:
                            print(f"[cdcu_monitor] PMM timestamp: {_pmm_timestamp}")
                        # Save the baseline PMM capture as a normal CSV so it can be
                        # re-analyzed later without reconnecting to the power supply.
                        _baseline_pmm_dir = _os.path.join(_RUN_DIR, "pmm_captures")
                        _os.makedirs(_baseline_pmm_dir, exist_ok=True)
                        _baseline_pmm_csv = _os.path.join(
                            _baseline_pmm_dir, f"{_PREFIX}_initial_pmm.csv")
                        _pmm_df.to_csv(_baseline_pmm_csv, index=False)
                        print(f"[cdcu_monitor] Initial PMM CSV saved: {_baseline_pmm_csv}")
                        # User requirement: first PMM sample is ALWAYS analyzed immediately.
                        _initial_analysis = _analyze_pmm_immediately(
                            _pmm_df, capture_kind="initial", capture_index=1,
                            timestamp=_pmm_timestamp, run_dir=_RUN_DIR, prefix=_PREFIX,
                            fault_order=None)
                        _pmm_capture_analyses.append(_initial_analysis)
                        _pmm_obj.arm()   # rearm for hardware fault trigger
                        print("[cdcu_monitor] PMM rearmed.")
                    else:
                        print(f"[cdcu_monitor] PMM:READY timed out after "
                              f"{PMM_WAIT_TIMEOUT:.0f}s — no PMM data captured.")
                else:
                    print("[cdcu_monitor] PMM:FORCE NAK — skipping PMM.")
            else:
                print("[cdcu_monitor] PMM:RESET NAK — skipping PMM.")
            # PmmAcquisition's _send_recv() leaves the socket timeout at
            # whatever the last PMM command needed (up to 30s for the large
            # fetch payloads). Restore SOCKET_TIMEOUT before the polling loop
            # starts so send_command()'s per-burst recv() behaves as
            # configured, not with a stale PMM timeout.
            s.settimeout(SOCKET_TIMEOUT)
            print("[cdcu_monitor] Starting polling loop ...")
        except ImportError:
            print("[cdcu_monitor] cdcu_pmm.py not found — PMM skipped.")
        except Exception as _pmm_exc:
            print(f"[cdcu_monitor] PMM acquisition error: {_pmm_exc}")
    else:
        print("[cdcu_monitor] PMM DISABLED (RUN_PMM=False)")

    # The configured DURATION applies to the live polling/plot data window itself.
    # Startup connection and initial PMM acquisition do not consume this interval.
    start_time = time.time()
    end_time = start_time + DURATION
    _live_start_mono = time.perf_counter()
    _live_start_local = datetime.now()
    print("\n── Live Plot / Polling Window ────────────────────────────────")
    print(f"[runtime] Live polling start: {_live_start_local.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"[runtime] Configured live duration: {_format_runtime(DURATION)}")

    with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:

        # ── Metadata header (# key = value lines) ─────────────────────────
        # These are read back by cdcu_ripple_analyzer and cdcu_ripple_io.
        f.write(f"# FORMAT = CDCU_MONITOR_CSV v1\n")
        f.write(f"# run_start_utc = {datetime.now(timezone.utc).isoformat()}\n")
        f.write(f"# run_start_local = {run_start_iso}\n")
        f.write(f"# host = {HOST}\n")
        f.write(f"# cabinet = {CABINET or ''}\n")
        f.write(f"# sector = {SECTOR}\n")
        f.write(f"# magnet_id = {MAGNET_ID}\n")
        if _VER_STR:
            f.write(f"# firmware_ver = {_VER_STR}\n")
        if _SN_EARLY:
            f.write(f"# serial_number = {_SN_EARLY}\n")
        if _MODEL_STR:
            f.write(f"# model = {_MODEL_STR}\n")
        f.write(f"# load_desc = {LOAD_DESC}\n")
        if RAW_V is not None:
            f.write(f"# raw_V = {RAW_V}\n")
        if V_OUT_RATING is not None:
            f.write(f"# v_out_rating = {V_OUT_RATING}\n")
        if DCBUS_REF_V is not None:
            f.write(f"# dcbus_ref_V = {DCBUS_REF_V}\n")
        if IDC_REF_A is not None:
            f.write(f"# idc_ref_A = {IDC_REF_A}\n")
        if MAGNET_R_NAMEPLATE_OHM is not None:
            f.write(f"# magnet_resistance_nameplate_ohm = {MAGNET_R_NAMEPLATE_OHM}\n")
        if MAGNET_L_NAMEPLATE_H is not None:
            f.write(f"# magnet_inductance_nameplate_H = {MAGNET_L_NAMEPLATE_H}\n")
        # ppm reference values for ripple analysis
        # vout_ref and idc_ref are used instead of DC-mean when available
        if V_OUT_RATING is not None:
            f.write(f"# vout_rating_V = {V_OUT_RATING}\n")
        if RAW_V is not None:
            f.write(f"# bus_voltage_V = {RAW_V}\n")
        f.write("\n")

        writer = csv.writer(f)

        header = [
            "burst_start_s",
            "burst_end_s",
            "burst_midpoint_s",          # ← time column used by cdcu_ripple_analyzer
            "burst_duration_s",
        ] + [f"{cmd}_raw" for cmd in commands] + [
            f"{cmd.replace(':', '_')}_float" for cmd in temperature_commands
        ] + [
            "MRP_float",                 # ← analyzed: DC bus voltage (V)
            "MGPC_float",               # ← analyzed: input current (A)
            "MRV_float",                # ← analyzed: output voltage (V)
            "MRI_float",                # ← analyzed: output current (A)
            "Pin_W",                    # ← analyzed: input power (W)
            "Pout_W",                   # ← analyzed: output power (W)
            "Efficiency_pct_raw",
            "Efficiency_pct_clipped",
            "I_IN_expected_A",           # ← diagnostic: power-balance expected input current
            "IBUS_delta_A",              # ← diagnostic: MGPC - I_IN_expected
            "IBUS_pct_error",
            "IBUS_error_ppm",
            "load_fraction",
            "load_fraction_pct",
            "is_steady_state",
            "diagnostic_valid",
            "diagnostic_state",
            "diagnostic_confidence",
            "eta_reference_pct",
            "eta_reference_source",
            "eta_full_load_min_pct",
            "caen_full_load_compliance_valid",
            "caen_efficiency_compliance",
            "efficiency_delta_from_reference_pct_points",
            "efficiency_delta_from_reference_abs_ppm",
            "efficiency_delta_from_reference_relative_ppm",
            "efficiency_margin_to_CAEN_pct_points",
            "efficiency_margin_to_CAEN_abs_ppm",
            "efficiency_margin_to_CAEN_relative_ppm",
            "power_loss_W",
            "power_loss_pct",
            "power_loss_ppm",
            "power_balance_anomaly",
            "Magnet_R_measured_ohm",
            "Magnet_R_measured_mOhm",
            "Magnet_R_nameplate_ohm",
            "Magnet_R_delta_mOhm",
            "Magnet_R_error_pct",
            "Magnet_R_error_ppm",
            "Magnet_dIdt_A_per_s",
            "is_magnet_cycling",
            "Magnet_L_estimated_H",
            "Magnet_L_estimated_mH",
            "Magnet_L_nameplate_H",
            "Magnet_L_delta_mH",
            "Magnet_L_error_pct",
            "Magnet_L_error_ppm",
            "Efficiency_health",
        ]
        writer.writerow(header)

        _health_counts = {"healthy": 0, "investigate": 0}
        _valid_eff_data = []
        _investigate_start_s = None
        _max_investigate_duration_s = 0.0
        # Magnet characterization histories are kept separately from converter
        # efficiency diagnostics. Resistance uses steady-state points; inductance
        # uses ramp points and is expected to be noisier because it comes from live polling.
        _magnet_r_samples = []
        _magnet_l_samples = []
        # Robust steady-state DCBus characterization samples used in the magnet text report.
        _steady_dcbus_v_samples = []
        _steady_dcbus_i_samples = []
        _steady_dcbus_p_samples = []
        # Steady-state output-side power and measured converter efficiency use
        # the same meaningful-load gate as the DCBus characterization.
        _steady_output_p_samples = []
        _steady_efficiency_pct_samples = []
        _prev_magnet_t_s = math.nan
        _prev_magnet_i_a = math.nan
        _prev_plot_t_s = math.nan

        while time.time() < end_time:
            loop_start = time.time()

            burst_start_abs = time.time()
            results = {}

            for cmd in commands:
                try:
                    value = send_command(s, cmd)
                except Exception:
                    value = "ERR"
                results[cmd] = value
                raw_history[cmd].append(value)

            burst_end_abs = time.time()

            burst_start   = burst_start_abs - start_time
            burst_end     = burst_end_abs   - start_time
            burst_midpoint = 0.5 * (burst_start + burst_end)
            burst_duration = burst_end - burst_start

            mrp  = parse_float(results.get("MRP", ""))
            mgpc = parse_float(results.get("MGPC", ""))
            mrv  = parse_float(results.get("MRV", ""))
            mri  = parse_float(results.get("MRI", ""))

            # Parse every user-selected numeric signal once per burst.  Core
            # channels above use the same replies for the engineering math.
            for _cmd, _history in signal_data.items():
                _history.append(parse_float(results.get(_cmd, "")))

            pin  = safe_power(mrp, mgpc)
            pout = safe_power(mrv, mri)

            eff_raw     = calculate_efficiency_percent(vout=mrv, iout=mri, vbus=mrp, ibus=mgpc)
            eff_clipped = clip_efficiency_percent(eff_raw, low=0.0, high=105.0)

            # ── Engineering diagnostics: steady-state + substantial-load gated ──
            if _DIAGNOSTICS_AVAILABLE:
                _is_steady = _plateau.update(burst_midpoint, mri)
                _telemetry_valid = all(math.isfinite(x) for x in (mrp, mgpc, mrv, mri, pin, pout, eff_raw))
                _model_spec = cdcu_diagnostics.get_model_spec(_MODEL_STR)
                _model_known = _model_spec is not None
                _load_fraction = cdcu_diagnostics.calculate_load_fraction(_MODEL_STR, pout)
                _is_substantial_load = cdcu_diagnostics.substantial_load(_MODEL_STR, pout)
                _diagnostic_valid = bool(_telemetry_valid and _model_known and _is_steady and
                                         _is_substantial_load and math.isfinite(_ETA_REFERENCE))
                if _diagnostic_valid:
                    _i_in_expected = cdcu_diagnostics.expected_input_current(
                        v_out=mrv, i_out=mri, v_bus=mrp, eta_reference=_ETA_REFERENCE)
                    _ibus_delta, _ibus_pct_error = cdcu_diagnostics.bus_current_percent_error(
                        i_bus_actual=mgpc, i_bus_expected=_i_in_expected)
                    _eff_health = cdcu_diagnostics.efficiency_health(eff_raw, _ETA_REFERENCE)
                else:
                    _i_in_expected = math.nan
                    _ibus_delta = math.nan
                    _ibus_pct_error = math.nan
                    _eff_health = "invalid" if not _telemetry_valid else (
                        "unknown_model" if not _model_known else (
                        "transient" if not _is_steady else "low_load"))
                _diagnostic_state = cdcu_diagnostics.diagnostic_state(
                    telemetry_valid=_telemetry_valid, model_known=_model_known,
                    is_steady=_is_steady, is_substantial_load=_is_substantial_load,
                    health=_eff_health)
                _diagnostic_confidence = cdcu_diagnostics.diagnostic_confidence(
                    _ETA_REFERENCE_SOURCE, _diagnostic_valid)
                _ibus_error_ppm = cdcu_diagnostics.percent_to_ppm(_ibus_pct_error)
                _eta_ref_pct = _ETA_REFERENCE * 100.0 if math.isfinite(_ETA_REFERENCE) else math.nan
                _eta_min_pct = (_model_spec["eta_full_load_min"] * 100.0
                                if _model_spec else math.nan)
                _eff_delta_ref_pct = eff_raw - _eta_ref_pct if (_diagnostic_valid and math.isfinite(eff_raw)) else math.nan
                # Absolute fractional ppm is percentage-point delta × 10,000.
                _eff_delta_ref_ppm = cdcu_diagnostics.percent_point_delta_to_abs_ppm(_eff_delta_ref_pct)
                # Relative ppm uses the selected efficiency baseline as the denominator.
                _eff_delta_ref_relative_ppm = cdcu_diagnostics.relative_percent_difference_ppm(eff_raw, _eta_ref_pct) if _diagnostic_valid else math.nan
                if _telemetry_valid and _model_known and _is_steady:
                    _caen_compliance = cdcu_diagnostics.caen_efficiency_compliance(_MODEL_STR, eff_raw, _load_fraction)
                else:
                    _caen_compliance = "not_applicable"
                _caen_compliance_valid = _caen_compliance in ("pass", "fail")
                _eff_margin_caen_pct = eff_raw - _eta_min_pct if (_caen_compliance_valid and math.isfinite(eff_raw)) else math.nan
                _eff_margin_caen_ppm = cdcu_diagnostics.percent_point_delta_to_abs_ppm(_eff_margin_caen_pct)
                _eff_margin_caen_relative_ppm = cdcu_diagnostics.relative_percent_difference_ppm(eff_raw, _eta_min_pct) if _caen_compliance_valid else math.nan
                _power_loss_w, _power_loss_pct = cdcu_diagnostics.power_loss(pin, pout) if _diagnostic_valid else (math.nan, math.nan)
                _power_loss_ppm = cdcu_diagnostics.percent_to_ppm(_power_loss_pct)
                _power_balance_anomaly = bool(_diagnostic_valid and (
                    (math.isfinite(_ibus_pct_error) and abs(_ibus_pct_error) >= cdcu_diagnostics.MAX_IBUS_PCT_ERROR_WARNING) or
                    (math.isfinite(_eff_delta_ref_pct) and abs(_eff_delta_ref_pct) >= cdcu_diagnostics.MAX_EFFICIENCY_DEVIATION_PCT_POINTS)))
            else:
                _i_in_expected = _ibus_delta = _ibus_pct_error = _ibus_error_ppm = math.nan
                _load_fraction = math.nan
                _is_steady = _diagnostic_valid = _power_balance_anomaly = False
                _diagnostic_state = _diagnostic_confidence = "unavailable"
                _eta_ref_pct = _eta_min_pct = math.nan
                _eff_delta_ref_pct = _eff_delta_ref_ppm = _eff_delta_ref_relative_ppm = math.nan
                _eff_margin_caen_pct = _eff_margin_caen_ppm = _eff_margin_caen_relative_ppm = math.nan
                _caen_compliance = "unavailable"
                _caen_compliance_valid = False
                _power_loss_w = _power_loss_pct = _power_loss_ppm = math.nan
                _eff_health = "unavailable"
                _caen_compliance = "unavailable"
                _caen_compliance_valid = False

            # Capture steady-state DCBus operating points for the magnet characterization report.
            # Use the same meaningful-current gate as the resistance characterization so an
            # idle/near-zero plateau does not dominate the reported DCBus operating point.
            _rated_i_for_bus = ((_model_spec or {}).get("rated_A", 0.0)
                                if _DIAGNOSTICS_AVAILABLE else 0.0)
            _min_bus_characterization_current = max(1.0, 0.10 * float(_rated_i_for_bus or 0.0))
            if (_is_steady and math.isfinite(mri) and abs(mri) >= _min_bus_characterization_current
                    and all(math.isfinite(v) for v in (mrp, mgpc, pin))):
                _steady_dcbus_v_samples.append(mrp)
                _steady_dcbus_i_samples.append(mgpc)
                _steady_dcbus_p_samples.append(pin)
                if math.isfinite(pout):
                    _steady_output_p_samples.append(pout)
                if math.isfinite(eff_raw):
                    _steady_efficiency_pct_samples.append(eff_raw)

            # ── Magnet load characterization ─────────────────────────────────
            # At a steady current plateau V/I is the magnet's DC resistance.
            # During a ramp V = R*I + L*dI/dt, so the same measurements can
            # provide an inductance estimate when dI/dt is large enough.
            _mag_r_measured = math.nan
            _mag_r_delta_ohm = math.nan
            _mag_r_error_pct = math.nan
            _mag_r_error_ppm = math.nan
            _mag_didt = math.nan
            _mag_l_estimated_h = math.nan
            _mag_l_delta_h = math.nan
            _mag_l_error_pct = math.nan
            _mag_l_error_ppm = math.nan

            if _MAGNET_DIAGNOSTICS_AVAILABLE and math.isfinite(mri) and math.isfinite(mrv):
                if _is_steady:
                    _rated_i_for_r = ((_model_spec or {}).get("rated_A", 0.0)
                                      if _DIAGNOSTICS_AVAILABLE else 0.0)
                    _min_r_current = max(1.0, 0.10 * float(_rated_i_for_r or 0.0))
                    _mag_r_measured = magnet_load_diagnostics.measured_resistance(
                        mrv, mri, min_abs_current_a=_min_r_current)
                    if math.isfinite(_mag_r_measured):
                        _magnet_r_samples.append(_mag_r_measured)
                        (_mag_r_delta_ohm, _mag_r_error_pct, _mag_r_error_ppm) = \
                            magnet_load_diagnostics.deviation(_mag_r_measured, MAGNET_R_NAMEPLATE_OHM)

                _mag_didt = magnet_load_diagnostics.estimate_didt(
                    _prev_magnet_t_s, _prev_magnet_i_a, burst_midpoint, mri)

                # Prefer a measured resistance once a steady plateau has been
                # observed. Before that point, use the load-map nameplate R.
                _r_for_l = (statistics.median(_magnet_r_samples)
                            if _magnet_r_samples else MAGNET_R_NAMEPLATE_OHM)
                if _r_for_l is not None and math.isfinite(_mag_didt) and not _is_steady:
                    _mag_l_estimated_h = magnet_load_diagnostics.estimated_inductance(
                        mrv, mri, _mag_didt, _r_for_l)
                    if math.isfinite(_mag_l_estimated_h) and _mag_l_estimated_h > 0.0:
                        _magnet_l_samples.append(_mag_l_estimated_h)
                        (_mag_l_delta_h, _mag_l_error_pct, _mag_l_error_ppm) = \
                            magnet_load_diagnostics.deviation(_mag_l_estimated_h, MAGNET_L_NAMEPLATE_H)

                _prev_magnet_t_s = burst_midpoint
                _prev_magnet_i_a = mri

            # Live plots remain raw/dynamic.  This flag only adds a visual overlay
            # during active magnet cycling so ramp-correlated DCBus/current excursions
            # are easy to distinguish from true steady-state behavior.
            _is_magnet_cycling = (
                math.isfinite(_mag_didt)
                and abs(_mag_didt) >= CYCLING_DIDT_THRESHOLD_A_PER_S
            )

            if _eff_health in ("healthy", "investigate"):
                _health_counts[_eff_health] += 1
            if _diagnostic_valid:
                _valid_eff_data.append(eff_raw)
                if _eff_health == "investigate":
                    if _investigate_start_s is None:
                        _investigate_start_s = burst_midpoint
                    _max_investigate_duration_s = max(
                        _max_investigate_duration_s, burst_midpoint - _investigate_start_s)
                else:
                    _investigate_start_s = None

            time_data.append(burst_midpoint)
            mrp_data.append(mrp)
            mgpc_data.append(mgpc)
            mrv_data.append(mrv)
            mri_data.append(mri)
            pin_data.append(pin)
            pout_data.append(pout)
            eff_data.append(eff_clipped)
            ibus_err_data.append(_ibus_pct_error)

            # Decode MFTR fault register if available
            _mftr_raw = results.get("MFTR", "")
            _fault_str = ""
            _is_faulted_now = False
            _fault_names_now = []
            if _REGISTERS_AVAILABLE and _mftr_raw and "ERR" not in _mftr_raw:
                _mftr_hex = _mftr_raw.split(":")[-1].strip() if ":" in _mftr_raw else _mftr_raw
                _fd = decode_mftr(_mftr_hex)
                _is_faulted_now  = _fd["is_faulted"]
                _fault_names_now = _fd["active_names"]
                if _is_faulted_now:
                    _fault_str = "  FAULT: " + "; ".join(_fault_names_now)

            # Maintain ordered fault cascade by FIRST observation, not bit number.
            _new_fault_names = []
            for _name in _fault_names_now:
                if _name not in _seen_fault_names:
                    _seen_fault_names.add(_name)
                    _fault_cascade.append(_name)
                    _fault_first_seen_s[_name] = burst_midpoint
                    _new_fault_names.append(_name)

            # ── Fault-triggered immediate PMM re-acquisition ───────────────────
            # On the rising edge of a fault (previously clear, now faulted),
            # check/fetch the PMM buffer right away instead of waiting for the
            # polling loop's fixed DURATION to elapse. The CDCU firmware
            # auto-fills the PMM buffer on a real hardware fault event (see
            # cdcu_pmm.py docstring's "Trigger" step), so in most cases the
            # buffer is already captured — this fetches it immediately, tagged
            # to the fault, before the unit is re-armed for the next event.
            if _new_fault_names and _pmm_obj is not None:
                _fault_event_count += 1
                print(f"\n[cdcu_monitor] *** NEW FAULT STAGE DETECTED *** "
                      f"new={'; '.join(_new_fault_names)}  "
                      f"cascade={' -> '.join(_fault_cascade)}  "
                      f"(event #{_fault_event_count} @ {burst_midpoint:.3f}s) "
                      f"— checking PMM buffer immediately ...")
                try:
                    if _pmm_obj.wait_ready(timeout=PMM_FAULT_READY_TIMEOUT, poll_interval=0.1, verbose=False):
                        _fault_ts     = _pmm_obj.timestamp()
                        _fault_pmm_df = _pmm_obj.fetch_dataframe()
                        _fault_dir = _os.path.join(_RUN_DIR, "fault_events")
                        _os.makedirs(_fault_dir, exist_ok=True)
                        _fault_csv = _os.path.join(
                            _fault_dir,
                            f"{_PREFIX}_fault{_fault_event_count:02d}"
                            f"_{burst_midpoint:.3f}s.csv")
                        _fault_pmm_df.to_csv(_fault_csv, index=False)
                        print(f"[cdcu_monitor] Fault-event PMM capture saved: "
                              f"{_fault_csv}  ({len(_fault_pmm_df)} samples "
                              f"@ {PMM_FS_HZ:.0f} Hz)")
                        if _fault_ts:
                            print(f"[cdcu_monitor] Fault PMM timestamp: {_fault_ts}")
                        # User requirement: EVERY fault-triggered PMM is analyzed immediately,
                        # and the report explicitly carries the ordered fault cascade.
                        _fault_analysis = _analyze_pmm_immediately(
                            _fault_pmm_df, capture_kind="fault",
                            capture_index=_fault_event_count, timestamp=_fault_ts,
                            run_dir=_RUN_DIR, prefix=_PREFIX,
                            fault_order=list(_fault_cascade))
                        _pmm_capture_analyses.append(_fault_analysis)
                    else:
                        print(f"[cdcu_monitor] PMM buffer not ready within {PMM_FAULT_READY_TIMEOUT:.1f}s "
                              f"of fault detection — this fault type may not "
                              f"auto-trigger the hardware buffer, or it was "
                              f"already consumed by a prior event.")
                    _pmm_obj.arm()   # rearm immediately for the next event
                except Exception as _fault_pmm_exc:
                    print(f"[cdcu_monitor] Fault-triggered PMM capture "
                          f"failed: {_fault_pmm_exc}")
                finally:
                    # PMM commands change the socket timeout; restore it so
                    # the polling loop's send_command() behaves as configured.
                    s.settimeout(SOCKET_TIMEOUT)
            _was_faulted = _is_faulted_now

            print(
                f"{burst_midpoint:8.3f}s | "
                f"MRP={results.get('MRP', 'OFF')} | "
                f"MGPC={results.get('MGPC', 'OFF')} | "
                f"MRV={results.get('MRV', 'OFF')} | "
                f"MRI={results.get('MRI', 'OFF')} | "
                f"Pin={pin:.3f} | "
                f"Pout={pout:.3f} | "
                f"Eff(raw)={eff_raw:.2f}% | "
                f"Eff(clip)={eff_clipped:.2f}% | "
                f"IBUSerr={_ibus_pct_error:+.2f}%/{_ibus_error_ppm:+.0f}ppm(expected) | "
                f"State={_diagnostic_state} | Cycling={'YES' if _is_magnet_cycling else 'no'} | "
                f"Health={_eff_health} | "
                f"Burst={burst_duration*1000:.1f} ms"
                + _fault_str
            )

            writer.writerow(
                [
                    f"{burst_start:.6f}",
                    f"{burst_end:.6f}",
                    f"{burst_midpoint:.6f}",
                    f"{burst_duration:.6f}",
                ] +
                [results[cmd] for cmd in commands] +
                [
                    "" if math.isnan(parse_float(results.get(cmd, "")))
                    else f"{parse_float(results.get(cmd, '')):.6f}"
                    for cmd in temperature_commands
                ] +
                [
                    "" if math.isnan(mrp)         else f"{mrp:.6f}",
                    "" if math.isnan(mgpc)        else f"{mgpc:.6f}",
                    "" if math.isnan(mrv)         else f"{mrv:.6f}",
                    "" if math.isnan(mri)         else f"{mri:.6f}",
                    "" if math.isnan(pin)         else f"{pin:.6f}",
                    "" if math.isnan(pout)        else f"{pout:.6f}",
                    "" if math.isnan(eff_raw)     else f"{eff_raw:.6f}",
                    "" if math.isnan(eff_clipped) else f"{eff_clipped:.6f}",
                    "" if math.isnan(_i_in_expected)  else f"{_i_in_expected:.6f}",
                    "" if math.isnan(_ibus_delta)     else f"{_ibus_delta:.6f}",
                    "" if math.isnan(_ibus_pct_error) else f"{_ibus_pct_error:.6f}",
                    "" if math.isnan(_ibus_error_ppm) else f"{_ibus_error_ppm:.3f}",
                    "" if math.isnan(_load_fraction) else f"{_load_fraction:.8f}",
                    "" if math.isnan(_load_fraction) else f"{_load_fraction*100.0:.6f}",
                    "1" if _is_steady else "0",
                    "1" if _diagnostic_valid else "0",
                    _diagnostic_state,
                    _diagnostic_confidence,
                    "" if math.isnan(_eta_ref_pct) else f"{_eta_ref_pct:.6f}",
                    _ETA_REFERENCE_SOURCE,
                    "" if math.isnan(_eta_min_pct) else f"{_eta_min_pct:.6f}",
                    "1" if _caen_compliance_valid else "0",
                    _caen_compliance,
                    "" if math.isnan(_eff_delta_ref_pct) else f"{_eff_delta_ref_pct:.6f}",
                    "" if math.isnan(_eff_delta_ref_ppm) else f"{_eff_delta_ref_ppm:.3f}",
                    "" if math.isnan(_eff_delta_ref_relative_ppm) else f"{_eff_delta_ref_relative_ppm:.3f}",
                    "" if math.isnan(_eff_margin_caen_pct) else f"{_eff_margin_caen_pct:.6f}",
                    "" if math.isnan(_eff_margin_caen_ppm) else f"{_eff_margin_caen_ppm:.3f}",
                    "" if math.isnan(_eff_margin_caen_relative_ppm) else f"{_eff_margin_caen_relative_ppm:.3f}",
                    "" if math.isnan(_power_loss_w) else f"{_power_loss_w:.6f}",
                    "" if math.isnan(_power_loss_pct) else f"{_power_loss_pct:.6f}",
                    "" if math.isnan(_power_loss_ppm) else f"{_power_loss_ppm:.3f}",
                    "1" if _power_balance_anomaly else "0",
                    "" if math.isnan(_mag_r_measured) else f"{_mag_r_measured:.9f}",
                    "" if math.isnan(_mag_r_measured) else f"{_mag_r_measured*1e3:.6f}",
                    "" if MAGNET_R_NAMEPLATE_OHM is None else f"{MAGNET_R_NAMEPLATE_OHM:.9f}",
                    "" if math.isnan(_mag_r_delta_ohm) else f"{_mag_r_delta_ohm*1e3:.6f}",
                    "" if math.isnan(_mag_r_error_pct) else f"{_mag_r_error_pct:.6f}",
                    "" if math.isnan(_mag_r_error_ppm) else f"{_mag_r_error_ppm:.3f}",
                    "" if math.isnan(_mag_didt) else f"{_mag_didt:.6f}",
                    "1" if _is_magnet_cycling else "0",
                    "" if math.isnan(_mag_l_estimated_h) else f"{_mag_l_estimated_h:.9f}",
                    "" if math.isnan(_mag_l_estimated_h) else f"{_mag_l_estimated_h*1e3:.6f}",
                    "" if MAGNET_L_NAMEPLATE_H is None else f"{MAGNET_L_NAMEPLATE_H:.9f}",
                    "" if math.isnan(_mag_l_delta_h) else f"{_mag_l_delta_h*1e3:.6f}",
                    "" if math.isnan(_mag_l_error_pct) else f"{_mag_l_error_pct:.6f}",
                    "" if math.isnan(_mag_l_error_ppm) else f"{_mag_l_error_ppm:.3f}",
                    _eff_health,
                ]
            )
            f.flush()

            # Publish a throttled live snapshot for the consolidated multi-IP dashboard.
            _temps_snapshot = {}
            for _tcmd in temperature_commands:
                _tv = parse_float(results.get(_tcmd, ""))
                if math.isfinite(_tv):
                    _temps_snapshot[_tcmd] = _tv
            _write_dashboard_snapshot({
                "host": HOST,
                "magnet_id": MAGNET_ID or "",
                "load_desc": LOAD_DESC or "",
                "serial": _SN_FULL or _SN_EARLY or "",
                "firmware": _VER_STR or "",
                "t_s": float(burst_midpoint),
                "pin_w": None if not math.isfinite(pin) else float(pin),
                "pout_w": None if not math.isfinite(pout) else float(pout),
                "mrp_v": None if not math.isfinite(mrp) else float(mrp),
                "mgpc_a": None if not math.isfinite(mgpc) else float(mgpc),
                "mrv_v": None if not math.isfinite(mrv) else float(mrv),
                "mri_a": None if not math.isfinite(mri) else float(mri),
                "eff_pct": None if not math.isfinite(eff_clipped) else float(eff_clipped),
                "temperatures_c": _temps_snapshot,
                "fault": _fault_str.strip(),
                "state": _diagnostic_state,
                "is_magnet_cycling": _is_magnet_cycling,
                "magnet_didt_a_per_s": None if not math.isfinite(_mag_didt) else float(_mag_didt),
            })

            line_pin.set_data(time_data, pin_data)
            line_pout.set_data(time_data, pout_data)
            for _cmd, _line in electrical_lines.items():
                _line.set_data(time_data, signal_data[_cmd])
            line_eff.set_data(time_data, eff_data)
            for _cmd, _line in temperature_lines.items():
                _line.set_data(time_data, signal_data[_cmd])

            if (_is_magnet_cycling and math.isfinite(_prev_plot_t_s)
                    and burst_midpoint > _prev_plot_t_s):
                for _ax in axes:
                    _ax.axvspan(_prev_plot_t_s, burst_midpoint,
                                facecolor=CYCLING_SHADE_COLOR,
                                alpha=CYCLING_SHADE_ALPHA, zorder=0)
            _prev_plot_t_s = burst_midpoint

            axes[0].relim(); axes[0].autoscale_view()
            axes[1].relim(); axes[1].autoscale_view()
            axes[2].set_xlim(
                min(time_data) if time_data else 0,
                max(time_data) if time_data else DURATION,
            )

            axes[3].relim(); axes[3].autoscale_view()

            if not _HEADLESS:
                plt.pause(0.001)

            # Force one final PMM immediately before the live-polling timeout.
            # The PMM hardware continues sampling independently after the force
            # command, so the buffer captures the end-of-run operating point
            # without using the irregular Ethernet polling samples for FFT/PSD.
            if RUN_PMM and _pmm_obj is not None and not _final_pmm_forced:
                _remaining_s = end_time - time.time()
                if _remaining_s <= max(PMM_FINAL_TRIGGER_LEAD_S, 1.5 * burst_duration):
                    try:
                        if _pmm_obj.force():
                            _final_pmm_forced = True
                            _final_pmm_force_time = time.time()
                            print(f"[cdcu_monitor] Final PMM forced with {_remaining_s:.3f}s remaining in live polling.")
                        else:
                            print("[cdcu_monitor] Final PMM:FORCE returned NAK; no end-of-run PMM will be available.")
                    except Exception as _final_force_exc:
                        print(f"[cdcu_monitor] Final PMM trigger failed: {_final_force_exc}")
                    finally:
                        if s.fileno() != -1:
                            s.settimeout(SOCKET_TIMEOUT)

            elapsed_loop = time.time() - loop_start
            time.sleep(max(0.0, INTERVAL - elapsed_loop))

    # If the last polling burst crossed the timeout before the lead-time test could
    # issue PMM:FORCE, trigger the final PMM immediately at timeout as a fallback.
    # This preserves the end-of-run spectral witness rather than silently losing it.
    if RUN_PMM and _pmm_obj is not None and not _final_pmm_forced:
        try:
            if _pmm_obj.force():
                _final_pmm_forced = True
                _final_pmm_force_time = time.time()
                print("[cdcu_monitor] Final PMM forced at live-polling timeout (fallback path).")
        except Exception as _final_force_exc:
            print(f"[cdcu_monitor] Final PMM fallback trigger failed: {_final_force_exc}")
        finally:
            if s.fileno() != -1:
                s.settimeout(SOCKET_TIMEOUT)

    # ============================================================
    # FINAL PMM CAPTURE — fetch the PMM that was forced immediately before the
    # live-polling timeout.  This creates the end-of-run spectral witness used for
    # startup-versus-live comparison.  FFT/PSD is performed on PMM data only.
    # ============================================================
    if RUN_PMM and _pmm_obj is not None and _final_pmm_forced:
        try:
            print("\n── Final PMM Acquisition ───────────────────────────────────────")
            if _pmm_obj.wait_ready(timeout=max(PMM_FAULT_READY_TIMEOUT, 10.0), poll_interval=0.1, verbose=False):
                _final_pmm_timestamp = _pmm_obj.timestamp()
                _final_pmm_df = _pmm_obj.fetch_dataframe()
                _final_pmm_dir = _os.path.join(_RUN_DIR, "pmm_captures")
                _os.makedirs(_final_pmm_dir, exist_ok=True)
                _final_pmm_csv = _os.path.join(_final_pmm_dir, f"{_PREFIX}_final_pmm.csv")
                _final_pmm_df.to_csv(_final_pmm_csv, index=False)
                print(f"[cdcu_monitor] Final PMM CSV saved: {_final_pmm_csv}")
                _final_analysis = _analyze_pmm_immediately(
                    _final_pmm_df, capture_kind="final", capture_index=1,
                    timestamp=_final_pmm_timestamp, run_dir=_RUN_DIR, prefix=_PREFIX,
                    fault_order=None)
                _pmm_capture_analyses.append(_final_analysis)
                # Keep the final PMM available to the optional end-of-run report path.
                _pmm_df = _final_pmm_df
                _pmm_timestamp = _final_pmm_timestamp
                print("[cdcu_monitor] Final PMM analyzed immediately. Startup and end-of-run PMM products are now available for comparison.")
            else:
                print("[cdcu_monitor] Final PMM buffer did not become ready before the fetch timeout.")
            _pmm_obj.arm()
        except Exception as _final_pmm_exc:
            print(f"[cdcu_monitor] Final PMM acquisition failed: {_final_pmm_exc}")
        finally:
            if s.fileno() != -1:
                s.settimeout(SOCKET_TIMEOUT)

# ============================================================
# Refine RAW_V ("DC Bus:" display value) using the run's mean live-measured
# MRP — more representative than the single connect-time reading taken
# before the loop started. Falls back to that connect-time value (or stays
# None) if no valid samples were collected during the run.
# ============================================================
_valid_mrp_samples = [v for v in mrp_data if not math.isnan(v)]
if _valid_mrp_samples:
    RAW_V = sum(_valid_mrp_samples) / len(_valid_mrp_samples)

# ============================================================
# PARSE SERIAL NUMBER + VER from captured history; update figure title
# SN response:  #SN:CDCU-300:19Y0002  → model="CDCU-300", sn="19Y0002"
# VER response: #VER:3.1.4            → ver="3.1.4"
# ============================================================
_sn_raw_list = [v for v in raw_history.get("SN", [])
                if v and "ERR" not in str(v) and "NAK" not in str(v)]
_SN = _SN_EARLY  # prefer the on-connect value; fall back to per-burst capture
if not _SN and _sn_raw_list:
    _sn_resp = str(_sn_raw_list[-1]).strip()
    _sn_parts = _sn_resp.lstrip("#").split(":", 2)
    if len(_sn_parts) >= 3:
        _SN = _sn_parts[2].strip()        # serial only e.g. "19Y0002"
        if not _SN_FULL:
            _SN_FULL = f"{_sn_parts[1].strip()}:{_SN}"
    elif len(_sn_parts) == 2:
        _SN = _sn_parts[1].strip()
        if not _SN_FULL:
            _SN_FULL = _SN

_ver_raw_list = [v for v in raw_history.get("VER", [])
                 if v and "ERR" not in str(v) and "NAK" not in str(v)]
_VER_FINAL = _VER_STR  # prefer on-connect value
if not _VER_FINAL and _ver_raw_list:
    _VER_FINAL = str(_ver_raw_list[-1]).split(":")[-1].strip()

# Final title: {SECTOR}  {CABINET}  {HOST}  {full SN}  {VER}
_title_parts_final = [p for p in [SECTOR, CABINET, HOST,
                                    _SN_FULL, _VER_FINAL] if p]
_title_with_sn = ("  ".join(_title_parts_final)
                  if _title_parts_final else f"CDCU Live — {HOST}")
fig.suptitle(_title_with_sn, fontsize=12, fontweight="bold", y=0.985)

# Also append SN to the CSV metadata header (reopen in append mode is not
# possible after close, so write it to the console and carry it in memory
# for the footer box below)
if _SN or _VER_FINAL:
    print(f"[cdcu_monitor] VER={_VER_FINAL or '?'}  SN={_SN or '?'}")
    try:
        with open(CSV_FILE, "a", encoding="utf-8") as _csv_append:
            if _SN:
                _csv_append.write(f"# serial_number = {_SN}\n")
            if _VER_FINAL:
                _csv_append.write(f"# firmware_ver = {_VER_FINAL}\n")
    except Exception:
        pass

# ── Run-level diagnostics summary (mean IBUS %Error, efficiency-health
# verdict across steady-state samples, fault-event count) — appended to the
# CSV metadata and carried into the PDF report meta dict below. ──────────
_valid_ibus_err = [v for v in ibus_err_data if not math.isnan(v)]
_IBUS_PCT_ERROR_MEAN = statistics.mean(_valid_ibus_err) if _valid_ibus_err else None
_IBUS_PCT_ERROR_MEDIAN = statistics.median(_valid_ibus_err) if _valid_ibus_err else None
_IBUS_PCT_ERROR_MAX = max(_valid_ibus_err) if _valid_ibus_err else None
_IBUS_PCT_ERROR_MIN = min(_valid_ibus_err) if _valid_ibus_err else None
_IBUS_PCT_ERROR_STD = statistics.pstdev(_valid_ibus_err) if len(_valid_ibus_err) > 1 else (0.0 if _valid_ibus_err else None)
_IBUS_VALID_SAMPLE_COUNT = len(_valid_ibus_err)
if _max_investigate_duration_s >= cdcu_diagnostics.INVESTIGATE_PERSISTENCE_S if _DIAGNOSTICS_AVAILABLE else False:
    _EFF_HEALTH_VERDICT = "investigate"
elif _health_counts["healthy"] > 0:
    _EFF_HEALTH_VERDICT = "healthy"
else:
    _EFF_HEALTH_VERDICT = "insufficient diagnostic-valid data"

try:
    with open(CSV_FILE, "a", encoding="utf-8") as _csv_append2:
        if RAW_V is not None:
            _csv_append2.write(f"# dcbus_V_measured_mean = {RAW_V:.6f}\n")
        if _IBUS_PCT_ERROR_MEAN is not None:
            _csv_append2.write(f"# ibus_pct_error_mean = {_IBUS_PCT_ERROR_MEAN:.4f}\n")
            _csv_append2.write(f"# ibus_error_ppm_mean = {_IBUS_PCT_ERROR_MEAN*1.0e4:.2f}\n")
            _csv_append2.write(f"# ibus_pct_error_median = {_IBUS_PCT_ERROR_MEDIAN:.4f}\n")
            _csv_append2.write(f"# ibus_pct_error_min = {_IBUS_PCT_ERROR_MIN:.4f}\n")
            _csv_append2.write(f"# ibus_pct_error_max = {_IBUS_PCT_ERROR_MAX:.4f}\n")
            _csv_append2.write(f"# ibus_pct_error_std = {_IBUS_PCT_ERROR_STD:.4f}\n")
            _csv_append2.write(f"# ibus_valid_sample_count = {_IBUS_VALID_SAMPLE_COUNT}\n")
        if math.isfinite(_ETA_REFERENCE):
            _csv_append2.write(f"# eta_reference_pct = {_ETA_REFERENCE * 100.0:.4f}\n")
        _csv_append2.write(f"# eta_reference_source = {_ETA_REFERENCE_SOURCE}\n")
        _csv_append2.write(f"# efficiency_health_verdict = {_EFF_HEALTH_VERDICT}\n")
        _csv_append2.write(f"# max_investigate_duration_s = {_max_investigate_duration_s:.4f}\n")
        _csv_append2.write(f"# fault_event_count = {_fault_event_count}\n")
        _csv_append2.write(f"# fault_cascade = {' -> '.join(_fault_cascade) if _fault_cascade else 'None'}\n")
        for _fname in _fault_cascade:
            _csv_append2.write(f"# fault_first_seen_s[{_fname}] = {_fault_first_seen_s[_fname]:.6f}\n")
except Exception:
    pass

# ============================================================
# FOOTER: logo + metadata box + timestamp  (added after data loop)
# These use add_axes so they must come AFTER tight_layout (already called
# in the setup block above) to avoid UserWarning.
# ============================================================

# ── ANL logo inset (lower-right) with transparency support ────────────────
_LOGO_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "ANL_RGB-APS-fullname_horiz.png",
)
if os.path.isfile(_LOGO_FILE):
    try:
        from PIL import Image as _PILImage
        _logo_pil = _PILImage.open(_LOGO_FILE).convert("RGBA")
        import numpy as _np_logo
        _logo_arr = _np_logo.array(_logo_pil).astype(float) / 255.0
        ax_logo = fig.add_axes([0.76, 0.005, 0.22, 0.07])
        ax_logo.set_facecolor("none")   # transparent axes background
        # Render RGBA — alpha channel is honoured; JPEG (no alpha) renders normally
        ax_logo.imshow(_logo_arr, interpolation="lanczos")
        ax_logo.axis("off")
        ax_logo.patch.set_alpha(0.0)    # axes patch also transparent
    except Exception:
        pass  # logo is decorative — never crash on failure

# ── Metadata info box (lower-left) ───────────────────────────────────────
# Assembles load-map fields into a compact multi-line string so the saved
# PNG is self-documenting without needing a separate legend or README.
_meta_lines = []
if MAGNET_ID:
    _meta_lines.append(f"Magnet: {MAGNET_ID}")
_sn_label = f"SN: {_SN}  |  " if _SN else ""
_meta_lines.append(f"{_sn_label}Host: {HOST}  |  Cabinet: {CABINET or 'N/A'}"
                   + (f"  |  Sector: {SECTOR}" if SECTOR else ""))
if RAW_V is not None:
    _meta_lines.append(f"DC Bus: {RAW_V} V"
                       + (f"  |  Vout rating: {V_OUT_RATING} V" if V_OUT_RATING is not None else ""))
if DCBUS_REF_V is not None:
    _meta_lines.append(f"Vbus ref: {DCBUS_REF_V} V"
                       + (f"  |  Idc ref: {IDC_REF_A} A" if IDC_REF_A is not None else ""))
if LOAD_DESC:
    # Wrap long load descriptions to ~90 chars per line
    _words = LOAD_DESC.split(";")
    _meta_lines.append(";".join(_words[:2]).strip())
    if len(_words) > 2:
        _meta_lines.append(";".join(_words[2:]).strip())

if _meta_lines:
    # x=0.125 aligns with the default matplotlib subplot left edge
    # so the box left-edge is flush with the y-axis of the top subplot
    _ax_left = axes[0].get_position().x0  # actual left edge in fig coords
    fig.text(
        _ax_left, 0.005,
        "\n".join(_meta_lines),
        ha="left", va="bottom",
        fontsize=7.5, color="dimgray",
        linespacing=1.5,
        bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="lightgray",
                  alpha=0.85),
    )

# ── Generation timestamp (lower-centre) ──────────────────────────────────
fig.text(
    0.5, 0.005,
    f"Saved: {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}",
    ha="center", va="bottom", fontsize=7.5, color="dimgray",
)

fig.savefig(PNG_FILE, dpi=150, bbox_inches="tight")

# Live polling has ended.  Capture the actual elapsed data-window duration before
# post-run characterization/report work adds to the per-supply runtime.
if _live_start_mono is not None:
    _live_actual_duration_s = time.perf_counter() - _live_start_mono
    print("\n── Live Duration Summary ─────────────────────────────────────")
    print(f"[runtime] Live duration setting: {_format_runtime(DURATION)}")
    print(f"[runtime] Actual live polling duration: {_format_runtime(_live_actual_duration_s)}")

# ============================================================
# MAGNET LOAD CHARACTERIZATION SUMMARY
# ============================================================
_MAGNET_R_MEASURED_OHM = statistics.median(_magnet_r_samples) if _magnet_r_samples else None
_MAGNET_L_ESTIMATED_H = statistics.median(_magnet_l_samples) if _magnet_l_samples else None
_MAGNET_SUMMARY_FILE = os.path.join(_RUN_DIR, f"{_PREFIX}_magnet_load_summary.txt")

if _MAGNET_DIAGNOSTICS_AVAILABLE and (_MAGNET_R_MEASURED_OHM is not None or MAGNET_R_NAMEPLATE_OHM is not None):
    _model_spec_for_magnet = cdcu_diagnostics.get_model_spec(_MODEL_STR) if _DIAGNOSTICS_AVAILABLE else None
    _rated_current_a = (_model_spec_for_magnet or {}).get("rated_A", math.nan)
    _rated_voltage_v = (_model_spec_for_magnet or {}).get("rated_V", math.nan)
    _rated_power_w = (_model_spec_for_magnet or {}).get("rated_W", math.nan)

    _r_for_projection = (_MAGNET_R_MEASURED_OHM if _MAGNET_R_MEASURED_OHM is not None
                         else MAGNET_R_NAMEPLATE_OHM)
    _v_at_rated, _p_at_rated = magnet_load_diagnostics.extrapolate_at_current(
        _r_for_projection, _rated_current_a)
    _v_nameplate_rated, _p_nameplate_rated = magnet_load_diagnostics.extrapolate_at_current(
        MAGNET_R_NAMEPLATE_OHM, _rated_current_a)

    if _MAGNET_R_MEASURED_OHM is not None:
        _r_delta, _r_pct, _r_ppm = magnet_load_diagnostics.deviation(
            _MAGNET_R_MEASURED_OHM, MAGNET_R_NAMEPLATE_OHM)
    else:
        _r_delta = _r_pct = _r_ppm = math.nan

    if _MAGNET_L_ESTIMATED_H is not None:
        _l_delta, _l_pct, _l_ppm = magnet_load_diagnostics.deviation(
            _MAGNET_L_ESTIMATED_H, MAGNET_L_NAMEPLATE_H)
    else:
        _l_delta = _l_pct = _l_ppm = math.nan

    _slew_r = (_MAGNET_R_MEASURED_OHM if _MAGNET_R_MEASURED_OHM is not None
               else MAGNET_R_NAMEPLATE_OHM)
    _slew_l = (_MAGNET_L_ESTIMATED_H if _MAGNET_L_ESTIMATED_H is not None
               else MAGNET_L_NAMEPLATE_H)
    _max_slew_at_rated = magnet_load_diagnostics.max_slew_rate(
        _rated_voltage_v, _rated_current_a, _slew_r, _slew_l)

    _steady_bus_v = statistics.median(_steady_dcbus_v_samples) if _steady_dcbus_v_samples else None
    _steady_bus_i = statistics.median(_steady_dcbus_i_samples) if _steady_dcbus_i_samples else None
    _steady_bus_p = statistics.median(_steady_dcbus_p_samples) if _steady_dcbus_p_samples else None
    _steady_output_p = statistics.median(_steady_output_p_samples) if _steady_output_p_samples else None
    _steady_eff_pct = (statistics.median(_steady_efficiency_pct_samples)
                       if _steady_efficiency_pct_samples else None)
    # Cross-check efficiency using robust median output/input powers.
    _steady_eff_power_ratio_pct = None
    if (_steady_bus_p is not None and _steady_output_p is not None
            and math.isfinite(_steady_bus_p) and abs(_steady_bus_p) > 1e-12):
        _steady_eff_power_ratio_pct = abs(_steady_output_p / _steady_bus_p) * 100.0

    # Manufacturer switching-frequency references. These values are specifications,
    # not estimates from PMM data.
    _switching_frequency_hz = ((_model_spec_for_magnet or {}).get("switching_frequency_Hz")
                               if _model_spec_for_magnet else None)
    _equiv_switching_frequency_hz = ((_model_spec_for_magnet or {}).get("equivalent_switching_frequency_Hz")
                                     if _model_spec_for_magnet else None)

    with open(_MAGNET_SUMMARY_FILE, "w", encoding="utf-8") as _ms:
        _ms.write("MAGNET LOAD CHARACTERIZATION\n")
        _ms.write("============================\n")
        _ms.write(f"Magnet: {MAGNET_ID or '(unknown)'}\n")
        _ms.write(f"Load map: {LOAD_DESC}\n")
        _ms.write(f"CDCU model: {_MODEL_STR or '(unknown)'}\n\n")
        _ms.write("Steady-state DCBus operating point\n")
        _ms.write("---------------------------------\n")
        if _steady_bus_v is not None:
            _ms.write(f"DCBus voltage (median steady-state MRP): {_steady_bus_v:.6f} V\n")
        else:
            _ms.write("DCBus voltage: insufficient steady-state data\n")
        if _steady_bus_i is not None:
            _ms.write(f"DCBus current (median steady-state MGPC): {_steady_bus_i:.6f} A\n")
        else:
            _ms.write("DCBus current: insufficient steady-state data\n")
        if _steady_bus_p is not None:
            _ms.write(f"DCBus input power (median |MRP x MGPC|): {_steady_bus_p:.6f} W ({_steady_bus_p/1000.0:.6f} kW)\n")
        else:
            _ms.write("DCBus input power: insufficient steady-state data\n")
        if _steady_bus_v is not None and _steady_bus_i is not None:
            _ms.write(f"Median-V x median-I check: |{_steady_bus_v:.6f} V x {_steady_bus_i:.6f} A| = {abs(_steady_bus_v*_steady_bus_i):.6f} W\n")
        _ms.write(f"Steady-state DCBus samples: {len(_steady_dcbus_p_samples)}\n\n")

        _ms.write("Steady-state converter efficiency\n")
        _ms.write("---------------------------------\n")
        if _steady_output_p is not None:
            _ms.write(f"Output power (median steady-state |MRV x MRI|): {_steady_output_p:.6f} W ({_steady_output_p/1000.0:.6f} kW)\n")
        else:
            _ms.write("Output power: insufficient steady-state data\n")
        if _steady_eff_pct is not None:
            _ms.write(f"Measured power-supply efficiency (median steady-state Pout/Pin samples): {_steady_eff_pct:.6f}%\n")
        else:
            _ms.write("Measured power-supply efficiency: insufficient steady-state data\n")
        if _steady_eff_power_ratio_pct is not None:
            _ms.write(f"Median-power efficiency cross-check (median Pout / median Pin): {_steady_eff_power_ratio_pct:.6f}%\n")
        if math.isfinite(_ETA_REFERENCE):
            _ms.write(f"Diagnostic efficiency reference: {_ETA_REFERENCE*100.0:.3f}% (source: {_ETA_REFERENCE_SOURCE})\n")
        if _model_spec_for_magnet is not None:
            _eta_min = _model_spec_for_magnet.get("eta_full_load_min")
            if _eta_min is not None and math.isfinite(float(_eta_min)):
                _ms.write(f"CAEN full-load efficiency minimum: {float(_eta_min)*100.0:.1f}% (full-load specification; not a low-load acceptance criterion)\n")
        _ms.write(f"Steady-state efficiency samples: {len(_steady_efficiency_pct_samples)}\n\n")

        _ms.write("Converter switching-frequency reference\n")
        _ms.write("---------------------------------------\n")
        if _switching_frequency_hz is not None:
            _ms.write(f"Manufacturer switching frequency: {_switching_frequency_hz/1000.0:.1f} kHz\n")
        else:
            _ms.write("Manufacturer switching frequency: unavailable for unknown model\n")
        if _equiv_switching_frequency_hz is not None:
            _ms.write(f"Manufacturer equivalent switching frequency: {_equiv_switching_frequency_hz/1000.0:.1f} kHz\n")
        _ms.write("PMM-derived switching frequency: not directly measurable from the standard 10 kHz PMM record; Nyquist limit is 5 kHz.\n")
        _ms.write("Direct verification method: measure PWM at the PWM Logic Board test points or use a sufficiently wide-bandwidth oscilloscope on switching-ripple content.\n\n")

        if MAGNET_R_NAMEPLATE_OHM is not None:
            _ms.write(f"Nameplate resistance: {MAGNET_R_NAMEPLATE_OHM*1e3:.3f} mOhm\n")
        if _MAGNET_R_MEASURED_OHM is not None:
            _ms.write(f"Measured steady-state resistance (median): {_MAGNET_R_MEASURED_OHM*1e3:.3f} mOhm\n")
            if math.isfinite(_r_pct):
                _ms.write(f"Resistance deviation: {_r_delta*1e3:+.3f} mOhm | {_r_pct:+.3f}% | {_r_ppm:+.0f} ppm of nameplate\n")
        if MAGNET_L_NAMEPLATE_H is not None:
            _ms.write(f"Nameplate inductance: {MAGNET_L_NAMEPLATE_H*1e3:.3f} mH\n")
        if _MAGNET_L_ESTIMATED_H is not None:
            _ms.write(f"Live-ramp inductance estimate (median): {_MAGNET_L_ESTIMATED_H*1e3:.3f} mH\n")
            if math.isfinite(_l_pct):
                _ms.write(f"Inductance deviation: {_l_delta*1e3:+.3f} mH | {_l_pct:+.3f}% | {_l_ppm:+.0f} ppm of nameplate\n")
        _ms.write("\nProjected operation at CDCU rated current\n")
        if math.isfinite(_rated_current_a):
            _ms.write(f"Rated current: {_rated_current_a:.1f} A\n")
        if math.isfinite(_v_at_rated):
            _ms.write(f"Predicted steady-state magnet voltage from measured/best R: {_v_at_rated:.3f} V\n")
        if math.isfinite(_p_at_rated):
            _ms.write(f"Predicted steady-state magnet power from measured/best R: {_p_at_rated/1000.0:.3f} kW\n")
        if math.isfinite(_v_nameplate_rated):
            _ms.write(f"Nameplate-R predicted voltage: {_v_nameplate_rated:.3f} V\n")
        if math.isfinite(_p_nameplate_rated):
            _ms.write(f"Nameplate-R predicted power: {_p_nameplate_rated/1000.0:.3f} kW\n")
        if math.isfinite(_rated_voltage_v) and math.isfinite(_v_at_rated):
            _ms.write(f"CDCU voltage utilization at rated current: {_v_at_rated/_rated_voltage_v*100.0:.2f}%\n")
        if math.isfinite(_rated_power_w) and math.isfinite(_p_at_rated):
            _ms.write(f"CDCU power utilization at rated current: {_p_at_rated/_rated_power_w*100.0:.2f}%\n")
        if math.isfinite(_max_slew_at_rated):
            _ms.write(f"Estimated positive slew-rate headroom at rated current: {_max_slew_at_rated:.1f} A/s\n")
        _ms.write("\nEngineering note: resistance is evaluated from steady-state MRV/MRI data. ")
        _ms.write("Inductance is estimated from live-polling ramp data and should be treated as a trend/validation value, not a precision LCR measurement.\n")

    print(f"[cdcu_monitor] Magnet load summary saved: {_MAGNET_SUMMARY_FILE}")
    if _MAGNET_R_MEASURED_OHM is not None and MAGNET_R_NAMEPLATE_OHM is not None:
        print(f"[cdcu_monitor] Magnet R: measured {_MAGNET_R_MEASURED_OHM*1e3:.3f} mOhm vs "
              f"nameplate {MAGNET_R_NAMEPLATE_OHM*1e3:.3f} mOhm "
              f"({_r_pct:+.2f}% / {_r_ppm:+.0f} ppm)")

plt.ioff()
plt.close(fig)   # auto-close so the rest of the program continues immediately
print(f"[cdcu_monitor] Live plot window closed automatically.")

print(f"\nCSV saved to: {CSV_FILE}")
print(f"PNG saved to: {PNG_FILE}")

# ============================================================
# POST-RUN RIPPLE / FFT / PSD ANALYSIS
# ============================================================
if RUN_RIPPLE_ANALYSIS and (_pmm_df is not None):
    print("\n── Starting ripple analysis ────────────────────────────────────")
    try:
        import cdcu_ripple_psd as _psd_mod
        import cdcu_ripple_pdf as _pdf_mod
        from cdcu_ripple_bands import BAND_STR
        from cdcu_ripple_io import read_ps_ripple_metadata

        # ── Build shared metadata dict ────────────────────────────────────
        _csv_meta = read_ps_ripple_metadata(CSV_FILE)
        _resolved_sn = _csv_meta.get("serial_number", "") or _SN

        # Last-seen MFTR register + decoded active fault names for the
        # worksheet (previously always blank — never populated from the
        # actual per-burst MFTR readings already being collected).
        _last_mftr_raw    = ""
        _last_mftr_active = "None"
        if _REGISTERS_AVAILABLE and raw_history.get("MFTR"):
            _mftr_hist = [v for v in raw_history["MFTR"]
                          if v and "ERR" not in str(v) and "NAK" not in str(v)]
            if _mftr_hist:
                _last_val = str(_mftr_hist[-1])
                _last_hex = _last_val.split(":")[-1].strip() if ":" in _last_val else _last_val
                _last_decoded = decode_mftr(_last_hex)
                _last_mftr_raw = _last_decoded["raw_hex"]
                _last_mftr_active = ("; ".join(_last_decoded["active_names"])
                                     if _last_decoded["active_names"] else "None")

        _meta = {
            "ip":              HOST,
            "cabinet":         CABINET or "",
            "sector":          SECTOR,
            "ps_id":           MAGNET_ID or os.path.basename(os.path.dirname(CSV_FILE)),
            "magnet_id":       MAGNET_ID,
            "serial_number":   _resolved_sn,
            "event_local":     run_start_iso,
            "generated_local": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "load_desc":       LOAD_DESC,
            "raw_V":           str(RAW_V)   if RAW_V is not None else "",
            "v_out_rating":    str(V_OUT_RATING) if V_OUT_RATING is not None else "",
            "dcbus_ref_V":     str(DCBUS_REF_V)  if DCBUS_REF_V is not None else "",
            "idc_ref_A":       str(IDC_REF_A)    if IDC_REF_A is not None else "",
            "mftr":            _last_mftr_raw,
            "mftr_active":     _last_mftr_active,
            "model":           _MODEL_STR or "",
            "eta_reference_pct": (f"{_ETA_REFERENCE * 100.0:.2f}" if math.isfinite(_ETA_REFERENCE) else ""),
            "eta_reference_source": _ETA_REFERENCE_SOURCE,
            "ibus_pct_error_mean": (f"{_IBUS_PCT_ERROR_MEAN:.2f}" if _IBUS_PCT_ERROR_MEAN is not None else ""),
            "ibus_error_ppm_mean": (f"{_IBUS_PCT_ERROR_MEAN*1.0e4:.0f}" if _IBUS_PCT_ERROR_MEAN is not None else ""),
            "efficiency_health_verdict": _EFF_HEALTH_VERDICT,
            "fault_event_count": str(_fault_event_count),
            "fault_cascade": " -> ".join(_fault_cascade) if _fault_cascade else "None",
            "magnet_resistance_nameplate_ohm": (f"{MAGNET_R_NAMEPLATE_OHM:.9f}" if MAGNET_R_NAMEPLATE_OHM is not None else ""),
            "magnet_resistance_measured_ohm": (f"{_MAGNET_R_MEASURED_OHM:.9f}" if _MAGNET_R_MEASURED_OHM is not None else ""),
            "magnet_inductance_nameplate_H": (f"{MAGNET_L_NAMEPLATE_H:.9f}" if MAGNET_L_NAMEPLATE_H is not None else ""),
            "magnet_inductance_estimated_H": (f"{_MAGNET_L_ESTIMATED_H:.9f}" if _MAGNET_L_ESTIMATED_H is not None else ""),
        }

        # All output dirs live inside the structured run directory
        _event_dir    = _RUN_DIR
        _analysis_dir = os.path.join(_RUN_DIR, "analysis")
        _reports_dir  = os.path.join(_RUN_DIR, "reports")
        os.makedirs(_analysis_dir, exist_ok=True)
        os.makedirs(_reports_dir,  exist_ok=True)

        _LOGO_PATH_A = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "ANL_RGB-APS-fullname_horiz.png")
        # _LOGO_TEXT_A = "Argonne National Laboratory – APS"
        # Branding is supplied by the transparent PNG rather than duplicate text.
        _LOGO_TEXT_A = None
        _SIG_PPM     = 12.0

        # ── PMM spectral analysis ─────────────────────────────────────────
        if _pmm_df is not None:
            print("[cdcu_monitor] Running PMM spectral analysis ...")
            _pmm_analysis_dir = os.path.join(_analysis_dir, "pmm")
            os.makedirs(_pmm_analysis_dir, exist_ok=True)

            # PMM channel map: col_name → (unit, label)
            _pmm_col_map = {
                "vout_V":  ("V", "PMM Output Voltage"),
                "iout_A":  ("A", "PMM Output Current"),
            }
            import math as _math

            for _pmm_col, (_pmm_unit, _pmm_label) in _pmm_col_map.items():
                if _pmm_col not in _pmm_df.columns:
                    continue
                _sub = _pmm_df[["time_s", _pmm_col]].dropna().reset_index(drop=True)
                if len(_sub) < 64:
                    continue
                _dc_mean = float(_sub[_pmm_col].mean())
                _spec = cdcu_diagnostics.get_model_spec(_MODEL_STR) if _DIAGNOSTICS_AVAILABLE else None
                if _spec and _pmm_col in ("iout_A", "iset_A"):
                    _ppm_ref = float(_spec["rated_A"])
                    _ppm_ref_label = "full scale (rated current)"
                elif _spec and _pmm_col == "vout_V":
                    _ppm_ref = float(_spec["rated_V"])
                    _ppm_ref_label = "full scale (rated voltage)"
                else:
                    _ppm_ref = _dc_mean if (_math.isfinite(_dc_mean) and _dc_mean != 0) else None
                    _ppm_ref_label = "operating point (DC mean)" if _ppm_ref is not None else "undefined"
                _ch_dir  = os.path.join(_pmm_analysis_dir, _pmm_col)
                _comp_png = os.path.join(_ch_dir,
                                         f"{_PREFIX}_pmm_{_pmm_col}_report.png")
                _res = _psd_mod.analyze_series_for_reports(
                    df=_sub,
                    time_col="time_s",
                    value_col=_pmm_col,
                    outdir=_ch_dir,
                    ppm_ref=_ppm_ref,
                    ppm_ref_label=_ppm_ref_label,
                    bands=BAND_STR,
                    sig_threshold_ppm=_SIG_PPM,
                    label=_pmm_label,
                    quantity_unit=_pmm_unit,
                    window="hann",
                    nperseg=_psd_mod.recommended_welch_nperseg(len(_sub), target=16384),
                    overlap=0.5,
                    auto_scale_freq=True,
                    load_desc=LOAD_DESC or None,
                    acq_timestamp=_pmm_timestamp or None,
                    logo_path=_LOGO_PATH_A,
                    composite_png=_comp_png,
                    file_prefix=_PREFIX,
                )
                _pmm_results[_pmm_col] = _res

            print(f"[cdcu_monitor] PMM analysis complete: "
                  f"{len(_pmm_results)} channels")

        # ── DCBus input spectral analysis ─────────────────────────────────
        # The normal MRP/MGPC Ethernet readback path is NOT converted into FFT/PSD.
        # A valid DCBus capture must be hardware-timed at 10 kHz with exactly 100,001
        # samples. This replaces the inactive PMM Set Current spectral page.
        _dcbus_results = {}
        if _args.dcbus_spectrum_csv:
            print(f"[cdcu_monitor] Loading hardware-timed DCBus spectral capture: {_args.dcbus_spectrum_csv}")
            import cdcu_dcbus_fft as _dcbus_fft
            _dcbus_analysis_dir = os.path.join(_analysis_dir, "dcbus")
            _dcbus_results = _dcbus_fft.analyze_dcbus_csv(
                _args.dcbus_spectrum_csv,
                outdir=_dcbus_analysis_dir,
                prefix=f"{_PREFIX}_dcbus",
                load_desc=LOAD_DESC or None,
                logo_path=_LOGO_PATH_A,
                assume_10khz_when_no_time=bool(_args.dcbus_assume_10khz),
            )
            _pmm_results.update(_dcbus_results)
            print(f"[cdcu_monitor] DCBus spectral analysis complete: {len(_dcbus_results)} channels")
        else:
            print("[cdcu_monitor] DCBus FFT/PSD: no 10 kHz hardware capture supplied; Set Current FFT/PSD remains disabled.")

        # Live polling is intentionally excluded from FFT/PSD.
        # PMM is the authoritative output spectral source because it is hardware-timed
        # at 10 kHz. DCBus spectra likewise require a hardware-timed 10 kHz capture;
        # sequential MRP/MGPC Ethernet polling is never resampled into a fake PMM record.
        _poll_results = {}

        # ── Generate PDF ─────────────────────────────────────────────────
        print(f"[cdcu_monitor] Spectral channels in final report: {len(_pmm_results)}; live polling excluded from FFT/PSD")
        if _pmm_results:
            _pmm_pdf = os.path.join(_reports_dir, f"{_PREFIX}_pmm_summary.pdf")
            print(f"[cdcu_monitor] Writing PMM-only PDF: {_pmm_pdf}")
            _pdf_mod.build_pdf_summary(
                pdf_path=_pmm_pdf,
                csv_filename=os.path.basename(CSV_FILE),
                meta=_meta,
                results=_pmm_results,
                sig_threshold_ppm=_SIG_PPM,
                logo_path=_LOGO_PATH_A,
                logo_text=_LOGO_TEXT_A,
            )

        print(f"[cdcu_monitor] Analysis complete.  Reports → {_reports_dir}/")

    except ImportError as _imp_exc:
        print(f"[cdcu_monitor] Missing module: {_imp_exc}")
        print("  Ensure cdcu_ripple_analyzer.py, cdcu_ripple_psd.py, "
              "cdcu_ripple_pdf.py, cdcu_pmm.py, and cdcu_dcbus_fft.py are in the same directory.")
    except Exception as _exc:
        print(f"[cdcu_monitor] Analysis failed: {_exc}")
        raise

# ============================================================
# FINAL PROGRAM RUNTIME SUMMARY
# ============================================================
_PROGRAM_FINISH_LOCAL = datetime.now()
_TOTAL_RUNTIME_S = time.perf_counter() - _PROGRAM_START_MONO
print("\n── Program Runtime Summary ───────────────────────────────────")
print(f"[runtime] Live plot/data duration setting : {_format_runtime(DURATION)}")
if math.isfinite(_live_actual_duration_s):
    print(f"[runtime] Actual live polling duration    : {_format_runtime(_live_actual_duration_s)}")
else:
    print("[runtime] Actual live polling duration    : unavailable")
print(f"[runtime] Total runtime / supply          : {_format_runtime(_TOTAL_RUNTIME_S)}")
print(f"[runtime] Program start -> finish         : {_format_runtime(_TOTAL_RUNTIME_S)}")
print(f"[runtime] Program start                   : {_PROGRAM_START_LOCAL.strftime('%Y-%m-%d %H:%M:%S')}")
print(f"[runtime] Program finish                  : {_PROGRAM_FINISH_LOCAL.strftime('%Y-%m-%d %H:%M:%S')}")

