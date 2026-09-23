#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# Authored By: Byron Jordan
# Power Supply Engineer
# Advanced Photon Source (APS)
# Argonne National Laboratory
# ---------------------------------------------------------------------------
"""
cdcu_ripple_pdf.py   (renamed from ps_ripple_pdf_summary.py)

Creates:
  1) ripple_summary.pdf   – professional 8.5×11, embedded plots
  2) Technician worksheet – DOCX + PDF, pre-populated from metadata + analysis

Changes from ps_ripple_pdf_summary.py:
- build_pdf_summary() now renders a per-channel Band RMS table
  (1-10 Hz, 60-120 Hz, 360-720 Hz, 720-1200 Hz) on each channel detail page.
- Column/band labels are pulled from cdcu_ripple_bands so they stay
  in sync with the analyzer automatically.
- All other layout and footer logic is unchanged.

IMPORTANT DESIGN RULE:
- This module generates files only.
- It does NOT auto-open files.
"""

from __future__ import annotations

import os
from typing import Dict, List

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

try:
    from docx import Document
except Exception:
    Document = None  # type: ignore

from cdcu_ripple_bands import ANALYSIS_BANDS


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _safe_draw_image(
    c: canvas.Canvas, path: str, x: float, y: float, w: float, h: float,
    strip_plot_branding: bool = False,
) -> bool:
    """Draw an image safely while preserving transparency.

    When ``strip_plot_branding`` is True, only the small lower-right logo that
    is baked into a standalone FFT/PSD plot is masked before the plot is placed
    into the PDF.  The standalone PNG remains branded; the PDF page then shows
    only the larger official footer logo once.
    """
    if not path or not os.path.isfile(path):
        return False
    try:
        if strip_plot_branding:
            from PIL import Image as _PILImage, ImageDraw as _ImageDraw
            _pil = _PILImage.open(path).convert("RGBA")
            _pw, _ph = _pil.size
            # Plot footers reserve the lower strip for timestamp/logo content.
            # Mask only the lower-right logo region; leave the lower-left
            # acquisition/generation timestamp intact.
            _draw = _ImageDraw.Draw(_pil)
            _draw.rectangle(
                [int(_pw * 0.67), int(_ph * 0.89), _pw, _ph],
                fill=(255, 255, 255, 255),
            )
            img = ImageReader(_pil)
        else:
            img = ImageReader(path)
        c.drawImage(
            img, x, y, width=w, height=h,
            preserveAspectRatio=True, anchor="c", mask="auto"
        )
        return True
    except Exception:
        return False


def _draw_footer(c: canvas.Canvas, logo_path: str, logo_text: str | None = None) -> None:
    """Draw APS/Argonne branding at the lower-right footer location.

    The transparent PNG is the primary branding element.  ``logo_text`` remains
    optional for backward compatibility, but the normal toolkit path leaves it
    unset so the image replaces the older typed footer text.
    """
    W, _H = letter
    right_margin = 0.40 * inch
    bottom_margin = 0.10 * inch

    # Revision 17: anchor the transparent APS/Argonne brand block in the
    # bottom-right page footer.  The image itself contains the white-background-
    # safe APS wordmark; mask="auto" preserves the PNG alpha channel.
    logo_w = 2.75 * inch
    logo_h = 0.62 * inch
    logo_x = W - right_margin - logo_w
    logo_y = bottom_margin
    _safe_draw_image(c, logo_path, logo_x, logo_y, logo_w, logo_h)

    footer_y = bottom_margin + 0.12 * inch

    # The text path is retained only for callers that deliberately request it.
    if logo_text:
        c.setFont("Helvetica", 9)
        text_w = c.stringWidth(logo_text, "Helvetica", 9)
        c.drawString(W - margin - text_w, footer_y, logo_text)


def _draw_header(
    c: canvas.Canvas,
    csv_filename: str,
    meta: Dict[str, str],
    sig_threshold_ppm: float,
) -> float:
    """
    Draw the page 1 header block including load map data and serial number.
    Returns the y position after the last line drawn.
    """
    # Carry out this step before advancing to the next part of the function.
    W, H = letter
    # Capture margin here; the next step uses this intermediate result directly.
    margin = 0.75 * inch
    # Capture x0 here; the next step uses this intermediate result directly.
    x0 = margin
    # Capture y here; the next step uses this intermediate result directly.
    y = H - margin

    # Carry out this step before advancing to the next part of the function.
    c.setFont("Helvetica-Bold", 14)
    # Carry out this step before advancing to the next part of the function.
    c.drawString(x0, y, "CDCU Ripple / FFT / PSD Summary")
    # Carry out this step before advancing to the next part of the function.
    y -= 18

    # ── Load map identity block ──────────────────────────────────────────────
    # Capture magnet_id here; the next step uses this intermediate result directly.
    magnet_id  = meta.get("magnet_id", "")
    # Capture serial_num here; the next step uses this intermediate result directly.
    serial_num = meta.get("serial_number", "")
    # Capture cabinet here; the next step uses this intermediate result directly.
    cabinet    = meta.get("cabinet",    "")
    # Capture host here; the next step uses this intermediate result directly.
    host       = meta.get("ip",         "")
    # Capture sector here; the next step uses this intermediate result directly.
    sector     = meta.get("sector",     "")
    # Capture load_desc here; the next step uses this intermediate result directly.
    load_desc  = meta.get("load_desc",  "")
    # Capture raw_v here; the next step uses this intermediate result directly.
    raw_v      = meta.get("raw_V",      "")
    # Capture v_out here; the next step uses this intermediate result directly.
    v_out      = meta.get("v_out_rating", "")
    # Capture dcbus_ref here; the next step uses this intermediate result directly.
    dcbus_ref  = meta.get("dcbus_ref_V", "")
    # Capture idc_ref here; the next step uses this intermediate result directly.
    idc_ref    = meta.get("idc_ref_A",   "")

    # Carry out this step before advancing to the next part of the function.
    c.setFont("Helvetica", 10)
    # Take this branch only when the stated operating condition is true.
    if magnet_id or serial_num:
        # Capture id_str here; the next step uses this intermediate result directly.
        id_str = magnet_id
        # Take this branch only when the stated operating condition is true.
        if serial_num:
            # Capture id_str here; the next step uses this intermediate result directly.
            id_str = f"{id_str}   SN: {serial_num}" if id_str else f"SN: {serial_num}"
        # Carry out this step before advancing to the next part of the function.
        c.setFont("Helvetica-Bold", 11)
        # Carry out this step before advancing to the next part of the function.
        c.drawString(x0, y, id_str)
        # Carry out this step before advancing to the next part of the function.
        c.setFont("Helvetica", 10)
        # Carry out this step before advancing to the next part of the function.
        y -= 14

    # Take this branch only when the stated operating condition is true.
    if host or cabinet:
        # Capture loc_parts here; the next step uses this intermediate result directly.
        loc_parts = []
        # Take this branch only when the stated operating condition is true.
        if host:     loc_parts.append(f"Host: {host}")
        # Take this branch only when the stated operating condition is true.
        if cabinet:  loc_parts.append(f"Cabinet: {cabinet}")
        # Take this branch only when the stated operating condition is true.
        if sector:   loc_parts.append(f"Sector: {sector}")
        # Carry out this step before advancing to the next part of the function.
        c.drawString(x0, y, "  ".join(loc_parts))
        # Carry out this step before advancing to the next part of the function.
        y -= 13

    # Take this branch only when the stated operating condition is true.
    if raw_v or v_out:
        # Capture v_parts here; the next step uses this intermediate result directly.
        v_parts = []
        # Take this branch only when the stated operating condition is true.
        if raw_v:  v_parts.append(f"DC Bus: {raw_v} V")
        # Take this branch only when the stated operating condition is true.
        if v_out:  v_parts.append(f"Vout rated: {v_out} V")
        # Take this branch only when the stated operating condition is true.
        if dcbus_ref: v_parts.append(f"Vbus ref: {dcbus_ref} V")
        # Take this branch only when the stated operating condition is true.
        if idc_ref:   v_parts.append(f"Idc ref: {idc_ref} A")
        # Carry out this step before advancing to the next part of the function.
        c.drawString(x0, y, "  |  ".join(v_parts))
        # Carry out this step before advancing to the next part of the function.
        y -= 13

    # Do not judge full-load performance until the load is high enough to make that comparison meaningful.
    if load_desc:
        # Split on ';' for compact multi-token display
        # Capture parts here; the next step uses this intermediate result directly.
        parts = [p.strip() for p in load_desc.split(";") if p.strip()]
        # Carry out this step before advancing to the next part of the function.
        c.drawString(x0, y, "; ".join(parts[:3]))
        # Make sure enough samples are available before running the calculation.
        if len(parts) > 3:
            # Carry out this step before advancing to the next part of the function.
            y -= 12
            # Carry out this step before advancing to the next part of the function.
            c.drawString(x0, y, "; ".join(parts[3:]))
        # Carry out this step before advancing to the next part of the function.
        y -= 14

    # Horizontal rule under identity block
    # Carry out this step before advancing to the next part of the function.
    c.setLineWidth(0.5)
    # Carry out this step before advancing to the next part of the function.
    c.line(x0, y + 4, W - margin, y + 4)
    # Carry out this step before advancing to the next part of the function.
    y -= 6

    # ── File / timestamps ────────────────────────────────────────────────────
    # Carry out this step before advancing to the next part of the function.
    c.setFont("Helvetica", 10)
    # Carry out this step before advancing to the next part of the function.
    c.drawString(x0, y, f"Data File: {csv_filename}")
    # Carry out this step before advancing to the next part of the function.
    y -= 13

    # Capture generated here; the next step uses this intermediate result directly.
    generated   = meta.get("generated_local",  meta.get("generated_local_iso", ""))
    # Capture event_local here; the next step uses this intermediate result directly.
    event_local = meta.get("event_local",       meta.get("event_local_iso", ""))
    # Carry out this step before advancing to the next part of the function.
    c.drawString(x0, y, f"Generated: {generated}")
    # Carry out this step before advancing to the next part of the function.
    c.drawString(x0 + 3.6 * inch, y, f"Acquired: {event_local}")
    # Carry out this step before advancing to the next part of the function.
    y -= 13

    # Carry out this step before advancing to the next part of the function.
    c.drawString(x0, y, f"Significance threshold: {sig_threshold_ppm:g} ppm")
    # Carry out this step before advancing to the next part of the function.
    y -= 14

    # Hand the finished value back to the caller.
    return y


