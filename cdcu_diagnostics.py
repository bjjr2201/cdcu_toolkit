#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# Authored By: Byron Jordan
# Power Supply Engineer
# Advanced Photon Source (APS)
# Argonne National Laboratory
# ---------------------------------------------------------------------------
"""Engineering diagnostics for CAENels CDCU-100/200/300 converters.

Manufacturer full-load efficiency minima are from CAENels CDCU User's Manual
Rev. 1.0, Technical Specifications (page 42): CDCU-100 >92%, CDCU-200 >94%,
CDCU-300 >97%. These are compliance floors, not nominal efficiencies.

Dynamic power-balance calculations are de-emphasized during ramps because MRP,
MGPC, MRV and MRI are polled sequentially (not synchronously) and stored-energy
exchange in converter capacitors / magnet inductance can distort instantaneous
Pin/Pout comparison.
"""
from __future__ import annotations
import math
from collections import deque
from typing import Deque, Dict, Optional, Tuple

MODEL_EFFICIENCY_REFERENCE: Dict[str, Dict[str, float]] = {
    "CDCU-100": {
        "eta_full_load_min": 0.92,
        "rated_A": 100.0,
        "rated_V": 15.0,
        "rated_W": 1500.0,
        "switching_frequency_Hz": 100000.0,
        "equivalent_switching_frequency_Hz": 100000.0,
    },
    "CDCU-200": {
        "eta_full_load_min": 0.94,
        "rated_A": 200.0,
        "rated_V": 15.0,
        "rated_W": 3000.0,
        "switching_frequency_Hz": 100000.0,
        "equivalent_switching_frequency_Hz": 200000.0,
    },
    "CDCU-300": {
        "eta_full_load_min": 0.97,
        "rated_A": 300.0,
        "rated_V": 45.0,
        "rated_W": 13500.0,
        "switching_frequency_Hz": 100000.0,
        "equivalent_switching_frequency_Hz": 300000.0,
    },
}
# Optional empirical per-model baselines. Populate only after establishing a
# defensible healthy fleet baseline. Per-unit load-map override always wins.
MODEL_EMPIRICAL_ETA_REFERENCE: Dict[str, float] = {}
MIN_DIAGNOSTIC_LOAD_FRACTION = 0.25
CAEN_FULL_LOAD_MIN_FRACTION = 0.95
MAX_IBUS_PCT_ERROR_WARNING = 5.0
MAX_EFFICIENCY_DEVIATION_PCT_POINTS = 3.0
INVESTIGATE_PERSISTENCE_S = 2.0


def _is_bad(x) -> bool:
    # Protect this hardware or file operation so a failure is reported without obscuring where it happened.
    try:
        # Hand the finished value back to the caller.
        return not math.isfinite(float(x))
    except (TypeError, ValueError):
        # Hand the finished value back to the caller.
        return True


def percent_to_ppm(percent: float) -> float:
    """Convert percent to ppm: 1% = 10,000 ppm."""
    # Return NaN to mark this point unusable without inventing a numeric result.
    return math.nan if _is_bad(percent) else float(percent) * 1.0e4




def percent_point_delta_to_abs_ppm(delta_percentage_points: float) -> float:
    """Convert a percentage-point difference to absolute fractional ppm.

    Example: 97.0% - 96.4% = 0.6 percentage points = 0.006 fraction
    = 6,000 ppm on an absolute fractional basis. This is not a relative error
    referenced to 97%.
    """
    return math.nan if _is_bad(delta_percentage_points) else float(delta_percentage_points) * 1.0e4


def relative_percent_difference_ppm(value_pct: float, reference_pct: float) -> float:
    """Return relative ppm difference of one percentage value from another.

    This answers 'ppm relative to what?' explicitly by using reference_pct as
    the denominator: ((value-reference)/reference)*1e6.
    """
    if _is_bad(value_pct) or _is_bad(reference_pct) or float(reference_pct) == 0.0:
        return math.nan
    return ((float(value_pct) - float(reference_pct)) / abs(float(reference_pct))) * 1.0e6

def get_model_spec(model: Optional[str]) -> Optional[Dict[str, float]]:
    # Hand the finished value back to the caller.
    return MODEL_EFFICIENCY_REFERENCE.get((model or "").strip().upper())


def eta_reference_for_model(model: Optional[str], override: Optional[float] = None) -> float:
    """Expected efficiency baseline with provenance handled by eta_reference_details()."""
    # Carry out this step before advancing to the next part of the function.
    eta, _ = eta_reference_details(model, override)
    # Hand the finished value back to the caller.
    return eta


