#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# Authored By: Byron Jordan
# Power Supply Engineer
# Advanced Photon Source (APS)
# Argonne National Laboratory
# ---------------------------------------------------------------------------
"""
cdcu_pmm.py

Post-Mortem Monitor (PMM) acquisition for CAEN CDCU power supplies.

The PMM captures 100,001 samples at a fixed 100 µs sampling interval
(Fs = 10 kHz, Nyquist = 5 kHz) across three channels:
    Channel 0 — Output Voltage  (V)
    Channel 1 — Output Current  (A)
    Channel 2 — Setpoint Current (A)

This gives a 10-second waveform window sufficient to resolve all three
spectral bands in the CDCU tool-chain:
    1–10 Hz      (require Fs ≥ 20 Hz    → PMM gives 10 000 Hz ✓)
    60–120 Hz    (require Fs ≥ 240 Hz   → PMM gives 10 000 Hz ✓)
    360–720 Hz   (require Fs ≥ 1 440 Hz → PMM gives 10 000 Hz ✓)

PMM buffer lifecycle
--------------------
1. Arm   : send PMM:RESET  (re-arms after a previous trigger)
2. Trigger: a fault event fills the buffer automatically, OR you can
           use the waveform generator to inject a test trigger.
3. Poll  : PMM:READY:?  → 1 when buffer is full and ready to read
4. Fetch : PMM:0:?  PMM:1:?  PMM:2:?  (each returns 100,001 colon-
           separated floats in one TCP response)
5. Reset : PMM:RESET  to rearm for the next event

Reference: CDCU Remote Control Manual Rev 1.3, Section 4.12

Usage
-----
    import socket
    from cdcu_pmm import PmmAcquisition

    with socket.create_connection(("192.168.3.2", 10001), timeout=5) as s:
        pmm = PmmAcquisition(s)
        pmm.set_trigger_position(4.0)   # 4 s pre-fault, 6 s post-fault
        pmm.arm()
        print("Waiting for PMM trigger ...")
        if pmm.wait_ready(timeout=60):
            df = pmm.fetch_dataframe()  # 100001-row DataFrame at 10 kHz
            ts = pmm.timestamp()
        else:
            print("PMM did not trigger within timeout")
"""

from __future__ import annotations

import socket
import time
from typing import Optional, Tuple

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PMM_FS_HZ      = 10_000.0          # fixed hardware sample rate (100 µs / sample)
PMM_N_SAMPLES  = 100_001           # samples per channel per acquisition
PMM_DURATION_S = PMM_N_SAMPLES / PMM_FS_HZ   # 10.0001 seconds

PMM_CHANNELS = {
    0: ("vout_V",   "V",  "PMM Output Voltage"),
    1: ("iout_A",   "A",  "PMM Output Current"),
    2: ("iset_A",   "A",  "PMM Setpoint Current"),
}


# ---------------------------------------------------------------------------
# Low-level TCP helpers
# ---------------------------------------------------------------------------

def _send_recv(sock: socket.socket, cmd: str, timeout: float = 5.0) -> str:
    """
    Send a CR-terminated command and read the response byte-by-byte until \n.

    Reading byte-by-byte (matching cdcu_pmm_force_fault_fft_win.py) is the
    most robust strategy for this firmware: PMM data payloads are very large
    (~1 MB per channel) but are terminated with a single newline, and
    byte-by-byte reading never truncates mid-payload.
    """
    # Restore the socket timeout expected by the next communication phase.
    sock.settimeout(timeout)
    # Carry out this step before advancing to the next part of the function.
    sock.sendall(f"{cmd}\r".encode("ascii"))

    # Capture buf here; the next step uses this intermediate result directly.
    buf = bytearray()
    # Stay in this loop until the stated completion condition changes.
    while True:
        # Protect this hardware or file operation so a failure is reported without obscuring where it happened.
        try:
            # Capture b here; the next step uses this intermediate result directly.
            b = sock.recv(1)
            # Take this branch only when the stated operating condition is true.
            if not b:
                # The required item is resolved, so leave this loop now.
                break
            # Carry out this step before advancing to the next part of the function.
            buf += b
            # Take this branch only when the stated operating condition is true.
            if b == b"\n":
                # The required item is resolved, so leave this loop now.
                break
        except socket.timeout:
            # The required item is resolved, so leave this loop now.
            break   # partial read — return what we have

    # Hand the finished value back to the caller.
    return buf.decode("ascii", errors="replace").strip()