def _draw_load_map_block(
    c: canvas.Canvas,
    x0: float,
    y: float,
    meta: Dict[str, str],
    fs_hz: float,
) -> float:
    """
    Draw a compact load map identity + Fs advisory box above the Band RMS
    table on each per-channel detail page.

    Fs Advisory
    -----------
    Fs is derived from the median sample interval of burst_midpoint_s.
    The Nyquist limit Fs/2 determines the highest frequency resolvable.
    Required intervals per band:
        1–10 Hz   → Fs ≥ 20 Hz   → INTERVAL ≤ 0.050 s
        60–120 Hz → Fs ≥ 240 Hz  → INTERVAL ≤ 0.004 s
        360-720 Hz  -> Fs >= 1440 Hz -> INTERVAL <= 0.0007 s
        720-1200 Hz -> Fs >= 2400 Hz -> INTERVAL <= 0.00042 s
    """
    # Import this dependency locally because it is only needed on this execution path.
    from reportlab.lib import colors as _colors

    # Capture margin_x here; the next step uses this intermediate result directly.
    margin_x = x0
    # Capture nyquist here; the next step uses this intermediate result directly.
    nyquist = fs_hz / 2.0

    # Band requirements: (label, min_fs_hz, min_interval_s)
    # Capture band_reqs here; the next step uses this intermediate result directly.
    band_reqs = [
        ("1-10 Hz",     20.0,   0.050),
        ("60-120 Hz",   240.0,  0.004),
        ("360-720 Hz", 1440.0, 0.0007),
        ("720-1200 Hz", 2400.0, 1.0 / 2400.0),
    ]

    # ── Load map identity row ────────────────────────────────────────────────
    # Capture magnet_id here; the next step uses this intermediate result directly.
    magnet_id  = meta.get("magnet_id",      "")
    # Capture sn here; the next step uses this intermediate result directly.
    sn         = meta.get("serial_number",  "")
    # Capture host here; the next step uses this intermediate result directly.
    host       = meta.get("ip",             "")
    # Capture cabinet here; the next step uses this intermediate result directly.
    cabinet    = meta.get("cabinet",        "")
    # Capture sector here; the next step uses this intermediate result directly.
    sector     = meta.get("sector",         "")
    # Capture load_desc here; the next step uses this intermediate result directly.
    load_desc  = meta.get("load_desc",      "")
    # Capture raw_v here; the next step uses this intermediate result directly.
    raw_v      = meta.get("raw_V",          "")
    # Capture v_out here; the next step uses this intermediate result directly.
    v_out      = meta.get("v_out_rating",   "")

    # Carry out this step before advancing to the next part of the function.
    c.setFont("Helvetica-Bold", 9)
    # Capture id_parts here; the next step uses this intermediate result directly.
    id_parts = []
    # Take this branch only when the stated operating condition is true.
    if magnet_id: id_parts.append(magnet_id)
    # Take this branch only when the stated operating condition is true.
    if sn:        id_parts.append(f"SN: {sn}")
    # Take this branch only when the stated operating condition is true.
    if id_parts:
        # Carry out this step before advancing to the next part of the function.
        c.drawString(margin_x, y, "  |  ".join(id_parts))
        # Carry out this step before advancing to the next part of the function.
        y -= 11

    # Carry out this step before advancing to the next part of the function.
    c.setFont("Helvetica", 9)
    # Capture loc_parts here; the next step uses this intermediate result directly.
    loc_parts = []
    # Take this branch only when the stated operating condition is true.
    if host:    loc_parts.append(f"Host: {host}")
    # Take this branch only when the stated operating condition is true.
    if cabinet: loc_parts.append(f"Cab: {cabinet}")
    # Take this branch only when the stated operating condition is true.
    if sector:  loc_parts.append(f"Sector: {sector}")
    # Take this branch only when the stated operating condition is true.
    if raw_v:   loc_parts.append(f"Vbus: {raw_v} V")
    # Take this branch only when the stated operating condition is true.
    if v_out:   loc_parts.append(f"Vout rated: {v_out} V")
    # Take this branch only when the stated operating condition is true.
    if loc_parts:
        # Carry out this step before advancing to the next part of the function.
        c.drawString(margin_x, y, "  |  ".join(loc_parts))
        # Carry out this step before advancing to the next part of the function.
        y -= 11

    # Do not judge full-load performance until the load is high enough to make that comparison meaningful.
    if load_desc:
        # Capture parts here; the next step uses this intermediate result directly.
        parts = [p.strip() for p in load_desc.split(";") if p.strip()]
        # Carry out this step before advancing to the next part of the function.
        c.drawString(margin_x + 6, y, "; ".join(parts[:4]))
        # Carry out this step before advancing to the next part of the function.
        y -= 11

    # Carry out this step before advancing to the next part of the function.
    y -= 3

    # ── Fs advisory ──────────────────────────────────────────────────────────
    # Carry out this step before advancing to the next part of the function.
    c.setFont("Helvetica-Bold", 9)
    # Carry out this step before advancing to the next part of the function.
    c.drawString(margin_x, y,
                 f"Sample Rate: Fs = {fs_hz:.2f} Hz   "
                 f"Nyquist limit = {nyquist:.2f} Hz")
    # Carry out this step before advancing to the next part of the function.
    y -= 11

    # Carry out this step before advancing to the next part of the function.
    c.setFont("Helvetica", 8)
    # Walk the collection in order so every item receives the same treatment.
    for band_label, min_fs, min_interval in band_reqs:
        # Capture ok here; the next step uses this intermediate result directly.
        ok = nyquist >= (min_fs / 2.0)
        # Capture status here; the next step uses this intermediate result directly.
        status = "OK" if ok else f"INSUFFICIENT — need Fs ≥ {min_fs:.0f} Hz (INTERVAL ≤ {min_interval:.4f} s)"
        # Capture marker here; the next step uses this intermediate result directly.
        marker = "✓" if ok else "✗"
        # Carry out this step before advancing to the next part of the function.
        c.setFillColor(_colors.green if ok else _colors.red)
        # Carry out this step before advancing to the next part of the function.
        c.drawString(margin_x + 6, y, f"{marker}  {band_label:12s}  {status}")
        # Carry out this step before advancing to the next part of the function.
        c.setFillColor(_colors.black)
        # Carry out this step before advancing to the next part of the function.
        y -= 10

    # Carry out this step before advancing to the next part of the function.
    y -= 4
    # Hand the finished value back to the caller.
    return y


def _draw_band_table(
    c: canvas.Canvas,
    x0: float,
    y: float,
    r: dict,
) -> float:
    """
    Draw a compact per-channel band RMS table.
    Returns updated y position after the table.
    """
    # Capture band_rms here; the next step uses this intermediate result directly.
    band_rms = r.get("band_rms", [])
    # Take this branch only when the stated operating condition is true.
    if not band_rms:
        # Hand the finished value back to the caller.
        return y

    # Capture unit here; the next step uses this intermediate result directly.
    unit = r.get("quantity_unit", "")
    # Capture col_w here; the next step uses this intermediate result directly.
    col_w = [1.6 * inch, 1.4 * inch, 1.4 * inch]
    # Capture headers here; the next step uses this intermediate result directly.
    headers = ["Band", f"RMS ({unit})", "ppm"]

    # Carry out this step before advancing to the next part of the function.
    c.setFont("Helvetica-Bold", 9)
    # Capture cx here; the next step uses this intermediate result directly.
    cx = x0 + 18
    # Walk the collection in order so every item receives the same treatment.
    for i, h in enumerate(headers):
        # Carry out this step before advancing to the next part of the function.
        c.drawString(cx + sum(col_w[:i]), y, h)
    # Carry out this step before advancing to the next part of the function.
    y -= 11

    # Carry out this step before advancing to the next part of the function.
    c.setFont("Helvetica", 9)
    # Walk the collection in order so every item receives the same treatment.
    for name, _lo, _hi, rms_val, rms_ppm in band_rms:
        # Carry out this step before advancing to the next part of the function.
        c.drawString(cx,                      y, name)
        # Carry out this step before advancing to the next part of the function.
        c.drawString(cx + col_w[0],           y, f"{rms_val:.4g}")
        # Carry out this step before advancing to the next part of the function.
        c.drawString(cx + col_w[0] + col_w[1], y,
                     f"{rms_ppm:.1f}" if rms_ppm is not None else "N/A")
        # Carry out this step before advancing to the next part of the function.
        y -= 11
    # Carry out this step before advancing to the next part of the function.
    y -= 4
    # Hand the finished value back to the caller.
    return y


