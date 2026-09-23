#!/usr/bin/env python3
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from cdcu_scope_fft import (
    DEFAULT_EXPECTED_SAMPLES,
    DEFAULT_FS_HZ,
    ScopeChannel,
    analyze_scope_dataframe,
    prepare_scope_dataframe,
    stability_metrics,
)


def main():
    fs = DEFAULT_FS_HZ
    n = DEFAULT_EXPECTED_SAMPLES
    t = np.arange(n, dtype=float) / fs
    df = pd.DataFrame({
        "Time": t,
        "CH1": 40.0 + 0.020*np.sin(2*np.pi*60*t),
        "CH2": 100.0 + 0.100*np.sin(2*np.pi*1000*t),
        "CH3": 5.0 + 0.010*np.sin(2*np.pi*360*t),
        "CH4": 2.0 + 0.005*np.sin(2*np.pi*720*t),
    })
    channels = [
        ScopeChannel("CH1", "DCBus Input Voltage", "V", 40.0),
        ScopeChannel("CH2", "DCBus Input Current", "A", 100.0),
        ScopeChannel("CH3", "Aux Channel 3", "V", 5.0),
        ScopeChannel("CH4", "Aux Channel 4", "V", 2.0),
    ]
    prepared, selected, measured_fs = prepare_scope_dataframe(
        df, channels=channels, expected_samples=n
    )
    assert len(prepared) == n
    assert len(selected) == 4
    assert abs(measured_fs - fs) < 1e-6

    m = stability_metrics(df["CH1"].to_numpy(), t, 40.0)
    assert 900 < m["peak_to_peak_ppm"] < 1100  # 40 mV p-p / 40 V = 1000 ppm

    with tempfile.TemporaryDirectory() as td:
        results = analyze_scope_dataframe(
            df,
            outdir=td,
            channels=channels,
            expected_samples=n,
            fft_y_mode="magnitude",
        )
        assert results["_run"]["n_samples"] == n
        assert Path(results["_run"]["stability_txt"]).is_file()
        assert Path(results["_run"]["stability_csv"]).is_file()
        assert len([k for k in results if not k.startswith("_")]) == 4

    print("scope FFT/PSD + stability tests: PASS")


if __name__ == "__main__":
    main()