def eta_reference_details(model: Optional[str], override: Optional[float] = None) -> Tuple[float, str]:
    # Normalize the model identifier once so every lookup uses the same key.
    key = (model or "").strip().upper()
    # Reject invalid telemetry here; downstream math is only useful with finite values.
    if override is not None and not _is_bad(override):
        # Capture override here; the next step uses this intermediate result directly.
        override = float(override)
        # Use the unit-specific baseline when one was supplied and passed validation.
        if not 0.70 <= override <= 1.00:
            # Raise a specific error instead of allowing bad input to propagate into the analysis.
            raise ValueError(f"eta_reference override must be 70-100%; got {override*100:.3f}%")
        # Hand the finished value back to the caller.
        return override, "unit_override"
    # Read the configured model baseline, if one has been established.
    empirical = MODEL_EMPIRICAL_ETA_REFERENCE.get(key)
    # Use the model baseline next when no unit-specific value is available.
    if empirical is not None:
        # Use the model baseline next when no unit-specific value is available.
        if not 0.70 <= empirical <= 1.00:
            # Raise a specific error instead of allowing bad input to propagate into the analysis.
            raise ValueError(f"Invalid model empirical eta reference for {key}: {empirical}")
        # Hand the finished value back to the caller.
        return empirical, "model_baseline"
    # Pull the model ratings and CAEN limits used by the checks below.
    spec = get_model_spec(key)
    # Take this branch only when the stated operating condition is true.
    if spec:
        # Hand the finished value back to the caller.
        return spec["eta_full_load_min"], "caen_minimum"
    # Return NaN to mark this point unusable without inventing a numeric result.
    return math.nan, "unknown"


def investigate_threshold_for_model(model: Optional[str]) -> float:
    # Pull the model ratings and CAEN limits used by the checks below.
    spec = get_model_spec(model)
    # Return NaN to mark this point unusable without inventing a numeric result.
    return spec["eta_full_load_min"] if spec else math.nan


def calculate_power(voltage: float, current: float) -> float:
    # Reject invalid telemetry here; downstream math is only useful with finite values.
    if _is_bad(voltage) or _is_bad(current):
        # Return NaN to mark this point unusable without inventing a numeric result.
        return math.nan
    # Hand the finished value back to the caller.
    return abs(float(voltage) * float(current))


def calculate_efficiency_percent(v_out: float, i_out: float, v_bus: float, i_bus: float) -> float:
    # Calculate DC input power from the measured bus voltage and current.
    pin = calculate_power(v_bus, i_bus)
    # Calculate delivered output power from the measured output voltage and current.
    pout = calculate_power(v_out, i_out)
    # Reject invalid telemetry here; downstream math is only useful with finite values.
    if _is_bad(pin) or _is_bad(pout) or pin <= 0:
        # Return NaN to mark this point unusable without inventing a numeric result.
        return math.nan
    # Hand the finished value back to the caller.
    return 100.0 * pout / pin


def expected_input_current(v_out: float, i_out: float, v_bus: float, eta_reference: float) -> float:
    # Reject invalid telemetry here; downstream math is only useful with finite values.
    if any(_is_bad(x) for x in (v_out, i_out, v_bus, eta_reference)):
        # Return NaN to mark this point unusable without inventing a numeric result.
        return math.nan
    # Take this branch only when the stated operating condition is true.
    if v_bus <= 0 or eta_reference <= 0:
        # Return NaN to mark this point unusable without inventing a numeric result.
        return math.nan
    # Calculate the input current implied by output power, bus voltage, and the efficiency baseline.
    expected = calculate_power(v_out, i_out) / (v_bus * eta_reference)
    # Return NaN to mark this point unusable without inventing a numeric result.
    return expected if expected > 0 else math.nan


def bus_current_percent_error(i_bus_actual: float, i_bus_expected: float) -> Tuple[float, float]:
    # Reject invalid telemetry here; downstream math is only useful with finite values.
    if _is_bad(i_bus_actual) or _is_bad(i_bus_expected) or i_bus_expected <= 0:
        # Return NaN to mark this point unusable without inventing a numeric result.
        return math.nan, math.nan
    # Calculate the signed difference between measured and expected input current.
    delta = float(i_bus_actual) - float(i_bus_expected)
    # Hand the finished value back to the caller.
    return delta, 100.0 * delta / float(i_bus_expected)


def calculate_load_fraction(model: Optional[str], p_out_w: float) -> float:
    # Pull the model ratings and CAEN limits used by the checks below.
    spec = get_model_spec(model)
    # Reject invalid telemetry here; downstream math is only useful with finite values.
    if spec is None or _is_bad(p_out_w) or spec["rated_W"] <= 0:
        # Return NaN to mark this point unusable without inventing a numeric result.
        return math.nan
    # Hand the finished value back to the caller.
    return max(0.0, float(p_out_w) / spec["rated_W"])


def substantial_load(model: Optional[str], p_out_w: float, min_fraction: float = MIN_DIAGNOSTIC_LOAD_FRACTION) -> bool:
    # Convert output power to a fraction of the model rating.
    frac = calculate_load_fraction(model, p_out_w)
    # Hand the finished value back to the caller.
    return not _is_bad(frac) and frac >= min_fraction


