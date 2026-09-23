#!/usr/bin/env python3
"""Regression checks for strict 10 kHz DCBus spectral capture validation."""
import numpy as np
import pandas as pd

from cdcu_dcbus_fft import (
    DCBUS_FS_HZ,
    DCBUS_N_SAMPLES,
    validate_dcbus_capture,
)


def main():
    n = DCBUS_N_SAMPLES
    t = np.arange(n, dtype=float) / DCBUS_FS_HZ
    df = pd.DataFrame({
        "time_s": t,
        "MRP": 36.0 + 0.01*np.sin(2*np.pi*60*t),
        "MGPC": 180.0 + 0.20*np.sin(2*np.pi*1000*t),
    })
    out = validate_dcbus_capture(df)
    assert len(out) == DCBUS_N_SAMPLES
    assert list(out.columns) == ["time_s", "dcbus_v_V", "dcbus_i_A"]

    short = df.iloc[:-1].copy()
    try:
        validate_dcbus_capture(short)
    except ValueError as exc:
        assert "exactly 100,001" in str(exc)
    else:
        raise AssertionError("Short DCBus record should have been rejected")

    print("dcbus FFT capture validation: PASS")


if __name__ == "__main__":
    main()