def _draw_diagnostics_block(
    c: canvas.Canvas,
    x0: float,
    y: float,
    meta: Dict[str, str],
) -> float:
    """
    Draw the power-balance diagnostics summary block (model, eta_reference,
    mean IBUS %Error, efficiency-health verdict, fault-event count) sourced
    from cdcu_monitor.py's per-run CSV metadata / meta dict.

    Silently draws nothing (returns y unchanged) if none of the diagnostic
    fields are present in *meta* — e.g. an older CSV produced before this
    feature existed, or cdcu_diagnostics.py was unavailable at capture time.
    Returns the updated y position after the block (or the original y if
    nothing was drawn).
    """
    # Import this dependency locally because it is only needed on this execution path.
    from reportlab.lib import colors as _colors

    # Capture model here; the next step uses this intermediate result directly.
    model      = meta.get("model", "")
    # Capture eta_pct here; the next step uses this intermediate result directly.
    eta_pct    = meta.get("eta_reference_pct", "")
    # Capture err_mean here; the next step uses this intermediate result directly.
    err_mean   = meta.get("ibus_pct_error_mean", "")
    # Capture verdict here; the next step uses this intermediate result directly.
    verdict    = meta.get("efficiency_health_verdict", "")
    # Capture n_faults here; the next step uses this intermediate result directly.
    n_faults   = meta.get("fault_event_count", "")
    mag_r_np   = meta.get("magnet_resistance_nameplate_ohm", "")
    mag_r_meas = meta.get("magnet_resistance_measured_ohm", "")
    mag_l_np   = meta.get("magnet_inductance_nameplate_H", "")
    mag_l_meas = meta.get("magnet_inductance_estimated_H", "")

    # Act only when this fault condition is present at this point in the sequence.
    if not any([model, eta_pct, err_mean, verdict, n_faults, mag_r_np, mag_r_meas, mag_l_np, mag_l_meas]):
        # Hand the finished value back to the caller.
        return y

    # Carry out this step before advancing to the next part of the function.
    c.setFont("Helvetica-Bold", 11)
    # Carry out this step before advancing to the next part of the function.
    c.drawString(x0, y, "Power-Balance Diagnostics")
    # Carry out this step before advancing to the next part of the function.
    y -= 14

    # Carry out this step before advancing to the next part of the function.
    c.setFont("Helvetica", 10)
    # Capture line1_parts here; the next step uses this intermediate result directly.
    line1_parts = []
    # Take this branch only when the stated operating condition is true.
    if model:
        # Add this observation to the ordered history so the sequence is preserved.
        line1_parts.append(f"Model: {model}")
    # Take this branch only when the stated operating condition is true.
    if eta_pct:
        # Add this observation to the ordered history so the sequence is preserved.
        line1_parts.append(f"eta_reference: {eta_pct}%")
    # Take this branch only when the stated operating condition is true.
    if line1_parts:
        # Carry out this step before advancing to the next part of the function.
        c.drawString(x0, y, "  |  ".join(line1_parts))
        # Carry out this step before advancing to the next part of the function.
        y -= 13

    # Take this branch only when the stated operating condition is true.
    if err_mean:
        # Carry out this step before advancing to the next part of the function.
        c.drawString(x0, y, f"IBUS %Error (run mean): {err_mean}%  "
                             f"[(MGPC - I_IN,expected) / I_IN,expected x 100]")
        # Carry out this step before advancing to the next part of the function.
        y -= 13

    # Take this branch only when the stated operating condition is true.
    if verdict:
        # Carry out this step before advancing to the next part of the function.
        c.setFont("Helvetica-Bold", 10)
        # Carry out this step before advancing to the next part of the function.
        is_investigate = (verdict == "investigate")
        # Carry out this step before advancing to the next part of the function.
        c.setFillColor(_colors.red if is_investigate else _colors.black)
        # Carry out this step before advancing to the next part of the function.
        c.drawString(x0, y, f"Efficiency health: {verdict.upper()}")
        # Carry out this step before advancing to the next part of the function.
        c.setFillColor(_colors.black)
        # Carry out this step before advancing to the next part of the function.
        c.setFont("Helvetica", 10)
        # Carry out this step before advancing to the next part of the function.
        y -= 13

    # Act only when this fault condition is present at this point in the sequence.
    if n_faults:
        # Carry out this step before advancing to the next part of the function.
        c.drawString(x0, y, f"Fault events captured this run: {n_faults}")
        # Carry out this step before advancing to the next part of the function.
        y -= 13

    # Carry out this step before advancing to the next part of the function.
    y -= 4
    # Hand the finished value back to the caller.
    return y


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_pdf_summary(
    pdf_path: str,
    csv_filename: str,
    meta: Dict[str, str],
    results: Dict[str, dict],
    sig_threshold_ppm: float,
    logo_path: str,
    logo_text: str,
) -> None:
    # Capture c here; the next step uses this intermediate result directly.
    c = canvas.Canvas(pdf_path, pagesize=letter)
    # Carry out this step before advancing to the next part of the function.
    W, H = letter
    # Capture margin here; the next step uses this intermediate result directly.
    margin = 0.75 * inch
    # Capture x0 here; the next step uses this intermediate result directly.
    x0 = margin

    # ── Page 1: overview ────────────────────────────────────────────────────
    # Capture y here; the next step uses this intermediate result directly.
    y = _draw_header(c, csv_filename, meta, sig_threshold_ppm)

    # Carry out this step before advancing to the next part of the function.
    c.setFont("Helvetica-Bold", 11)
    # Carry out this step before advancing to the next part of the function.
    c.drawString(x0, y, "Significant Components (Top per channel)")
    # Carry out this step before advancing to the next part of the function.
    y -= 14

    # Walk the collection in order so every item receives the same treatment.
    for key in results:
        # Capture r here; the next step uses this intermediate result directly.
        r = results[key]
        # Capture comps here; the next step uses this intermediate result directly.
        comps = r.get("sig_components", []) or []
        # Carry out this step before advancing to the next part of the function.
        c.setFont("Helvetica-Bold", 10)
        # Carry out this step before advancing to the next part of the function.
        c.drawString(x0, y, r.get("label", key))
        # Carry out this step before advancing to the next part of the function.
        y -= 12
        # Carry out this step before advancing to the next part of the function.
        c.setFont("Helvetica", 10)
        # Take this branch only when the stated operating condition is true.
        if not comps:
            # Carry out this step before advancing to the next part of the function.
            c.drawString(x0 + 18, y, "None above threshold.")
            # Carry out this step before advancing to the next part of the function.
            y -= 12
        else:
            # Walk the collection in order so every item receives the same treatment.
            for ff, aa, appm in comps[:3]:
                # Take this branch only when the stated operating condition is true.
                if appm is not None:
                    # Capture line here; the next step uses this intermediate result directly.
                    line = (
                        f"f={ff:.2f} Hz, A_pk={aa:.6g} "
                        f"{r.get('quantity_unit','')}, {appm:.1f} ppm"
                    )
                else:
                    # Capture line here; the next step uses this intermediate result directly.
                    line = f"f={ff:.2f} Hz, A_pk={aa:.6g} {r.get('quantity_unit','')}"
                # Carry out this step before advancing to the next part of the function.
                c.drawString(x0 + 18, y, line)
                # Carry out this step before advancing to the next part of the function.
                y -= 12
        # Carry out this step before advancing to the next part of the function.
        y -= 6

    # Carry out this step before advancing to the next part of the function.
    c.setFont("Helvetica-Bold", 11)
    # Carry out this step before advancing to the next part of the function.
    c.drawString(x0, y, "Integrated Metrics (per channel)")
    # Carry out this step before advancing to the next part of the function.
    y -= 14

    # Walk the collection in order so every item receives the same treatment.
    for key in results:
        # Capture r here; the next step uses this intermediate result directly.
        r = results[key]
        # Capture unit here; the next step uses this intermediate result directly.
        unit = r.get("quantity_unit", "")
        # Carry out this step before advancing to the next part of the function.
        c.setFont("Helvetica-Bold", 10)
        # Carry out this step before advancing to the next part of the function.
        c.drawString(x0, y, r.get("label", key))
        # Carry out this step before advancing to the next part of the function.
        y -= 12
        # Carry out this step before advancing to the next part of the function.
        c.setFont("Helvetica", 10)
        # Carry out this step before advancing to the next part of the function.
        c.drawString(
            x0 + 18, y,
            f"Integrated PSD Power (∫PSD df): "
            f"{r.get('integrated_power', 0.0):.6e} {unit}^2"
        )
        # Carry out this step before advancing to the next part of the function.
        y -= 12
        # Carry out this step before advancing to the next part of the function.
        c.drawString(
            x0 + 18, y,
            f"Integrated RMS: {r.get('integrated_rms', 0.0):.6e} {unit}"
        )
        # Carry out this step before advancing to the next part of the function.
        y -= 12
        # Take this branch only when the stated operating condition is true.
        if r.get("integrated_rms_ppm") is not None:
            # Carry out this step before advancing to the next part of the function.
            c.drawString(
                x0 + 18, y,
                f"Integrated RMS: {r.get('integrated_rms_ppm'):.2f} ppm"
            )
            # Carry out this step before advancing to the next part of the function.
            y -= 12
        # Carry out this step before advancing to the next part of the function.
        y -= 6

    # Capture load_desc here; the next step uses this intermediate result directly.
    load_desc = meta.get("load_desc", "") or "Not provided."
    # Carry out this step before advancing to the next part of the function.
    c.setFont("Helvetica-Bold", 11)
    # Carry out this step before advancing to the next part of the function.
    c.drawString(x0, y, "Load Description")
    # Carry out this step before advancing to the next part of the function.
    y -= 14
    # Carry out this step before advancing to the next part of the function.
    c.setFont("Helvetica", 10)
    # Carry out this step before advancing to the next part of the function.
    c.drawString(x0, y, load_desc[:140])
    # Carry out this step before advancing to the next part of the function.
    y -= 14

    # Carry out this step before advancing to the next part of the function.
    _draw_footer(c, logo_path, logo_text)
    # Carry out this step before advancing to the next part of the function.
    c.showPage()

    # ── Per-channel detail pages ─────────────────────────────────────────────
    # Walk the collection in order so every item receives the same treatment.
    for key in results:
        # Capture r here; the next step uses this intermediate result directly.
        r = results[key]

        # Capture y here; the next step uses this intermediate result directly.
        y = H - margin
        # Carry out this step before advancing to the next part of the function.
        c.setFont("Helvetica-Bold", 13)
        # Carry out this step before advancing to the next part of the function.
        c.drawString(x0, y, r.get("label", key))
        # Carry out this step before advancing to the next part of the function.
        y -= 18

        # Carry out this step before advancing to the next part of the function.
        c.setFont("Helvetica", 10)
        # Carry out this step before advancing to the next part of the function.
        c.drawString(
            x0, y,
            f"fs: {r.get('fs_hz', 0.0):.2f} Hz   "
            f"Threshold: {sig_threshold_ppm:g} ppm"
        )
        # Carry out this step before advancing to the next part of the function.
        y -= 14

        # Capture unit here; the next step uses this intermediate result directly.
        unit = r.get("quantity_unit", "")
        # Carry out this step before advancing to the next part of the function.
        c.drawString(
            x0, y,
            f"Integrated PSD Power: {r.get('integrated_power', 0.0):.6e} {unit}^2"
        )
        # Carry out this step before advancing to the next part of the function.
        c.drawString(
            x0 + 3.6 * inch, y,
            f"Integrated RMS: {r.get('integrated_rms', 0.0):.6e} {unit}"
        )
        # Carry out this step before advancing to the next part of the function.
        y -= 14
        # Take this branch only when the stated operating condition is true.
        if r.get("integrated_rms_ppm") is not None:
            # Carry out this step before advancing to the next part of the function.
            c.drawString(
                x0, y,
                f"Integrated RMS: {r.get('integrated_rms_ppm'):.2f} ppm"
            )
            # Carry out this step before advancing to the next part of the function.
            y -= 14

        # ── Load map identity + Fs advisory ────────────────────────────────────
        # Capture y here; the next step uses this intermediate result directly.
        y = _draw_load_map_block(c, x0, y, meta, r.get("fs_hz", 0.0))

        # ── Band RMS table ────────────────────────────────────────────────────
        # Carry out this step before advancing to the next part of the function.
        c.setFont("Helvetica-Bold", 10)
        # Carry out this step before advancing to the next part of the function.
        c.drawString(x0, y, "Band RMS Summary")
        # Carry out this step before advancing to the next part of the function.
        y -= 12
        # Capture y here; the next step uses this intermediate result directly.
        y = _draw_band_table(c, x0, y, r)

        # Capture img_w here; the next step uses this intermediate result directly.
        img_w = W - 2 * margin
        # Capture img_h here; the next step uses this intermediate result directly.
        img_h = 2.10 * inch
        # Capture gap here; the next step uses this intermediate result directly.
        gap = 0.18 * inch

        # Walk the collection in order so every item receives the same treatment.
        for attr, label in [("fft_png", "FFT"), ("psd_png", "PSD"), ("cum_png", "Cumulative RMS")]:
            # Capture png here; the next step uses this intermediate result directly.
            png = r.get(attr, "")
            # Capture ok here; the next step uses this intermediate result directly.
            ok = _safe_draw_image(c, png, x0, y - img_h, img_w, img_h, strip_plot_branding=True)
            # Take this branch only when the stated operating condition is true.
            if not ok:
                # Carry out this step before advancing to the next part of the function.
                c.drawString(x0, y - 12, f"Missing {label} image: {os.path.basename(str(png))}")
            # Carry out this step before advancing to the next part of the function.
            y -= img_h + gap

        # Carry out this step before advancing to the next part of the function.
        _draw_footer(c, logo_path, logo_text)
        # Carry out this step before advancing to the next part of the function.
        c.showPage()

    # Carry out this step before advancing to the next part of the function.
    c.save()