def efficiency_health(eff_pct: float, eta_reference: float,
                      max_deviation_pct_points: float = MAX_EFFICIENCY_DEVIATION_PCT_POINTS) -> str:
    """Classify deviation from the selected diagnostic efficiency baseline.

    This is intentionally separate from CAEN full-load compliance. A 25%-load
    operating point can be useful for trending against a known-good baseline,
    but it cannot be declared compliant/noncompliant with a specification that
    CAEN states specifically at full load.
    """
    if _is_bad(eff_pct) or _is_bad(eta_reference):
        return "invalid"
    reference_pct = float(eta_reference) * 100.0
    return "investigate" if (reference_pct - float(eff_pct)) >= max_deviation_pct_points else "healthy"


def caen_efficiency_compliance(model: Optional[str], eff_pct: float, load_fraction: float,
                               full_load_min_fraction: float = CAEN_FULL_LOAD_MIN_FRACTION) -> str:
    """Evaluate CAEN's efficiency specification only near rated full load.

    Returns 'pass', 'fail', 'not_applicable', 'invalid', or 'unknown_model'.
    CAEN Rev. 1.0 specifies efficiency at full load, so lower-power operation is
    not treated as a manufacturer compliance test.
    """
    if _is_bad(eff_pct) or _is_bad(load_fraction):
        return "invalid"
    spec = get_model_spec(model)
    if spec is None:
        return "unknown_model"
    if float(load_fraction) < float(full_load_min_fraction):
        return "not_applicable"
    minimum_pct = spec["eta_full_load_min"] * 100.0
    return "pass" if float(eff_pct) > minimum_pct else "fail"


def power_loss(pin_w: float, pout_w: float) -> Tuple[float, float]:
    # Reject invalid telemetry here; downstream math is only useful with finite values.
    if _is_bad(pin_w) or _is_bad(pout_w) or pin_w <= 0:
        # Return NaN to mark this point unusable without inventing a numeric result.
        return math.nan, math.nan
    # Calculate the input-to-output power difference for the loss check.
    loss = float(pin_w) - float(pout_w)
    # Hand the finished value back to the caller.
    return loss, 100.0 * loss / float(pin_w)


def diagnostic_state(*, telemetry_valid: bool, model_known: bool, is_steady: bool,
                     is_substantial_load: bool, health: str) -> str:
    # Take this branch only when the stated operating condition is true.
    if not telemetry_valid:
        # Hand the finished value back to the caller.
        return "invalid"
    # Take this branch only when the stated operating condition is true.
    if not model_known:
        # Hand the finished value back to the caller.
        return "unknown_model"
    # Keep transient data out of the steady-state engineering comparison.
    if not is_steady:
        # Hand the finished value back to the caller.
        return "transient"
    # Do not judge full-load performance until the load is high enough to make that comparison meaningful.
    if not is_substantial_load:
        # Hand the finished value back to the caller.
        return "low_load"
    # Return the engineering state produced by the checks above.
    return "investigate" if health == "investigate" else "healthy"


def diagnostic_confidence(eta_source: str, diagnostic_valid: bool) -> str:
    # Take this branch only when the stated operating condition is true.
    if not diagnostic_valid:
        # Hand the finished value back to the caller.
        return "low"
    # Use the unit-specific baseline when one was supplied and passed validation.
    if eta_source == "unit_override":
        # Hand the finished value back to the caller.
        return "high"
    # Take this branch only when the stated operating condition is true.
    if eta_source == "model_baseline":
        # Hand the finished value back to the caller.
        return "medium"
    # Hand the finished value back to the caller.
    return "low"


class PlateauDetector:
    def __init__(self, window_s: float = 3.0, min_dwell_s: float = 2.0,
                 tol_pct: float = 2.0, tol_abs: float = 0.05) -> None:
        # Carry out this step before advancing to the next part of the function.
        self.window_s = window_s; self.min_dwell_s = min_dwell_s
        # Carry out this step before advancing to the next part of the function.
        self.tol_pct = tol_pct; self.tol_abs = tol_abs
        # Carry out this step before advancing to the next part of the function.
        self._buf: Deque[Tuple[float, float]] = deque()

    def update(self, t: float, value: float) -> bool:
        # Reject invalid telemetry here; downstream math is only useful with finite values.
        if _is_bad(value) or _is_bad(t): return False
        # Add this observation to the ordered history so the sequence is preserved.
        self._buf.append((float(t), float(value)))
        # Set the oldest timestamp that still belongs in the active plateau window.
        cutoff = float(t) - self.window_s
        # Stay in this loop until the stated completion condition changes.
        while self._buf and self._buf[0][0] < cutoff: self._buf.popleft()
        # Take this branch only when the stated operating condition is true.
        if not self._buf or self._buf[-1][0] - self._buf[0][0] < self.min_dwell_s: return False
        # Pull only the sampled values from the time/value buffer for the stability check.
        vals = [v for _, v in self._buf]
        # Calculate the window mean used as the plateau reference.
        mean = sum(vals) / len(vals)
        # Use the larger of the absolute and percent tolerances for the plateau decision.
        tol = max(self.tol_abs, abs(mean) * self.tol_pct / 100.0)
        # Hand the finished value back to the caller.
        return max(abs(v - mean) for v in vals) <= tol

    def reset(self) -> None:
        # Clear the previous state before starting a new evaluation window.
        self._buf.clear()