def _parse_nak(resp: str) -> Optional[str]:
    """Return the error code string if the response is a NAK, else None."""
    # Take this branch only when the stated operating condition is true.
    if resp.startswith("#NAK"):
        # Hand the finished value back to the caller.
        return resp
    # Hand the finished value back to the caller.
    return None


# ---------------------------------------------------------------------------
# PmmAcquisition
# ---------------------------------------------------------------------------

class PmmAcquisition:
    """
    Manages the full PMM lifecycle over an open TCP socket.

    Parameters
    ----------
    sock            : Connected socket.socket to the CDCU unit.
    recv_timeout    : Per-recv timeout in seconds (default 10 s).
                      The PMM data response is ~800 KB; on a 100 Mbit LAN
                      this takes < 0.1 s, but allow headroom.
    """

    def __init__(self, sock: socket.socket, recv_timeout: float = 10.0) -> None:
        # Carry out this step before advancing to the next part of the function.
        self._sock = sock
        # Carry out this step before advancing to the next part of the function.
        self._recv_timeout = recv_timeout

    # ------------------------------------------------------------------
    # Control commands
    # ------------------------------------------------------------------

    def arm(self) -> bool:
        """
        Send PMM:RESET to arm (or rearm) the acquisition buffer.
        Returns True on #AK, False on #NAK.
        """
        # Capture resp here; the next step uses this intermediate result directly.
        resp = _send_recv(self._sock, "PMM:RESET", timeout=self._recv_timeout)
        # Capture ok here; the next step uses this intermediate result directly.
        ok = resp.startswith("#AK")
        # Take this branch only when the stated operating condition is true.
        if not ok:
            # Write this status to the console so the operator can follow the run in real time.
            print(f"[cdcu_pmm] PMM:RESET NAK: {resp}")
        # Hand the finished value back to the caller.
        return ok

    def force(self) -> bool:
        """
        Send PMM:FORCE to software-trigger the PMM buffer immediately.

        This fills the buffer without requiring a hardware fault event,
        allowing on-demand 10 kHz spectral captures during normal operation.
        Call arm() first, then force() after the desired delay.

        Returns True on #AK, False on #NAK.
        """
        # Capture resp here; the next step uses this intermediate result directly.
        resp = _send_recv(self._sock, "PMM:FORCE", timeout=self._recv_timeout)
        # Capture ok here; the next step uses this intermediate result directly.
        ok = resp.startswith("#AK")
        # Take this branch only when the stated operating condition is true.
        if not ok:
            # Write this status to the console so the operator can follow the run in real time.
            print(f"[cdcu_pmm] PMM:FORCE NAK: {resp}")
        # Hand the finished value back to the caller.
        return ok

    def set_trigger_position(self, pre_fault_s: float = 4.0) -> bool:
        """
        Set the trigger position (seconds of pre-fault data in the window).
        Valid range: 0–10 s.  Default 4 s = 4 s before fault, 6 s after.
        """
        # Capture pre_fault_s here; the next step uses this intermediate result directly.
        pre_fault_s = max(0.0, min(10.0, pre_fault_s))
        # Capture resp here; the next step uses this intermediate result directly.
        resp = _send_recv(
            self._sock,
            f"PMM:TRIG:{pre_fault_s:.1f}",
            timeout=self._recv_timeout,
        )
        # Capture ok here; the next step uses this intermediate result directly.
        ok = resp.startswith("#AK")
        # Take this branch only when the stated operating condition is true.
        if not ok:
            # Write this status to the console so the operator can follow the run in real time.
            print(f"[cdcu_pmm] PMM:TRIG NAK: {resp}")
        # Hand the finished value back to the caller.
        return ok

    def get_trigger_position(self) -> Optional[float]:
        """Query the current trigger position in seconds."""
        # Capture resp here; the next step uses this intermediate result directly.
        resp = _send_recv(self._sock, "PMM:TRIG:?", timeout=self._recv_timeout)
        # Take this branch only when the stated operating condition is true.
        if "NAK" in resp:
            # Hand the finished value back to the caller.
            return None
        # Protect this hardware or file operation so a failure is reported without obscuring where it happened.
        try:
            # Hand the finished value back to the caller.
            return float(resp.split(":")[-1].strip())
        except ValueError:
            # Hand the finished value back to the caller.
            return None

    def is_ready(self) -> bool:
        """Return True if the acquisition buffer is full and ready to read."""
        # Capture resp here; the next step uses this intermediate result directly.
        resp = _send_recv(self._sock, "PMM:READY:?", timeout=self._recv_timeout)
        # Take this branch only when the stated operating condition is true.
        if "NAK" in resp:
            # Hand the finished value back to the caller.
            return False
        # Protect this hardware or file operation so a failure is reported without obscuring where it happened.
        try:
            # Capture status here; the next step uses this intermediate result directly.
            status = int(resp.split(":")[-1].strip())
            # Hand the finished value back to the caller.
            return status == 1
        except ValueError:
            # Hand the finished value back to the caller.
            return False

    def wait_ready(
        self,
        timeout: float = 120.0,
        poll_interval: float = 0.2,
        verbose: bool = True,
    ) -> bool:
        """
        Poll PMM:READY:? every poll_interval seconds until READY=1 or timeout.
        Default poll_interval=0.2s matches the reference implementation.

        Returns True if the buffer became ready, False on timeout.
        """
        # Capture deadline here; the next step uses this intermediate result directly.
        deadline = time.monotonic() + timeout
        # Stay in this loop until the stated completion condition changes.
        while time.monotonic() < deadline:
            # Fetch the PMM buffer only after the hardware reports that the capture is complete.
            if self.is_ready():
                # Take this branch only when the stated operating condition is true.
                if verbose:
                    # Write this status to the console so the operator can follow the run in real time.
                    print("[cdcu_pmm] PMM buffer ready.")
                # Hand the finished value back to the caller.
                return True
            # Capture remaining here; the next step uses this intermediate result directly.
            remaining = deadline - time.monotonic()
            # Take this branch only when the stated operating condition is true.
            if verbose:
                # Write this status to the console so the operator can follow the run in real time.
                print(f"[cdcu_pmm] Waiting for PMM:READY=1 ... "
                      f"({remaining:.0f}s remaining)")
            # Carry out this step before advancing to the next part of the function.
            time.sleep(min(poll_interval, max(0.05, remaining)))
        # Write this status to the console so the operator can follow the run in real time.
        print(f"[cdcu_pmm] Timeout waiting for PMM:READY=1 after {timeout:.0f}s.")
        # Hand the finished value back to the caller.
        return False

    def timestamp(self) -> str:
        """
        Return the PMM acquisition timestamp string from the unit
        (e.g. 'FRI DEC 13 13:21:51 2019 GMT').
        Returns empty string on NAK or parse failure.
        """
        # Your firmware uses PMM:TIME:? (observed in cdcu_pmm_force_fault_fft_win.py)
        # Capture resp here; the next step uses this intermediate result directly.
        resp = _send_recv(self._sock, "PMM:TIME:?", timeout=self._recv_timeout)
        # Take this branch only when the stated operating condition is true.
        if "NAK" in resp:
            # Hand the finished value back to the caller.
            return ""
        # Format: #PMM:TIME:FRI DEC 13 13:21:51 2019 GMT
        # Capture parts here; the next step uses this intermediate result directly.
        parts = resp.split(":", 2)
        # Hand the finished value back to the caller.
        return parts[2].strip() if len(parts) >= 3 else resp

    # ------------------------------------------------------------------
    # Data retrieval
    # ------------------------------------------------------------------

    def fetch_channel(
        self, channel: int
    ) -> Tuple[np.ndarray, str, str, str]:
        """
        Fetch one PMM channel and return (samples, col_name, unit, label).

        The response format is:
            #PMM:0:s1:s2:s3:...:s100001
        Returns a float64 array of length PMM_N_SAMPLES.
        Raises ValueError on NAK or parse failure.
        """
        # Take this branch only when the stated operating condition is true.
        if channel not in PMM_CHANNELS:
            # Raise a specific error instead of allowing bad input to propagate into the analysis.
            raise ValueError(f"Invalid PMM channel {channel}. Valid: {list(PMM_CHANNELS)}")

        # Carry out this step before advancing to the next part of the function.
        col_name, unit, label = PMM_CHANNELS[channel]

        # Large response — use longer timeout.
        # Command is "PMM:0" (no ":?") per CAEN CDCU firmware behaviour.
        # Capture resp here; the next step uses this intermediate result directly.
        resp = _send_recv(
            self._sock,
            f"PMM:{channel}",
            timeout=max(self._recv_timeout, 30.0),
        )

        # Take this branch only when the stated operating condition is true.
        if resp.startswith("#NAK"):
            # Raise a specific error instead of allowing bad input to propagate into the analysis.
            raise ValueError(
                f"[cdcu_pmm] PMM:{channel} returned NAK: {resp}\n"
                f"  Ensure the buffer is ready (PMM:READY:? = 1) before fetching."
            )

        # Strip echo prefix.
        # Firmware returns "#PMM:0:s1:s2:..." or "#PPM:s1:s2:..." (firmware typo).
        # Handle both: if prefix is #PPM (no channel token), skip directly to data.
        # Take this branch only when the stated operating condition is true.
        if resp.upper().startswith("#PPM:"):
            # Capture raw_samples here; the next step uses this intermediate result directly.
            raw_samples = resp[len("#PPM:"):]
        else:
            # Capture parts here; the next step uses this intermediate result directly.
            parts = resp.split(":", 2)
            # Make sure enough samples are available before running the calculation.
            if len(parts) < 3:
                # Raise a specific error instead of allowing bad input to propagate into the analysis.
                raise ValueError(
                    f"[cdcu_pmm] Unexpected PMM response format: {resp[:80]}"
                )
            # Capture raw_samples here; the next step uses this intermediate result directly.
            raw_samples = parts[2]
        # Capture raw_samples here; the next step uses this intermediate result directly.
        raw_samples = raw_samples.strip()
        # Protect this hardware or file operation so a failure is reported without obscuring where it happened.
        try:
            # Capture samples here; the next step uses this intermediate result directly.
            samples = np.fromstring(raw_samples, dtype=float, sep=":")
        except Exception as exc:
            # Raise a specific error instead of allowing bad input to propagate into the analysis.
            raise ValueError(
                f"[cdcu_pmm] Failed to parse PMM:{channel} samples: {exc}"
            ) from exc

        # Make sure enough samples are available before running the calculation.
        if len(samples) < 1000:
            # Raise a specific error instead of allowing bad input to propagate into the analysis.
            raise ValueError(
                f"[cdcu_pmm] PMM:{channel} returned only {len(samples)} samples "
                f"(expected {PMM_N_SAMPLES}). Buffer may not be fully filled."
            )

        # Write this status to the console so the operator can follow the run in real time.
        print(f"[cdcu_pmm] Channel {channel} ({label}): "
              f"{len(samples)} samples at {PMM_FS_HZ:.0f} Hz")
        # Hand the finished value back to the caller.
        return samples, col_name, unit, label

    def fetch_dataframe(
        self,
        channels: Optional[list] = None,
        channel_scales: Optional[dict] = None,
    ) -> pd.DataFrame:
        """
        Fetch all (or specified) PMM channels and return a tidy DataFrame.

        Parameters
        ----------
        channels       : List of channel numbers to fetch (default: [0, 1, 2]).
        channel_scales : Optional dict of {channel_int: scale_factor} for
                         physical unit conversion (e.g. {1: 500.0} for a
                         500 A/V current shunt — matching ripple_exec.py
                         V_TO_I_SCALE).

        Returns
        -------
        DataFrame with columns:
            time_s      : sample time axis (0 .. ~10 s at 100 µs steps)
            vout_V      : output voltage (V)
            iout_A      : output current (A)
            iset_A      : setpoint current (A)
        """
        # Take this branch only when the stated operating condition is true.
        if channels is None:
            # Capture channels here; the next step uses this intermediate result directly.
            channels = list(PMM_CHANNELS.keys())
        # Take this branch only when the stated operating condition is true.
        if channel_scales is None:
            # Capture channel_scales here; the next step uses this intermediate result directly.
            channel_scales = {}

        # Capture n_actual here; the next step uses this intermediate result directly.
        n_actual = None
        # Initialize data as the working collection for this part of the run.
        data = {}

        # Walk the collection in order so every item receives the same treatment.
        for ch in channels:
            # Protect this hardware or file operation so a failure is reported without obscuring where it happened.
            try:
                # Carry out this step before advancing to the next part of the function.
                samples, col_name, _unit, _label = self.fetch_channel(ch)
                # Capture scale here; the next step uses this intermediate result directly.
                scale = channel_scales.get(ch, 1.0)
                # Capture data[col_name] here; the next step uses this intermediate result directly.
                data[col_name] = samples * scale
                # Take this branch only when the stated operating condition is true.
                if n_actual is None:
                    # Capture n_actual here; the next step uses this intermediate result directly.
                    n_actual = len(samples)
            except ValueError as exc:
                # Write this status to the console so the operator can follow the run in real time.
                print(f"[cdcu_pmm] WARNING: {exc}")

        # Take this branch only when the stated operating condition is true.
        if not data:
            # Raise a specific error instead of allowing bad input to propagate into the analysis.
            raise RuntimeError("[cdcu_pmm] No PMM channels could be fetched.")

        # Capture n here; the next step uses this intermediate result directly.
        n = n_actual or PMM_N_SAMPLES
        # Capture t here; the next step uses this intermediate result directly.
        t = np.arange(n, dtype=float) / PMM_FS_HZ

        # Load the source data into a DataFrame for numeric processing.
        df = pd.DataFrame({"time_s": t})
        # Walk the collection in order so every item receives the same treatment.
        for col, arr in data.items():
            # Pad or truncate to match time axis length
            # Make sure enough samples are available before running the calculation.
            if len(arr) > n:
                # Capture df[col] here; the next step uses this intermediate result directly.
                df[col] = arr[:n]
            # Make sure enough samples are available before running the calculation.
            elif len(arr) < n:
                # Capture padded here; the next step uses this intermediate result directly.
                padded = np.full(n, np.nan)
                # Capture padded[:len(arr)] here; the next step uses this intermediate result directly.
                padded[:len(arr)] = arr
                # Capture df[col] here; the next step uses this intermediate result directly.
                df[col] = padded
            else:
                # Capture df[col] here; the next step uses this intermediate result directly.
                df[col] = arr

        # Hand the finished value back to the caller.
        return df


