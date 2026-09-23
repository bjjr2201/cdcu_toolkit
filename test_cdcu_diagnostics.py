# ---------------------------------------------------------------------------
# Authored By: Byron Jordan
# Power Supply Engineer
# Advanced Photon Source (APS)
# Argonne National Laboratory
# ---------------------------------------------------------------------------
import math
import numpy as np
import pandas as pd

import cdcu_diagnostics as d
import cdcu_ripple_psd as psd


def test_caen_full_load_compliance():
    assert d.caen_efficiency_compliance('CDCU-100', 92.1, 1.00) == 'pass'
    assert d.caen_efficiency_compliance('CDCU-100', 92.0, 1.00) == 'fail'
    assert d.caen_efficiency_compliance('CDCU-200', 94.1, 1.00) == 'pass'
    assert d.caen_efficiency_compliance('CDCU-200', 94.0, 1.00) == 'fail'
    assert d.caen_efficiency_compliance('CDCU-300', 97.1, 1.00) == 'pass'
    assert d.caen_efficiency_compliance('CDCU-300', 97.0, 1.00) == 'fail'
    # CAEN states the value at full load; 50% load is not a compliance test.
    assert d.caen_efficiency_compliance('CDCU-300', 90.0, 0.50) == 'not_applicable'


def test_expected_current():
    expected = d.expected_input_current(20, 300, 36, 0.97)
    assert abs(expected - (6000 / (36 * 0.97))) < 1e-9
    delta, pct = d.bus_current_percent_error(expected * 1.05, expected)
    assert abs(delta - expected * 0.05) < 1e-9
    assert abs(pct - 5.0) < 1e-9
    assert abs(d.percent_to_ppm(pct) - 50000) < 1e-6


def test_efficiency_ppm_semantics():
    # -0.6 percentage points is -6000 ppm on an absolute fractional basis.
    assert abs(d.percent_point_delta_to_abs_ppm(-0.6) + 6000.0) < 1e-9
    # Relative ppm uses the named reference as the denominator.
    rel = d.relative_percent_difference_ppm(96.4, 97.0)
    assert abs(rel - ((96.4 - 97.0) / 97.0) * 1e6) < 1e-9



def test_switching_frequency_specs():
    assert d.get_model_spec('CDCU-100')['switching_frequency_Hz'] == 100000.0
    assert d.get_model_spec('CDCU-100')['equivalent_switching_frequency_Hz'] == 100000.0
    assert d.get_model_spec('CDCU-200')['equivalent_switching_frequency_Hz'] == 200000.0
    assert d.get_model_spec('CDCU-300')['equivalent_switching_frequency_Hz'] == 300000.0


def test_load():
    assert d.substantial_load('CDCU-300', 3375)
    assert not d.substantial_load('CDCU-300', 3000)


def test_override():
    eta, src = d.eta_reference_details('CDCU-300', .978)
    assert eta == .978 and src == 'unit_override'
    try:
        d.eta_reference_details('CDCU-300', 1.2)
    except ValueError:
        pass
    else:
        raise AssertionError('invalid eta accepted')


def test_fft_normalization():
    fs = 4096.0
    n = 4096
    t = np.arange(n) / fs
    # Bin-centered 1 V-peak sine should return 1/sqrt(2) Vrms at 128 Hz.
    x = np.sin(2.0 * np.pi * 128.0 * t)
    f, a = psd.single_sided_fft_rms(x, fs)
    idx = int(np.argmin(np.abs(f - 128.0)))
    assert abs(a[idx] - 1.0 / math.sqrt(2.0)) < 1e-10


def test_welch_parseval_and_sampling_resample():
    fs = 10000.0
    n = 100001
    t = np.arange(n) / fs
    x = 0.1 * np.sin(2.0 * np.pi * 150.0 * t)
    # Add a small deterministic timestamp perturbation to simulate network polling jitter.
    tj = t.copy()
    tj[1::2] += 5e-6
    df = pd.DataFrame({'time': tj, 'x': x})
    _, prepared, fs_prepared, _, info = psd.load_trace_from_df(
        df, 'time', 'x', timing_cv_limit=0.001, resample_if_irregular=True
    )
    assert info['resampled'] is True
    f, pxx = psd.welch_psd(prepared, fs_prepared, nperseg=psd.recommended_welch_nperseg(len(prepared)))
    rms_psd = math.sqrt(max(float(np.trapezoid(pxx, f)), 0.0))
    rms_time = float(np.sqrt(np.mean((prepared - np.mean(prepared)) ** 2)))
    assert abs(rms_psd - rms_time) / rms_time < 0.01


if __name__ == '__main__':
    test_caen_full_load_compliance()
    test_expected_current()
    test_efficiency_ppm_semantics()
    test_switching_frequency_specs()
    test_load()
    test_override()
    test_fft_normalization()
    test_welch_parseval_and_sampling_resample()
    print('PASS')