def _sig_lines_for_results(results: Dict[str, dict]) -> List[str]:
    # Carry out this step before advancing to the next part of the function.
    lines: List[str] = []
    # Walk the collection in order so every item receives the same treatment.
    for key, r in results.items():
        # Capture comps here; the next step uses this intermediate result directly.
        comps = r.get("sig_components", []) or []
        # Take this branch only when the stated operating condition is true.
        if not comps:
            # Skip this item and continue with the next valid candidate.
            continue
        # Carry out this step before advancing to the next part of the function.
        ff, aa, appm = comps[0]
        # Capture unit here; the next step uses this intermediate result directly.
        unit = r.get("quantity_unit", "")
        # Capture label here; the next step uses this intermediate result directly.
        label = r.get("label", key)
        # Take this branch only when the stated operating condition is true.
        if appm is not None:
            # Add this observation to the ordered history so the sequence is preserved.
            lines.append(f"{label}: {ff:.2f} Hz @ {aa:.6g} {unit} pk ({appm:.1f} ppm)")
        else:
            # Add this observation to the ordered history so the sequence is preserved.
            lines.append(f"{label}: {ff:.2f} Hz @ {aa:.6g} {unit} pk")
    # Hand the finished value back to the caller.
    return lines


def build_technical_worksheet(
    docx_path: str,
    pdf_path: str,
    csv_filename: str,
    meta: Dict[str, str],
    results: Dict[str, dict],
    sig_threshold_ppm: float,
    logo_path: str,
    logo_text: str,
) -> None:
    # Carry out this step before advancing to the next part of the function.
    _build_worksheet_docx(docx_path, csv_filename, meta, results, sig_threshold_ppm)
    # Carry out this step before advancing to the next part of the function.
    _build_worksheet_pdf(pdf_path, csv_filename, meta, results, sig_threshold_ppm, logo_path, logo_text)


def _build_worksheet_docx(
    docx_path: str,
    csv_filename: str,
    meta: Dict[str, str],
    results: Dict[str, dict],
    sig_threshold_ppm: float,
) -> None:
    # Take this branch only when the stated operating condition is true.
    if Document is None:
        # Return to the caller; there is no additional value to pass back.
        return

    # Capture doc here; the next step uses this intermediate result directly.
    doc = Document()
    # Carry out this step before advancing to the next part of the function.
    doc.add_heading("APS / ANL – Power Systems Group", level=1)
    # Carry out this step before advancing to the next part of the function.
    doc.add_paragraph("CDCU Ripple Event – Technical Worksheet (Auto-populated)")

    # Carry out this step before advancing to the next part of the function.
    doc.add_heading("Event Information", level=2)
    # Carry out this step before advancing to the next part of the function.
    doc.add_paragraph(f"Data File: {csv_filename}")
    # Carry out this step before advancing to the next part of the function.
    doc.add_paragraph(f"PS ID: {meta.get('ps_id', '')}")
    # Carry out this step before advancing to the next part of the function.
    doc.add_paragraph(f"IP: {meta.get('ip', '')}")
    # Carry out this step before advancing to the next part of the function.
    doc.add_paragraph(
        f"Event Local: {meta.get('event_local', '') or meta.get('event_local_iso', '')}"
    )
    # Carry out this step before advancing to the next part of the function.
    doc.add_paragraph(
        f"Generated: {meta.get('generated_local', '') or meta.get('generated_local_iso', '')}"
    )

    # Carry out this step before advancing to the next part of the function.
    doc.add_heading("Fault Register (MFTR)", level=2)
    # Carry out this step before advancing to the next part of the function.
    doc.add_paragraph(f"MFTR: {meta.get('mftr', '')}")
    # Carry out this step before advancing to the next part of the function.
    doc.add_paragraph(f"Active Bits: {meta.get('mftr_active', '')}")

    # Capture _diag_model here; the next step uses this intermediate result directly.
    _diag_model   = meta.get("model", "")
    # Capture _diag_eta here; the next step uses this intermediate result directly.
    _diag_eta     = meta.get("eta_reference_pct", "")
    # Capture _diag_err here; the next step uses this intermediate result directly.
    _diag_err     = meta.get("ibus_pct_error_mean", "")
    # Capture _diag_verdict here; the next step uses this intermediate result directly.
    _diag_verdict = meta.get("efficiency_health_verdict", "")
    # Capture _diag_faults here; the next step uses this intermediate result directly.
    _diag_faults  = meta.get("fault_event_count", "")
    # Act only when this fault condition is present at this point in the sequence.
    if any([_diag_model, _diag_eta, _diag_err, _diag_verdict, _diag_faults]):
        # Carry out this step before advancing to the next part of the function.
        doc.add_heading("Power-Balance Diagnostics", level=2)
        # Take this branch only when the stated operating condition is true.
        if _diag_model or _diag_eta:
            # Carry out this step before advancing to the next part of the function.
            doc.add_paragraph(
                f"Model: {_diag_model or 'unknown'}   "
                f"eta_reference: {_diag_eta or 'n/a'}%"
            )
        # Take this branch only when the stated operating condition is true.
        if _diag_err:
            # Carry out this step before advancing to the next part of the function.
            doc.add_paragraph(
                f"IBUS %Error (run mean): {_diag_err}%  "
                f"[(MGPC - I_IN,expected) / I_IN,expected x 100]"
            )
        # Take this branch only when the stated operating condition is true.
        if _diag_verdict:
            # Carry out this step before advancing to the next part of the function.
            doc.add_paragraph(f"Efficiency health: {_diag_verdict.upper()}")
        # Act only when this fault condition is present at this point in the sequence.
        if _diag_faults:
            # Carry out this step before advancing to the next part of the function.
            doc.add_paragraph(f"Fault events captured this run: {_diag_faults}")

    _mag_r_np = meta.get("magnet_resistance_nameplate_ohm", "")
    _mag_r_meas = meta.get("magnet_resistance_measured_ohm", "")
    _mag_l_np = meta.get("magnet_inductance_nameplate_H", "")
    _mag_l_meas = meta.get("magnet_inductance_estimated_H", "")
    if any([_mag_r_np, _mag_r_meas, _mag_l_np, _mag_l_meas]):
        doc.add_heading("Magnet Load Comparison", level=2)
        if _mag_r_np or _mag_r_meas:
            _rnp = f"{float(_mag_r_np)*1e3:.3f} mOhm" if _mag_r_np else "n/a"
            _rmeas = f"{float(_mag_r_meas)*1e3:.3f} mOhm" if _mag_r_meas else "n/a"
            doc.add_paragraph(f"Resistance - measured: {_rmeas}; load-map nameplate: {_rnp}")
        if _mag_l_np or _mag_l_meas:
            _lnp = f"{float(_mag_l_np)*1e3:.3f} mH" if _mag_l_np else "n/a"
            _lmeas = f"{float(_mag_l_meas)*1e3:.3f} mH" if _mag_l_meas else "n/a"
            doc.add_paragraph(f"Inductance - live-ramp estimate: {_lmeas}; load-map nameplate: {_lnp}")

    # Carry out this step before advancing to the next part of the function.
    doc.add_heading("Load Description", level=2)
    # Carry out this step before advancing to the next part of the function.
    doc.add_paragraph(meta.get("load_desc", "Not provided."))

    # Carry out this step before advancing to the next part of the function.
    doc.add_heading("Key Results (Technical Quick View)", level=2)
    # Carry out this step before advancing to the next part of the function.
    doc.add_paragraph(f"Significance threshold: {sig_threshold_ppm:g} ppm")
    # Walk the collection in order so every item receives the same treatment.
    for line in _sig_lines_for_results(results) or ["No significant components above threshold."]:
        # Carry out this step before advancing to the next part of the function.
        doc.add_paragraph(f"- {line}")

    # Carry out this step before advancing to the next part of the function.
    doc.add_heading("Integrated Metrics", level=2)
    # Walk the collection in order so every item receives the same treatment.
    for key, r in results.items():
        # Capture unit here; the next step uses this intermediate result directly.
        unit = r.get("quantity_unit", "")
        # Carry out this step before advancing to the next part of the function.
        doc.add_paragraph(r.get("label", key))
        # Carry out this step before advancing to the next part of the function.
        doc.add_paragraph(
            f"  Integrated PSD Power: {r.get('integrated_power', 0.0):.6e} {unit}^2"
        )
        # Carry out this step before advancing to the next part of the function.
        doc.add_paragraph(f"  Integrated RMS: {r.get('integrated_rms', 0.0):.6e} {unit}")
        # Take this branch only when the stated operating condition is true.
        if r.get("integrated_rms_ppm") is not None:
            # Carry out this step before advancing to the next part of the function.
            doc.add_paragraph(f"  Integrated RMS: {r.get('integrated_rms_ppm'):.2f} ppm")

        # Band table
        # Capture band_rms here; the next step uses this intermediate result directly.
        band_rms = r.get("band_rms", [])
        # Take this branch only when the stated operating condition is true.
        if band_rms:
            # Carry out this step before advancing to the next part of the function.
            doc.add_paragraph("  Band RMS:")
            # Walk the collection in order so every item receives the same treatment.
            for name, _lo, _hi, rms_val, rms_ppm in band_rms:
                # Capture ppm_str here; the next step uses this intermediate result directly.
                ppm_str = f"{rms_ppm:.1f} ppm" if rms_ppm is not None else "N/A"
                # Carry out this step before advancing to the next part of the function.
                doc.add_paragraph(f"    {name}: {rms_val:.4g} {unit} ({ppm_str})")

    # Carry out this step before advancing to the next part of the function.
    doc.add_heading("Technician Actions (Fill-in)", level=2)
    # Carry out this step before advancing to the next part of the function.
    doc.add_paragraph("1) Verify interlocks and cabling.")
    # Carry out this step before advancing to the next part of the function.
    doc.add_paragraph("2) Confirm fault clears after MRESET (if appropriate).")
    # Carry out this step before advancing to the next part of the function.
    doc.add_paragraph("3) Record any observations / environmental conditions:")
    # Carry out this step before advancing to the next part of the function.
    doc.add_paragraph("   ________________________________________________")
    # Carry out this step before advancing to the next part of the function.
    doc.add_paragraph("4) Attach additional notes/photos as needed.")

    # Carry out this step before advancing to the next part of the function.
    doc.save(docx_path)