# ---------------------------------------------------------------------------
# Convenience function for cdcu_monitor.py integration
# ---------------------------------------------------------------------------

def acquire_pmm(
    host: str,
    port: int = 10001,
    pre_fault_s: float = 4.0,
    wait_timeout: float = 120.0,
    channel_scales: Optional[dict] = None,
    verbose: bool = True,
    sock: Optional[socket.socket] = None,
) -> Tuple[Optional[pd.DataFrame], str]:
    """
    High-level convenience: connect (or reuse *sock*), arm, wait, fetch.

    If *sock* is provided it is reused (the caller is responsible for
    keeping it open).  Otherwise a new connection is made and closed.

    Returns
    -------
    (df, timestamp_str)  — df is None if acquisition failed or timed out.
    """
    # Capture own_sock here; the next step uses this intermediate result directly.
    own_sock = sock is None

    # Protect this hardware or file operation so a failure is reported without obscuring where it happened.
    try:
        # Take this branch only when the stated operating condition is true.
        if own_sock:
            # Capture sock here; the next step uses this intermediate result directly.
            sock = socket.create_connection((host, port), timeout=5.0)

        # Capture pmm here; the next step uses this intermediate result directly.
        pmm = PmmAcquisition(sock, recv_timeout=30.0)

        # Take this branch only when the stated operating condition is true.
        if verbose:
            # Write this status to the console so the operator can follow the run in real time.
            print(f"[cdcu_pmm] Arming PMM on {host}:{port} ...")
        # Take this branch only when the stated operating condition is true.
        if not pmm.arm():
            # Write this status to the console so the operator can follow the run in real time.
            print("[cdcu_pmm] PMM:RESET failed — PMM acquisition aborted.")
            # Hand the finished value back to the caller.
            return None, ""

        # Carry out this step before advancing to the next part of the function.
        pmm.set_trigger_position(pre_fault_s)

        # Take this branch only when the stated operating condition is true.
        if verbose:
            # Write this status to the console so the operator can follow the run in real time.
            print(f"[cdcu_pmm] PMM armed. Trigger window: "
                  f"{pre_fault_s:.1f}s pre / "
                  f"{PMM_DURATION_S - pre_fault_s:.1f}s post fault. "
                  f"Waiting up to {wait_timeout:.0f}s ...")

        # Fetch the PMM buffer only after the hardware reports that the capture is complete.
        if not pmm.wait_ready(timeout=wait_timeout, verbose=verbose):
            # Hand the finished value back to the caller.
            return None, ""

        # Capture ts here; the next step uses this intermediate result directly.
        ts = pmm.timestamp()
        # Load the source data into a DataFrame for numeric processing.
        df = pmm.fetch_dataframe(channel_scales=channel_scales)
        # Hand the finished value back to the caller.
        return df, ts

    except Exception as exc:
        # Write this status to the console so the operator can follow the run in real time.
        print(f"[cdcu_pmm] ERROR during PMM acquisition: {exc}")
        # Hand the finished value back to the caller.
        return None, ""

    finally:
        # Take this branch only when the stated operating condition is true.
        if own_sock and sock is not None:
            # Protect this hardware or file operation so a failure is reported without obscuring where it happened.
            try:
                # Carry out this step before advancing to the next part of the function.
                sock.close()
            except Exception:
                # No action is required in this branch; keep the control flow explicit.
                pass