def _build_worksheet_pdf(
    pdf_path: str,
    csv_filename: str,
    meta: Dict[str, str],
    results: Dict[str, dict],
    sig_threshold_ppm: float,
    logo_path: str,
    logo_text: str,
) -> None:
    # Capture c here; the next step uses this intermediate result directly.
    c = canvas.Canvas(pdf_path, pagesize=letter)
    # Carry out this step before advancing to the next part of the function.
    W, H = letter
    # Capture margin here; the next step uses this intermediate result directly.
    margin = 0.75 * inch
    # Capture x0 here; the next step uses this intermediate result directly.
    x0 = margin
    # Capture y here; the next step uses this intermediate result directly.
    y = H - margin

    # Carry out this step before advancing to the next part of the function.
    c.setFont("Helvetica-Bold", 14)
    # Carry out this step before advancing to the next part of the function.
    c.drawString(x0, y, "CDCU Ripple Event – Technical Worksheet")
    # Carry out this step before advancing to the next part of the function.
    y -= 18

    # Carry out this step before advancing to the next part of the function.
    c.setFont("Helvetica", 10)
    # Carry out this step before advancing to the next part of the function.
    c.drawString(x0, y, f"Data File: {csv_filename}")
    # Carry out this step before advancing to the next part of the function.
    y -= 14
    # Carry out this step before advancing to the next part of the function.
    c.drawString(x0, y, f"PS ID: {meta.get('ps_id', '')}")
    # Carry out this step before advancing to the next part of the function.
    c.drawString(x0 + 3.6 * inch, y, f"IP: {meta.get('ip', '')}")
    # Carry out this step before advancing to the next part of the function.
    y -= 14
    # Carry out this step before advancing to the next part of the function.
    c.drawString(
        x0, y,
        f"Event Local: {meta.get('event_local', '') or meta.get('event_local_iso', '')}"
    )
    # Carry out this step before advancing to the next part of the function.
    y -= 14
    # Carry out this step before advancing to the next part of the function.
    c.drawString(
        x0, y,
        f"Generated: {meta.get('generated_local', '') or meta.get('generated_local_iso', '')}"
    )
    # Carry out this step before advancing to the next part of the function.
    y -= 18

    # Carry out this step before advancing to the next part of the function.
    c.setFont("Helvetica-Bold", 11)
    # Carry out this step before advancing to the next part of the function.
    c.drawString(x0, y, "Fault Register (MFTR)")
    # Carry out this step before advancing to the next part of the function.
    y -= 14
    # Carry out this step before advancing to the next part of the function.
    c.setFont("Helvetica", 10)
    # Carry out this step before advancing to the next part of the function.
    c.drawString(x0, y, f"MFTR: {meta.get('mftr', '')}")
    # Carry out this step before advancing to the next part of the function.
    y -= 12
    # Capture active here; the next step uses this intermediate result directly.
    active = meta.get("mftr_active", "None")
    # Capture wrap here; the next step uses this intermediate result directly.
    wrap = 95
    # Walk the collection in order so every item receives the same treatment.
    for i in range(0, len(active), wrap):
        # Carry out this step before advancing to the next part of the function.
        c.drawString(x0, y, ("Active: " if i == 0 else "        ") + active[i : i + wrap])
        # Carry out this step before advancing to the next part of the function.
        y -= 12
    # Carry out this step before advancing to the next part of the function.
    y -= 6

    # Carry out this step before advancing to the next part of the function.
    c.setFont("Helvetica-Bold", 11)
    # Carry out this step before advancing to the next part of the function.
    c.drawString(x0, y, "Key Results (Auto)")
    # Carry out this step before advancing to the next part of the function.
    y -= 14
    # Carry out this step before advancing to the next part of the function.
    c.setFont("Helvetica", 10)
    # Carry out this step before advancing to the next part of the function.
    c.drawString(x0, y, f"Significance threshold: {sig_threshold_ppm:g} ppm")
    # Carry out this step before advancing to the next part of the function.
    y -= 12
    # Capture sig_lines here; the next step uses this intermediate result directly.
    sig_lines = _sig_lines_for_results(results)
    # Take this branch only when the stated operating condition is true.
    if not sig_lines:
        # Capture sig_lines here; the next step uses this intermediate result directly.
        sig_lines = ["No significant components above threshold."]
    # Walk the collection in order so every item receives the same treatment.
    for ln in sig_lines[:6]:
        # Carry out this step before advancing to the next part of the function.
        c.drawString(x0 + 18, y, f"- {ln}"[:120])
        # Carry out this step before advancing to the next part of the function.
        y -= 12
    # Carry out this step before advancing to the next part of the function.
    y -= 6

    # Carry out this step before advancing to the next part of the function.
    c.setFont("Helvetica-Bold", 11)
    # Carry out this step before advancing to the next part of the function.
    c.drawString(x0, y, "Integrated Metrics + Band RMS (Auto)")
    # Carry out this step before advancing to the next part of the function.
    y -= 14
    # Walk the collection in order so every item receives the same treatment.
    for key, r in results.items():
        # Capture unit here; the next step uses this intermediate result directly.
        unit = r.get("quantity_unit", "")
        # Carry out this step before advancing to the next part of the function.
        c.setFont("Helvetica-Bold", 10)
        # Carry out this step before advancing to the next part of the function.
        c.drawString(x0, y, r.get("label", key))
        # Carry out this step before advancing to the next part of the function.
        y -= 12
        # Carry out this step before advancing to the next part of the function.
        c.setFont("Helvetica", 10)
        # Carry out this step before advancing to the next part of the function.
        c.drawString(
            x0 + 18, y,
            f"Power: {r.get('integrated_power', 0.0):.6e} {unit}^2"
        )
        # Carry out this step before advancing to the next part of the function.
        y -= 12
        # Carry out this step before advancing to the next part of the function.
        c.drawString(
            x0 + 18, y,
            f"RMS  : {r.get('integrated_rms', 0.0):.6e} {unit}"
        )
        # Carry out this step before advancing to the next part of the function.
        y -= 12
        # Take this branch only when the stated operating condition is true.
        if r.get("integrated_rms_ppm") is not None:
            # Carry out this step before advancing to the next part of the function.
            c.drawString(
                x0 + 18, y,
                f"RMS  : {r.get('integrated_rms_ppm'):.2f} ppm"
            )
            # Carry out this step before advancing to the next part of the function.
            y -= 12
        # Capture y here; the next step uses this intermediate result directly.
        y = _draw_band_table(c, x0, y, r)

    # Capture y here; the next step uses this intermediate result directly.
    y = _draw_diagnostics_block(c, x0, y, meta)

    # Carry out this step before advancing to the next part of the function.
    c.setFont("Helvetica-Bold", 11)
    # Carry out this step before advancing to the next part of the function.
    c.drawString(x0, y, "Technician Notes (Fill-in)")
    # Carry out this step before advancing to the next part of the function.
    y -= 14
    # Carry out this step before advancing to the next part of the function.
    c.setFont("Helvetica", 10)
    # Walk the collection in order so every item receives the same treatment.
    for _ in range(6):
        # Carry out this step before advancing to the next part of the function.
        c.drawString(x0, y, "_" * 110)
        # Carry out this step before advancing to the next part of the function.
        y -= 14

    # Carry out this step before advancing to the next part of the function.
    _draw_footer(c, logo_path, logo_text)
    # Carry out this step before advancing to the next part of the function.
    c.showPage()
    # Carry out this step before advancing to the next part of the function.
    c.save()


# ---------------------------------------------------------------------------
# Combined PMM + polling report
# ---------------------------------------------------------------------------

def build_combined_pdf(
    pdf_path: str,
    csv_filename: str,
    meta: Dict[str, str],
    pmm_results: Dict[str, dict],
    poll_results: Dict[str, dict],
    sig_threshold_ppm: float,
    logo_path: str,
    logo_text: str,
    pmm_timestamp: str = "",
) -> None:
    """
    Build a single combined PDF with:
        Page 1   : Cover — identity block + run summary table
        Pages 2–N: PMM spectral analysis (FFT/PSD/bands at 10 kHz) per channel
        Pages N+1: Polling-based trend overview (band advisory)
        Last page: Technician worksheet

    Parameters
    ----------
    pmm_results  : Results dict from analyze_series_for_reports() on PMM data.
                   Keys are channel names; each value has the standard result
                   dict (fft_png, psd_png, cum_png, band_rms, fs_hz, ...).
    poll_results : Results dict from analyze_series_for_reports() on polling data.
    pmm_timestamp: Acquisition timestamp string from PMM:TIMESTAMP command.
    """
    # Import this dependency locally because it is only needed on this execution path.
    from reportlab.platypus import SimpleDocTemplate
    # Import this dependency locally because it is only needed on this execution path.
    from reportlab.lib import colors as _colors

    # Capture c here; the next step uses this intermediate result directly.
    c = canvas.Canvas(pdf_path, pagesize=letter)
    # Carry out this step before advancing to the next part of the function.
    W, H = letter
    # Capture margin here; the next step uses this intermediate result directly.
    margin = 0.75 * inch
    # Capture x0 here; the next step uses this intermediate result directly.
    x0 = margin

    # ── Page 1: Cover ────────────────────────────────────────────────────────
    # Capture y here; the next step uses this intermediate result directly.
    y = H - margin

    # Masthead
    # Carry out this step before advancing to the next part of the function.
    c.setFont("Helvetica-Bold", 16)
    # Carry out this step before advancing to the next part of the function.
    c.drawString(x0, y, "CDCU Ripple Analysis — Combined Report")
    # Carry out this step before advancing to the next part of the function.
    y -= 22

    # Identity block (reuse _draw_header internals inline for cover layout)
    # Capture magnet_id here; the next step uses this intermediate result directly.
    magnet_id  = meta.get("magnet_id", "")
    # Capture sn here; the next step uses this intermediate result directly.
    sn         = meta.get("serial_number", "")
    # Capture host here; the next step uses this intermediate result directly.
    host       = meta.get("ip", "")
    # Capture cabinet here; the next step uses this intermediate result directly.
    cabinet    = meta.get("cabinet", "")
    # Capture sector here; the next step uses this intermediate result directly.
    sector     = meta.get("sector", "")
    # Capture load_desc here; the next step uses this intermediate result directly.
    load_desc  = meta.get("load_desc", "")
    # Capture raw_v here; the next step uses this intermediate result directly.
    raw_v      = meta.get("raw_V", "")
    # Capture v_out here; the next step uses this intermediate result directly.
    v_out      = meta.get("v_out_rating", "")

    # Carry out this step before advancing to the next part of the function.
    c.setFont("Helvetica-Bold", 12)
    # Capture id_str here; the next step uses this intermediate result directly.
    id_str = magnet_id
    # Take this branch only when the stated operating condition is true.
    if sn:
        # Capture id_str here; the next step uses this intermediate result directly.
        id_str = f"{id_str}   SN: {sn}" if id_str else f"SN: {sn}"
    # Take this branch only when the stated operating condition is true.
    if id_str:
        # Carry out this step before advancing to the next part of the function.
        c.drawString(x0, y, id_str)
        # Carry out this step before advancing to the next part of the function.
        y -= 16

    # Carry out this step before advancing to the next part of the function.
    c.setFont("Helvetica", 10)
    # Capture loc_parts here; the next step uses this intermediate result directly.
    loc_parts = []
    # Take this branch only when the stated operating condition is true.
    if host:    loc_parts.append(f"Host: {host}")
    # Take this branch only when the stated operating condition is true.
    if cabinet: loc_parts.append(f"Cabinet: {cabinet}")
    # Take this branch only when the stated operating condition is true.
    if sector:  loc_parts.append(f"Sector: {sector}")
    # Take this branch only when the stated operating condition is true.
    if loc_parts:
        # Carry out this step before advancing to the next part of the function.
        c.drawString(x0, y, "  |  ".join(loc_parts))
        # Carry out this step before advancing to the next part of the function.
        y -= 13

    # Capture v_parts here; the next step uses this intermediate result directly.
    v_parts = []
    # Take this branch only when the stated operating condition is true.
    if raw_v:  v_parts.append(f"DC Bus: {raw_v} V")
    # Take this branch only when the stated operating condition is true.
    if v_out:  v_parts.append(f"Vout rated: {v_out} V")
    # Take this branch only when the stated operating condition is true.
    if v_parts:
        # Carry out this step before advancing to the next part of the function.
        c.drawString(x0, y, "  |  ".join(v_parts))
        # Carry out this step before advancing to the next part of the function.
        y -= 13

    # Do not judge full-load performance until the load is high enough to make that comparison meaningful.
    if load_desc:
        # Capture parts here; the next step uses this intermediate result directly.
        parts = [p.strip() for p in load_desc.split(";") if p.strip()]
        # Carry out this step before advancing to the next part of the function.
        c.drawString(x0, y, "; ".join(parts[:4]))
        # Carry out this step before advancing to the next part of the function.
        y -= 13

    # Divider
    # Carry out this step before advancing to the next part of the function.
    c.setLineWidth(0.75)
    # Carry out this step before advancing to the next part of the function.
    c.line(x0, y + 4, W - margin, y + 4)
    # Carry out this step before advancing to the next part of the function.
    y -= 10

    # Run summary table
    # Carry out this step before advancing to the next part of the function.
    c.setFont("Helvetica-Bold", 11)
    # Carry out this step before advancing to the next part of the function.
    c.drawString(x0, y, "Run Summary")
    # Carry out this step before advancing to the next part of the function.
    y -= 14

    # Carry out this step before advancing to the next part of the function.
    c.setFont("Helvetica", 10)
    # Capture generated here; the next step uses this intermediate result directly.
    generated = meta.get("generated_local", "")
    # Carry out this step before advancing to the next part of the function.
    c.drawString(x0,              y, f"Report generated : {generated}")
    # Carry out this step before advancing to the next part of the function.
    y -= 13
    # Carry out this step before advancing to the next part of the function.
    c.drawString(x0,              y, f"Polling data file: {csv_filename}")
    # Carry out this step before advancing to the next part of the function.
    y -= 13

    # Take this branch only when the stated operating condition is true.
    if pmm_timestamp:
        # Carry out this step before advancing to the next part of the function.
        c.drawString(x0, y, f"PMM acquired     : {pmm_timestamp}")
        # Carry out this step before advancing to the next part of the function.
        y -= 13

    # PMM specs
    # Carry out this step before advancing to the next part of the function.
    c.setFont("Helvetica-Bold", 10)
    # Carry out this step before advancing to the next part of the function.
    c.drawString(x0, y, "PMM Acquisition Parameters")
    # Carry out this step before advancing to the next part of the function.
    y -= 12
    # Carry out this step before advancing to the next part of the function.
    c.setFont("Helvetica", 10)
    # Carry out this step before advancing to the next part of the function.
    c.drawString(x0 + 12, y, "Sample rate   : 10 000 Hz (100 µs fixed, hardware)")
    # Carry out this step before advancing to the next part of the function.
    y -= 12
    # Carry out this step before advancing to the next part of the function.
    c.drawString(x0 + 12, y, "Record length : 100 001 samples  (10 s window)")
    # Carry out this step before advancing to the next part of the function.
    y -= 12
    # Carry out this step before advancing to the next part of the function.
    c.drawString(x0 + 12, y, "Nyquist limit : 5 000 Hz")
    # Carry out this step before advancing to the next part of the function.
    y -= 12
    # Carry out this step before advancing to the next part of the function.
    c.drawString(x0 + 12, y, "Channels      : Vout (ch 0)  |  Iout (ch 1)  |  Iset (ch 2)")
    # Carry out this step before advancing to the next part of the function.
    y -= 16

    # Band coverage table
    # Carry out this step before advancing to the next part of the function.
    c.setFont("Helvetica-Bold", 10)
    # Carry out this step before advancing to the next part of the function.
    c.drawString(x0, y, "Spectral Band Coverage")
    # Carry out this step before advancing to the next part of the function.
    y -= 12
    # Carry out this step before advancing to the next part of the function.
    c.setFont("Helvetica", 9)
    # Capture bands_info here; the next step uses this intermediate result directly.
    bands_info = [
        ("1–10 Hz",    "20 Hz",    "0.050 s", "10 000 Hz ✓"),
        ("60–120 Hz",  "240 Hz",   "0.004 s", "10 000 Hz ✓"),
        ("360–720 Hz", "1 440 Hz", "0.0007 s","10 000 Hz ✓"),
    ]
    # Capture col_w here; the next step uses this intermediate result directly.
    col_w = [1.4*inch, 1.1*inch, 1.0*inch, 1.5*inch, 1.3*inch]
    # Capture hdrs here; the next step uses this intermediate result directly.
    hdrs = ["Band", "Min Fs", "Max Interval", "PMM Fs", "Status"]
    # Capture cx here; the next step uses this intermediate result directly.
    cx = x0 + 12
    # Carry out this step before advancing to the next part of the function.
    c.setFont("Helvetica-Bold", 9)
    # Walk the collection in order so every item receives the same treatment.
    for i, h in enumerate(hdrs):
        # Carry out this step before advancing to the next part of the function.
        c.drawString(cx + sum(col_w[:i]), y, h)
    # Carry out this step before advancing to the next part of the function.
    y -= 11
    # Carry out this step before advancing to the next part of the function.
    c.setFont("Helvetica", 9)
    # Walk the collection in order so every item receives the same treatment.
    for band_label, min_fs, max_ivl, pmm_fs in bands_info:
        # Capture row here; the next step uses this intermediate result directly.
        row = [band_label, min_fs, max_ivl, pmm_fs, "COVERED by PMM"]
        # Walk the collection in order so every item receives the same treatment.
        for i, cell in enumerate(row):
            # Carry out this step before advancing to the next part of the function.
            c.drawString(cx + sum(col_w[:i]), y, cell)
        # Carry out this step before advancing to the next part of the function.
        y -= 11
    # Carry out this step before advancing to the next part of the function.
    y -= 6

    # Polling summary note
    # Capture poll_fs here; the next step uses this intermediate result directly.
    poll_fs = 0.0
    # Take this branch only when the stated operating condition is true.
    if poll_results:
        # Capture poll_fs here; the next step uses this intermediate result directly.
        poll_fs = list(poll_results.values())[0].get("fs_hz", 0.0)
    # Carry out this step before advancing to the next part of the function.
    c.setFont("Helvetica-Bold", 10)
    # Carry out this step before advancing to the next part of the function.
    c.drawString(x0, y, "Polling Monitor Parameters")
    # Carry out this step before advancing to the next part of the function.
    y -= 12
    # Carry out this step before advancing to the next part of the function.
    c.setFont("Helvetica", 9)
    # Carry out this step before advancing to the next part of the function.
    c.drawString(x0 + 12, y,
                 f"Fs ≈ {poll_fs:.2f} Hz  |  Nyquist ≈ {poll_fs/2:.2f} Hz  "
                 f"|  Best for slow-trend, DC operating point, efficiency")
    # Carry out this step before advancing to the next part of the function.
    y -= 16

    # Channel results overview
    # Take this branch only when the stated operating condition is true.
    if pmm_results:
        # Carry out this step before advancing to the next part of the function.
        c.setFont("Helvetica-Bold", 10)
        # Carry out this step before advancing to the next part of the function.
        c.drawString(x0, y, "PMM Channel Overview")
        # Carry out this step before advancing to the next part of the function.
        y -= 12
        # Carry out this step before advancing to the next part of the function.
        c.setFont("Helvetica", 9)
        # Walk the collection in order so every item receives the same treatment.
        for key, r in pmm_results.items():
            # Capture i_rms here; the next step uses this intermediate result directly.
            i_rms = r.get("integrated_rms", 0.0)
            # Capture i_ppm here; the next step uses this intermediate result directly.
            i_ppm = r.get("integrated_rms_ppm")
            # Capture unit here; the next step uses this intermediate result directly.
            unit  = r.get("quantity_unit", "")
            # Capture ppm_s here; the next step uses this intermediate result directly.
            ppm_s = f"  ({i_ppm:.1f} ppm)" if i_ppm is not None else ""
            # Carry out this step before advancing to the next part of the function.
            c.drawString(x0 + 12, y,
                         f"{r.get('label', key):40s}  "
                         f"RMS = {i_rms:.4g} {unit}{ppm_s}")
            # Carry out this step before advancing to the next part of the function.
            y -= 11
        # Carry out this step before advancing to the next part of the function.
        y -= 4

    # Carry out this step before advancing to the next part of the function.
    _draw_footer(c, logo_path, logo_text)
    # Carry out this step before advancing to the next part of the function.
    c.showPage()

    # ── PMM channel detail pages ─────────────────────────────────────────────
    # Take this branch only when the stated operating condition is true.
    if pmm_results:
        # Carry out this step before advancing to the next part of the function.
        c.setFont("Helvetica-Bold", 13)
        # Section header page
        # Capture y here; the next step uses this intermediate result directly.
        y = H - margin
        # Carry out this step before advancing to the next part of the function.
        c.setFont("Helvetica-Bold", 14)
        # Carry out this step before advancing to the next part of the function.
        c.drawString(x0, y, "Section 1 — PMM Spectral Analysis  (Fs = 10 kHz)")
        # Carry out this step before advancing to the next part of the function.
        y -= 16
        # Carry out this step before advancing to the next part of the function.
        c.setFont("Helvetica", 10)
        # Carry out this step before advancing to the next part of the function.
        c.drawString(x0, y,
                     "All three spectral bands are fully resolved by the PMM "
                     "10 kHz hardware sample rate.")
        # Carry out this step before advancing to the next part of the function.
        y -= 12
        # Take this branch only when the stated operating condition is true.
        if pmm_timestamp:
            # Carry out this step before advancing to the next part of the function.
            c.drawString(x0, y, f"PMM acquisition timestamp: {pmm_timestamp}")
        # Carry out this step before advancing to the next part of the function.
        _draw_footer(c, logo_path, logo_text)
        # Carry out this step before advancing to the next part of the function.
        c.showPage()

        # Walk the collection in order so every item receives the same treatment.
        for key, r in pmm_results.items():
            # Capture y here; the next step uses this intermediate result directly.
            y = H - margin
            # Carry out this step before advancing to the next part of the function.
            c.setFont("Helvetica-Bold", 13)
            # Carry out this step before advancing to the next part of the function.
            c.drawString(x0, y, r.get("label", key))
            # Carry out this step before advancing to the next part of the function.
            y -= 18

            # Carry out this step before advancing to the next part of the function.
            c.setFont("Helvetica", 10)
            # Carry out this step before advancing to the next part of the function.
            c.drawString(
                x0, y,
                f"Fs: {r.get('fs_hz', 0.0):.2f} Hz   "
                f"Nyquist: {r.get('fs_hz', 0.0)/2:.2f} Hz   "
                f"Threshold: {sig_threshold_ppm:g} ppm"
            )
            # Carry out this step before advancing to the next part of the function.
            y -= 14

            # Capture unit here; the next step uses this intermediate result directly.
            unit = r.get("quantity_unit", "")
            # Carry out this step before advancing to the next part of the function.
            c.drawString(
                x0, y,
                f"Integrated PSD Power: {r.get('integrated_power', 0.0):.6e} {unit}^2"
            )
            # Carry out this step before advancing to the next part of the function.
            c.drawString(
                x0 + 3.6 * inch, y,
                f"Integrated RMS: {r.get('integrated_rms', 0.0):.6e} {unit}"
            )
            # Carry out this step before advancing to the next part of the function.
            y -= 14
            # Take this branch only when the stated operating condition is true.
            if r.get("integrated_rms_ppm") is not None:
                # Carry out this step before advancing to the next part of the function.
                c.drawString(
                    x0, y,
                    f"Integrated RMS: {r.get('integrated_rms_ppm'):.2f} ppm"
                )
                # Carry out this step before advancing to the next part of the function.
                y -= 14

            # Load map block + band table
            # Capture y here; the next step uses this intermediate result directly.
            y = _draw_load_map_block(c, x0, y, meta, r.get("fs_hz", 0.0))
            # Carry out this step before advancing to the next part of the function.
            c.setFont("Helvetica-Bold", 10)
            # Carry out this step before advancing to the next part of the function.
            c.drawString(x0, y, "Band RMS Summary")
            # Carry out this step before advancing to the next part of the function.
            y -= 12
            # Capture y here; the next step uses this intermediate result directly.
            y = _draw_band_table(c, x0, y, r)

            # Plots
            # Capture img_w here; the next step uses this intermediate result directly.
            img_w = W - 2 * margin
            # Capture img_h here; the next step uses this intermediate result directly.
            img_h = 2.05 * inch
            # Capture gap here; the next step uses this intermediate result directly.
            gap   = 0.15 * inch
            # Walk the collection in order so every item receives the same treatment.
            for attr, lbl in [("fft_png", "FFT"), ("psd_png", "PSD"),
                               ("cum_png", "Cumulative RMS")]:
                # Capture png here; the next step uses this intermediate result directly.
                png = r.get(attr, "")
                # Capture ok here; the next step uses this intermediate result directly.
                ok  = _safe_draw_image(c, png, x0, y - img_h, img_w, img_h, strip_plot_branding=True)
                # Take this branch only when the stated operating condition is true.
                if not ok:
                    # Carry out this step before advancing to the next part of the function.
                    c.drawString(x0, y - 12,
                                 f"Missing {lbl}: {os.path.basename(str(png))}")
                # Carry out this step before advancing to the next part of the function.
                y -= img_h + gap

            # Carry out this step before advancing to the next part of the function.
            _draw_footer(c, logo_path, logo_text)
            # Carry out this step before advancing to the next part of the function.
            c.showPage()

    # ── Polling-based trend pages ─────────────────────────────────────────────
    # Take this branch only when the stated operating condition is true.
    if poll_results:
        # Capture y here; the next step uses this intermediate result directly.
        y = H - margin
        # Carry out this step before advancing to the next part of the function.
        c.setFont("Helvetica-Bold", 14)
        # Carry out this step before advancing to the next part of the function.
        c.drawString(x0, y,
                     f"Section 2 — Polling Monitor Trend  "
                     f"(Fs ≈ {poll_fs:.2f} Hz)")
        # Carry out this step before advancing to the next part of the function.
        y -= 16
        # Carry out this step before advancing to the next part of the function.
        c.setFont("Helvetica", 10)
        # Carry out this step before advancing to the next part of the function.
        c.drawString(x0, y,
                     "Slow-trend DC operating point, efficiency, and "
                     "1–10 Hz band (if INTERVAL ≤ 0.05 s).")
        # Carry out this step before advancing to the next part of the function.
        _draw_footer(c, logo_path, logo_text)
        # Carry out this step before advancing to the next part of the function.
        c.showPage()

        # Overview table (sig components + integrated metrics)
        # Capture y here; the next step uses this intermediate result directly.
        y = _draw_header(c, csv_filename, meta, sig_threshold_ppm)

        # Carry out this step before advancing to the next part of the function.
        c.setFont("Helvetica-Bold", 11)
        # Carry out this step before advancing to the next part of the function.
        c.drawString(x0, y, "Significant Components (Polling channels)")
        # Carry out this step before advancing to the next part of the function.
        y -= 14

        # Walk the collection in order so every item receives the same treatment.
        for key, r in poll_results.items():
            # Capture comps here; the next step uses this intermediate result directly.
            comps = r.get("sig_components", []) or []
            # Carry out this step before advancing to the next part of the function.
            c.setFont("Helvetica-Bold", 10)
            # Carry out this step before advancing to the next part of the function.
            c.drawString(x0, y, r.get("label", key))
            # Carry out this step before advancing to the next part of the function.
            y -= 12
            # Carry out this step before advancing to the next part of the function.
            c.setFont("Helvetica", 10)
            # Take this branch only when the stated operating condition is true.
            if not comps:
                # Carry out this step before advancing to the next part of the function.
                c.drawString(x0 + 18, y, "None above threshold.")
                # Carry out this step before advancing to the next part of the function.
                y -= 12
            else:
                # Walk the collection in order so every item receives the same treatment.
                for ff, aa, appm in comps[:3]:
                    # Capture ppm_s here; the next step uses this intermediate result directly.
                    ppm_s = f", {appm:.1f} ppm" if appm is not None else ""
                    # Carry out this step before advancing to the next part of the function.
                    c.drawString(x0 + 18, y,
                                 f"f={ff:.2f} Hz, A_pk={aa:.6g} "
                                 f"{r.get('quantity_unit','')}{ppm_s}")
                    # Carry out this step before advancing to the next part of the function.
                    y -= 12
            # Carry out this step before advancing to the next part of the function.
            y -= 6

        # Carry out this step before advancing to the next part of the function.
        _draw_footer(c, logo_path, logo_text)
        # Carry out this step before advancing to the next part of the function.
        c.showPage()

        # Per-channel polling detail pages
        # Walk the collection in order so every item receives the same treatment.
        for key, r in poll_results.items():
            # Capture y here; the next step uses this intermediate result directly.
            y = H - margin
            # Carry out this step before advancing to the next part of the function.
            c.setFont("Helvetica-Bold", 13)
            # Carry out this step before advancing to the next part of the function.
            c.drawString(x0, y, r.get("label", key) + "  (Polling)")
            # Carry out this step before advancing to the next part of the function.
            y -= 18

            # Carry out this step before advancing to the next part of the function.
            c.setFont("Helvetica", 10)
            # Carry out this step before advancing to the next part of the function.
            c.drawString(
                x0, y,
                f"Fs: {r.get('fs_hz', 0.0):.2f} Hz   "
                f"Threshold: {sig_threshold_ppm:g} ppm"
            )
            # Carry out this step before advancing to the next part of the function.
            y -= 14

            # Capture unit here; the next step uses this intermediate result directly.
            unit = r.get("quantity_unit", "")
            # Carry out this step before advancing to the next part of the function.
            c.drawString(
                x0, y,
                f"Integrated PSD Power: {r.get('integrated_power', 0.0):.6e} {unit}^2"
            )
            # Carry out this step before advancing to the next part of the function.
            c.drawString(
                x0 + 3.6 * inch, y,
                f"Integrated RMS: {r.get('integrated_rms', 0.0):.6e} {unit}"
            )
            # Carry out this step before advancing to the next part of the function.
            y -= 14
            # Take this branch only when the stated operating condition is true.
            if r.get("integrated_rms_ppm") is not None:
                # Carry out this step before advancing to the next part of the function.
                c.drawString(x0, y,
                             f"Integrated RMS: {r.get('integrated_rms_ppm'):.2f} ppm")
                # Carry out this step before advancing to the next part of the function.
                y -= 14

            # Capture y here; the next step uses this intermediate result directly.
            y = _draw_load_map_block(c, x0, y, meta, r.get("fs_hz", 0.0))
            # Carry out this step before advancing to the next part of the function.
            c.setFont("Helvetica-Bold", 10)
            # Carry out this step before advancing to the next part of the function.
            c.drawString(x0, y, "Band RMS Summary")
            # Carry out this step before advancing to the next part of the function.
            y -= 12
            # Capture y here; the next step uses this intermediate result directly.
            y = _draw_band_table(c, x0, y, r)

            # Capture img_w here; the next step uses this intermediate result directly.
            img_w = W - 2 * margin
            # Capture img_h here; the next step uses this intermediate result directly.
            img_h = 2.05 * inch
            # Capture gap here; the next step uses this intermediate result directly.
            gap   = 0.15 * inch
            # Walk the collection in order so every item receives the same treatment.
            for attr, lbl in [("fft_png", "FFT"), ("psd_png", "PSD"),
                               ("cum_png", "Cumulative RMS")]:
                # Capture png here; the next step uses this intermediate result directly.
                png = r.get(attr, "")
                # Capture ok here; the next step uses this intermediate result directly.
                ok  = _safe_draw_image(c, png, x0, y - img_h, img_w, img_h, strip_plot_branding=True)
                # Take this branch only when the stated operating condition is true.
                if not ok:
                    # Carry out this step before advancing to the next part of the function.
                    c.drawString(x0, y - 12,
                                 f"Missing {lbl}: {os.path.basename(str(png))}")
                # Carry out this step before advancing to the next part of the function.
                y -= img_h + gap

            # Carry out this step before advancing to the next part of the function.
            _draw_footer(c, logo_path, logo_text)
            # Carry out this step before advancing to the next part of the function.
            c.showPage()

    # ── Technician worksheet (last page) ─────────────────────────────────────
    # Capture y here; the next step uses this intermediate result directly.
    y = H - margin
    # Carry out this step before advancing to the next part of the function.
    c.setFont("Helvetica-Bold", 14)
    # Carry out this step before advancing to the next part of the function.
    c.drawString(x0, y, "Technician Worksheet")
    # Carry out this step before advancing to the next part of the function.
    y -= 18

    # Carry out this step before advancing to the next part of the function.
    c.setFont("Helvetica", 10)
    # Carry out this step before advancing to the next part of the function.
    c.drawString(x0, y, f"PS ID: {meta.get('ps_id', '')}")
    # Carry out this step before advancing to the next part of the function.
    c.drawString(x0 + 3.6 * inch, y, f"IP: {meta.get('ip', '')}")
    # Carry out this step before advancing to the next part of the function.
    y -= 14
    # Carry out this step before advancing to the next part of the function.
    c.drawString(x0, y, f"SN: {meta.get('serial_number', '')}")
    # Carry out this step before advancing to the next part of the function.
    c.drawString(x0 + 3.6 * inch, y,
                 f"Generated: {meta.get('generated_local', '')}")
    # Carry out this step before advancing to the next part of the function.
    y -= 14
    # Do not judge full-load performance until the load is high enough to make that comparison meaningful.
    if load_desc:
        # Carry out this step before advancing to the next part of the function.
        c.drawString(x0, y, load_desc[:120])
        # Carry out this step before advancing to the next part of the function.
        y -= 14
    # Carry out this step before advancing to the next part of the function.
    y -= 6

    # Carry out this step before advancing to the next part of the function.
    c.setFont("Helvetica-Bold", 11)
    # Carry out this step before advancing to the next part of the function.
    c.drawString(x0, y, "MFTR Fault Register")
    # Carry out this step before advancing to the next part of the function.
    y -= 14
    # Carry out this step before advancing to the next part of the function.
    c.setFont("Helvetica", 10)
    # Carry out this step before advancing to the next part of the function.
    c.drawString(x0, y, f"MFTR: {meta.get('mftr', '')}")
    # Carry out this step before advancing to the next part of the function.
    y -= 12
    # Capture active here; the next step uses this intermediate result directly.
    active = meta.get("mftr_active", "None")
    # Carry out this step before advancing to the next part of the function.
    c.drawString(x0, y, f"Active: {active[:100]}")
    # Carry out this step before advancing to the next part of the function.
    y -= 16

    # Capture y here; the next step uses this intermediate result directly.
    y = _draw_diagnostics_block(c, x0, y, meta)

    # Carry out this step before advancing to the next part of the function.
    c.setFont("Helvetica-Bold", 11)
    # Carry out this step before advancing to the next part of the function.
    c.drawString(x0, y, "Technician Notes (Fill-in)")
    # Carry out this step before advancing to the next part of the function.
    y -= 14
    # Carry out this step before advancing to the next part of the function.
    c.setFont("Helvetica", 10)
    # Walk the collection in order so every item receives the same treatment.
    for _ in range(8):
        # Carry out this step before advancing to the next part of the function.
        c.drawString(x0, y, "_" * 110)
        # Carry out this step before advancing to the next part of the function.
        y -= 14

    # Carry out this step before advancing to the next part of the function.
    _draw_footer(c, logo_path, logo_text)
    # Carry out this step before advancing to the next part of the function.
    c.showPage()
    # Carry out this step before advancing to the next part of the function.
    c.save()
