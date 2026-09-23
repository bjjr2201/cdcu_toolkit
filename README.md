
## v28 FFT Callout Update

FFT plot arrow callouts now identify the three strongest spectral components strictly below 1 kHz. The underlying FFT/PSD calculations, full displayed spectrum, dominant-component summary, and standard frequency-band integration are unchanged.

CDCU TOOLKIT
CAENels CDCU-100 / CDCU-200 / CDCU-300 Engineering Diagnostics

Authored By:
Byron Jordan
Power Supply Engineer
Advanced Photon Source (APS)
Argonne National Laboratory

======================================================================
1. PURPOSE
======================================================================

cdcu_toolkit is a field and test-stand diagnostic package for the CAENels
CDCU family.  The toolkit is built around the measurements that matter when a
converter is being qualified, conditioned, or faulted:

  MRP   - measured DC-bus voltage
  MGPC  - measured DC-bus/input current
  MRV   - measured output voltage
  MRI   - measured output current
  MFTR  - fault register
  MSTR  - status register
  PMM   - Post-Mortem Monitor waveform capture

The normal workflow combines live polling, power-balance calculations,
steady-state efficiency checks, PMM capture, fault-cascade tracking, FFT/PSD
analysis, ppm reporting, CSV logging, plots, and report generation.

The toolkit is diagnostic.  It does not automatically call a Hall sensor,
PWM Logic Board, Buck/MOSFET Driver board, DCCT, or other component defective.
The intent is to preserve the evidence needed to make that determination.

CAENels User's Manual Rev. 1.0 lists these full-load efficiency minimums:

  CDCU-100   >92 %
  CDCU-200   >94 %
  CDCU-300   >97 %

These values are manufacturer compliance floors at full load.  A unit-specific
healthy baseline may be higher and is preferred for expected-input-current
calculations when a defensible baseline is available.

======================================================================
REVISION 25 UPDATE
======================================================================

The live monitor remains a dynamic telemetry display.  It does not replace
ramped or transient samples with steady-state medians.  Revision 25 adds a
light magnet-cycling overlay to the live plots and consolidated multi-IP
dashboard.  When the measured output-current slope exceeds the cycling
threshold, the affected time segment is shaded across Power, Electrical
Values, Efficiency, and Temperature panels.  The CSV also includes
is_magnet_cycling so post-run review can identify those dynamic intervals.

The default cycling threshold is 0.5 A/s.  It can be tuned without editing
code by setting the environment variable:

  CDCU_CYCLING_DIDT_THRESHOLD_A_PER_S

Example PowerShell setting:

  $env:CDCU_CYCLING_DIDT_THRESHOLD_A_PER_S = "0.5"


======================================================================
REVISION 20 UPDATE
======================================================================

FFT Analysis - PMM Output plots now keep the magnet load description inside
 the upper-right engineering summary box, directly below the Dominant
 Components section so the load context is easy to reference while reviewing
 spectral content.

The same FFT plots now annotate the two dominant components with boxed arrow
 callouts.  The callouts are intentionally placed inside the plot frame and
 away from the main engineering summary so the peak markers stay readable and
 do not cover other report content.

======================================================================
2. FILES
======================================================================

cdcu_monitor.py
  Primary live monitor.  Polls the converter, logs measurements, calculates
  engineering diagnostics, captures the initial PMM, captures PMM data after
  new faults, tracks the fault cascade, and launches post-run analysis.

cdcu_diagnostics.py
  Reusable power, efficiency, expected-input-current, load-fraction, ppm,
  plateau, and health-classification functions.

cdcu_pmm.py
  Low-level PMM acquisition.  Arms, forces, waits, fetches, timestamps, and
  rearms the CAEN PMM buffer.

cdcu_pmm_fft.py
  Standalone PMM FFT/PSD utility.  Use this when a PMM CSV already exists and
  no live CDCU connection is required.

cdcu_ripple_analyzer.py
  Compatibility launcher retained for older commands.  Spectral analysis is
  PMM-only and routes saved PMM CSV files to cdcu_pmm_fft.py.  Live polling
  CSV files are not used as FFT/PSD sources.

cdcu_ripple_psd.py
  Core FFT, PSD, cumulative RMS, spectral-band, significant-component, and
  plotting routines.

cdcu_ripple_bands.py
  Defines the frequency bands used by the ripple analysis.

cdcu_ripple_io.py
  CSV metadata and ripple-analysis file support.

cdcu_ripple_pdf.py
  Builds the engineering PDF report from monitor and PMM analysis products.

cdcu_registers.py
  Decodes MFTR, MSTR, and warning/status register values into readable names.

cdcu_load_map.py
  Resolves cabinet/IP/sector information from load_map_with_magnetid.json.

one_liners.py
  Convenience launcher for one or several supplies, including cabinet-based
  selection from the load map.

load_map_with_magnetid.json
  Site/load metadata.  This is also where a known-good eta_reference_pct can be
  assigned to an individual supply when that baseline has been established.

test_cdcu_diagnostics.py
  Small regression test for the diagnostic formulas and model thresholds.

CDCU_Toolkit_Function_and_Sequence_Guide.docx
  Engineering description of toolkit architecture, execution sequence,
  diagnostic logic, PMM handling, fault cascade, and FFT/PSD workflow.

ANL_RGB-APS-fullname_horiz.png
  APS/Argonne branding asset used by reports and documentation.

======================================================================
3. PYTHON ENVIRONMENT
======================================================================

Run the toolkit from the directory containing the scripts.

Typical packages:

  python3 -m pip install numpy pandas matplotlib scipy reportlab

The scripts use only standard Python modules beyond the packages above.
Use the site-approved Python environment on APS production systems.

Quick syntax check:

  python3 -m compileall -q .

Diagnostic regression check:

  python3 test_cdcu_diagnostics.py

======================================================================
4. LIVE MONITOR - BASIC RUN
======================================================================

Minimum command:

  python3 cdcu_monitor.py --host 192.168.x.x

Recommended run with load-map information:

  python3 cdcu_monitor.py \
      --host 192.168.x.x \
      --cabinet Test_1 \
      --sector B400A \
      --duration 120 \
      --interval 0.40 \
      --outdir ./cdcu_logs

Show the command-line options:

  python3 cdcu_monitor.py --help

Available options:

  --host IP
      CDCU Ethernet address.

  --cabinet NAME
      Cabinet key in load_map_with_magnetid.json.

  --sector STR
      Sector text used to resolve {SECTOR} placeholders in the load map.

  --duration SEC
      Total live-polling duration.

  --interval SEC
      Requested delay between polling bursts.

  --outdir DIR
      Directory used for CSV files, plots, PMM captures, analysis, and reports.

  --no-analysis
      Skip optional end-of-run report assembly.  The startup, fault-triggered,
      and final PMM captures are still analyzed immediately because those PMM
      records are the authoritative spectral witnesses for the run.

  --no-plot
      Suppress the live Matplotlib window.  This is useful for batch operation
      or a headless host.

======================================================================
5. WHAT HAPPENS DURING A NORMAL LIVE RUN
======================================================================

The execution order is intentional.  Live Ethernet polling and PMM spectral
analysis serve different purposes and are kept separate.

1. Parse command-line settings.
2. Resolve the load map, magnet identification, ratings, and optional
   unit-specific efficiency baseline.
3. Open the CDCU TCP connection and read identity/configuration data.
4. Arm and force a startup PMM capture.
5. Wait for the hardware-timed PMM record to complete, fetch it, save it, and
   analyze its FFT/PSD immediately.
6. Rearm PMM for a hardware-triggered fault event.
7. Start the live MRP/MGPC/MRV/MRI/MFTR polling loop.
8. Use live polling for slow engineering diagnostics: Pin, Pout, efficiency,
   expected input current, IBUS deviation, load fraction, power loss, state,
   and ordered fault tracking.
9. Do NOT run FFT/PSD on the live polling samples.  They are sequential network
   measurements and are not the spectral source of record.
10. When a new fault stage appears, preserve only newly observed fault names in
    first-observed order.  If the hardware-triggered PMM is ready, fetch it,
    save it, and analyze it immediately.
11. Rearm PMM after the fault capture so a later fault stage can create another
    spectral record if the hardware triggers again.
12. Immediately before the requested live-polling duration expires, force one
    final PMM capture.  If the final polling burst crosses the timeout before
    the pre-timeout force can be issued, the monitor forces the PMM immediately
    at timeout as a fallback rather than losing the final spectral witness.
13. After polling stops, wait for that final PMM record to complete, fetch it,
    save it, and analyze FFT/PSD immediately.
14. Save the final live plot, CSV, diagnostic summary, PMM products, and reports.

The three PMM roles are therefore:

  STARTUP PMM  -> spectral condition at the beginning of the run
  FAULT PMM    -> hardware-timed spectral evidence associated with a fault stage
  FINAL PMM    -> spectral condition at the end of the live-polling interval

This gives a direct startup-versus-end-of-run comparison even when the live
setpoint is neither 0 A nor full-scale current.  The comparison remains valid
because both spectra come from the same 10 kHz hardware-timed PMM acquisition
path rather than from the live polling stream.

A fault sequence is kept in first-observed order.  A fault report may therefore
read:

  1. Input Over-Current
  2. Input Over-Current HW fault
  3. HW Fault

The order is preserved to separate the initiating indication from faults that
appear later as a consequence of the shutdown.

======================================================================
6. STARTUP, FAULT, AND FINAL PMM BEHAVIOR
======================================================================

FFT/PSD is run only on PMM sample data.  The PMM record contains 100,001 samples
at a fixed 10 kHz hardware sample rate, so it is the preferred spectral source
for frequency-domain troubleshooting.

Startup PMM:
  - forced before live polling starts;
  - saved under pmm_captures/<prefix>_initial_pmm.csv;
  - analyzed immediately;
  - establishes the beginning-of-run spectral condition.

Fault PMM:
  - hardware-triggered when the CDCU provides a fault-triggered PMM record;
  - saved under fault_events/;
  - analyzed immediately;
  - summary states FAULT OCCURRED: YES;
  - fault names are listed in the order first observed;
  - PMM is rearmed after each captured fault stage.

Final PMM:
  - PMM:FORCE is issued immediately before the live-polling timeout;
  - if the final polling burst crosses the timeout first, PMM:FORCE is issued at
    timeout as a fallback;
  - saved under pmm_captures/<prefix>_final_pmm.csv;
  - analyzed immediately after the hardware record is ready;
  - provides the end-of-run spectrum for direct comparison to startup.

Immediate analysis folders are organized as:

  analysis/pmm/initial_01/
  analysis/pmm/fault_01/
  analysis/pmm/fault_02/
  analysis/pmm/final_01/

Welch PSD configuration:

  nperseg = 16384 whenever the PMM record contains at least 16384 samples
  overlap = 50 %
  window = Hann

At Fs = 10,000 Hz, nperseg = 16,384 gives approximately 0.61035 Hz frequency
spacing before Welch averaging.  That resolution is preferred for the low
frequency bands used in CDCU analysis while retaining multiple averages across
the 100,001-sample PMM record.

======================================================================
7. RUN ONLY FFT/PSD FROM AN EXISTING PMM FILE
======================================================================

A live CDCU connection is not required when a PMM CSV has already been saved.
Use cdcu_pmm_fft.py.  Do not use a live-polling CSV for FFT/PSD; the standalone
frequency-domain path accepts PMM records only.

Analyze all three PMM channels:

  python3 cdcu_pmm_fft.py \
      --csv ./run/pmm_captures/S28A_Q4_initial_pmm.csv

Choose an output directory:

  python3 cdcu_pmm_fft.py \
      --csv ./run/fault_events/S28A_Q4_fault01.csv \
      --outdir ./pmm_review

Analyze only output current:

  python3 cdcu_pmm_fft.py \
      --csv ./run/fault_events/S28A_Q4_fault01.csv \
      --channels iout_A

Analyze output voltage and output current:

  python3 cdcu_pmm_fft.py \
      --csv ./run/fault_events/S28A_Q4_fault01.csv \
      --channels vout_V,iout_A

Supply engineering ppm reference values instead of using each channel's DC mean:

  python3 cdcu_pmm_fft.py \
      --csv ./run/fault_events/S28A_Q4_fault01.csv \
      --iout-ref 300 \
      --iset-ref 300 \
      --vout-ref 45

Add a load description to the report:

  python3 cdcu_pmm_fft.py \
      --csv ./run/fault_events/S28A_Q4_fault01.csv \
      --load-desc "S28A:Q4 CDCU-300 conditioning fault"

Show every standalone PMM option:

  python3 cdcu_pmm_fft.py --help

The PMM CSV must contain:

  time_s

and at least one of:

  vout_V
  iout_A
  iset_A

The standalone utility uses the same FFT/PSD engine as the live PMM analysis.

The primary FFT graphic now uses a linear-frequency, filled-spectrum presentation. This is the first-look troubleshooting view: harmonic spacing is visible immediately, dominant components stand out without a logarithmic axis, and the summary box reports DC reference, total ripple RMS, percent, ppm, and the dominant integrated frequency band. PSD and cumulative integrated ripple remain available as the deeper engineering views.

Select the primary FFT Y-axis with `--fft-y`:

```bash
# Physical magnitude (default; auto-scales A to mA and V to mV when appropriate)
python3 cdcu_pmm_fft.py --csv ./fault.csv --channels iout_A --iout-ref 300 --fft-y magnitude

# Percent of the supplied engineering reference
python3 cdcu_pmm_fft.py --csv ./fault.csv --channels iout_A --iout-ref 300 --fft-y percent

# Parts per million of the supplied engineering reference
python3 cdcu_pmm_fft.py --csv ./fault.csv --channels iout_A --iout-ref 300 --fft-y ppm
```

`--fft-y percent` and `--fft-y ppm` require a valid nonzero reference. For output current, use the applicable engineering reference such as rated current or the operating reference being evaluated. Do not use an arbitrary reference simply to make the ppm number look smaller.

Typical outputs include FFT, PSD, cumulative integrated ripple power/RMS,
frequency-band values, ppm values, a composite report graphic, and a text
summary.

======================================================================
8. POST-RUN FFT/PSD FROM A LIVE MONITOR CSV
======================================================================

Analyze a specific monitor CSV:

  python3 cdcu_ripple_analyzer.py --csv ./cdcu_logs/cdcu_192_168_3_2.csv

Analyze the newest monitor CSV under a directory:

  python3 cdcu_ripple_analyzer.py --latest --root ./cdcu_logs

Override the load description:

  python3 cdcu_ripple_analyzer.py \
      --csv ./cdcu_logs/cdcu_192_168_3_2.csv \
      --load-desc "B400A DMM Q3"

Show analyzer options:

  python3 cdcu_ripple_analyzer.py --help

======================================================================
9. MULTI-SUPPLY / ONE-LINER OPERATION
======================================================================

List the launcher options:

  python3 one_liners.py --help

List known load-map targets:

  python3 one_liners.py --list

Run explicit IP addresses:

  python3 one_liners.py \
      --ips 192.168.3.2 192.168.3.3 \
      --duration 120 \
      --outdir ./cdcu_logs

Run by cabinet/sector:

  python3 one_liners.py \
      --cabinet Cab_1 \
      --sector S28 \
      --duration 120 \
      --outdir ./cdcu_logs

Preview what would be launched without starting monitor processes:

  python3 one_liners.py \
      --cabinet Cab_1 \
      --sector S28 \
      --dry-run

Skip optional post-run report assembly for the launched monitors:

  python3 one_liners.py \
      --ips 192.168.3.2 192.168.3.3 \
      --no-analysis

======================================================================
10. LOAD MAP
======================================================================

List the load map:

  python3 cdcu_load_map.py --list

Look up a specific entry:

  python3 cdcu_load_map.py \
      --map load_map_with_magnetid.json \
      --cabinet Test_1 \
      --ip 192.168.5.2 \
      --sector B400A

The optional per-unit field:

  "eta_reference_pct": 97.8

is treated as the expected healthy efficiency baseline for the current-domain
power-balance calculation.  It does not replace the CAEN manufacturer minimum.

Baseline priority:

  1. unit-specific eta_reference_pct
  2. configured empirical model baseline
  3. CAEN full-load minimum as fallback

The output records eta_reference_source so the origin of the comparison value
is never ambiguous.

======================================================================
11. REGISTER DECODING
======================================================================

Decode an MFTR value:

  python3 cdcu_registers.py --mftr 00000010

Decode status and warning registers at the same time:

  python3 cdcu_registers.py \
      --mftr 00000010 \
      --mstr 00000012 \
      --mwrr 00000001

Show options:

  python3 cdcu_registers.py --help

======================================================================
12. ENGINEERING DIAGNOSTICS
======================================================================

Power:

  Pin  = |Vbus x Ibus|
  Pout = |Vout x Iout|

Measured efficiency:

  eta_measured = Pout / Pin

Expected input current:

  Ibus_expected = Pout / (Vbus x eta_reference)

Input-current residual:

  IBUS_delta_A = Ibus_measured - Ibus_expected

  IBUS_pct_error = 100 x IBUS_delta_A / Ibus_expected

Relative metrics are also reported in ppm where useful:

  1 % = 10,000 ppm

Example:

  +2.80 % = +28,000 ppm

The ppm conversion does not change the measurement.  It gives the same
relative deviation in the unit normally used for accelerator stability and
precision reporting.

The IBUS residual is a current-domain representation of the power-balance
result.  It is not mathematically independent of measured efficiency.

======================================================================
13. STEADY-STATE AND LOAD GATING
======================================================================

Efficiency and expected-input-current comparisons are not assigned during a
rapid ramp simply because four sequentially polled values can represent
slightly different instants and stored energy is moving through the converter
and magnet.

A sample becomes diagnostic-valid only when the required conditions are met,
including:

  valid telemetry
  known CDCU model
  stable output-current plateau
  sufficient dwell time
  output power above the configured minimum load fraction
  valid efficiency reference

The default minimum diagnostic load fraction is 25% of rated output power.
A steady low-load operating point is labeled low_load rather than being judged
against a full-load CAEN efficiency requirement.

======================================================================
14. DIAGNOSTIC STATES
======================================================================

Typical states are:

  transient
  low_load
  healthy
  investigate
  invalid
  unknown_model

A run-level investigate result requires persistence.  One isolated sample does
not condemn the entire run.

======================================================================
15. PPM REPORTING
======================================================================

The toolkit reports ppm when the metric represents a relative error, ripple,
stability, or deviation and ppm adds engineering value.

Examples:

  Efficiency deviation:  -0.50 % / -5,000 ppm
  IBUS error:             +2.80 % / +28,000 ppm
  Ripple RMS:                        8.4 ppm

Absolute quantities remain in their physical units:

  V, A, W, Hz, ohm, H, seconds

Do not reinterpret a large percentage efficiency loss as a precision stability
number merely because it can be converted to ppm.  Both forms are reported so
the scale remains obvious.

======================================================================
16. OUTPUT DIRECTORY STRUCTURE
======================================================================

A run may produce folders similar to:

  <run>/
      cdcu_<host>.csv
      cdcu_<host>_live.png
      pmm_captures/
          <prefix>_initial_pmm.csv
      fault_events/
          <prefix>_fault01_<time>.csv
          <prefix>_fault02_<time>.csv
      analysis/
          pmm/
              initial_01/
              fault_01/
              fault_02/
          ...
      reports/
          ...

Exact report names depend on the selected analysis path and available data.

======================================================================
17. PRACTICAL TROUBLESHOOTING USE
======================================================================

For an Input Over-Current or Input Over-Current HW fault, compare:

  MRP / DC-bus voltage
  MGPC / input current
  MRV / output voltage
  MRI / output current
  expected input current
  measured efficiency
  IBUS error in A, %, and ppm
  initial PMM spectral condition
  first fault-triggered PMM
  later fault-triggered PMM captures, if the fault sequence cascades
  known-good converter behavior under the same load and bus conditions

CAEN's Service Manual identifies more than one possible origin for these faults,
including the Buck/MOSFET Driver boards, the input Hall current sensor, and CH4
over-current sensing on the PWM Logic Board.  Use the toolkit to determine which
measurement path lost credibility first; do not skip the independent electrical
checks required to prove the failed component.

======================================================================
18. COMMON COMMANDS - QUICK REFERENCE
======================================================================

Live monitor:
  python3 cdcu_monitor.py --host 192.168.x.x

Live monitor without GUI:
  python3 cdcu_monitor.py --host 192.168.x.x --no-plot

Live logging without final ripple analysis:
  python3 cdcu_monitor.py --host 192.168.x.x --no-analysis

Analyze saved PMM only:
  python3 cdcu_pmm_fft.py --csv path/to/pmm.csv

Analyze saved PMM output current only:
  python3 cdcu_pmm_fft.py --csv path/to/pmm.csv --channels iout_A

Analyze saved live-monitor CSV:
  python3 cdcu_ripple_analyzer.py --csv path/to/cdcu_monitor.csv

Newest saved live-monitor CSV:
  python3 cdcu_ripple_analyzer.py --latest --root ./cdcu_logs

Load-map listing:
  python3 cdcu_load_map.py --list

Multi-unit launcher listing:
  python3 one_liners.py --list

Decode MFTR:
  python3 cdcu_registers.py --mftr HEXVALUE

Compile check:
  python3 -m compileall -q .

Diagnostic test:
  python3 test_cdcu_diagnostics.py

======================================================================
19. SOURCE DOCUMENTS
======================================================================

CAENels, CDCU User's Manual, Rev. 1.0, November 2019.
  Technical Specifications, page 42.

CAENels, CDCU Remote Control Manual, Rev. 1.3, March 2023.
  Remote commands, PMM command set, and waveform/post-mortem functions.

CAENels, CDCU Service Manual, Rev. 1.0, March 2023.
  Hardware architecture and fault troubleshooting guidance.

======================================================================
20. AUTHOR
======================================================================

Byron Jordan
Power Supply Engineer
Advanced Photon Source (APS)
Argonne National Laboratory

======================================================================
11. MATHEMATICAL VALIDATION AND REFERENCE CONVENTIONS (REVISION 11)
======================================================================

The Revision 11 math review separates three ideas that should not be mixed:

  1. CAEN full-load efficiency compliance,
  2. diagnostic comparison against a known-good efficiency baseline,
  3. ripple/stability reporting in percent and ppm.

CAEN full-load efficiency compliance
------------------------------------

The User's Manual states the efficiency specification at full load. The toolkit
therefore does not use >92%, >94%, or >97% as a manufacturer pass/fail limit at
25%, 40%, or 60% output power.

General power-balance diagnostics remain enabled above the configurable
minimum diagnostic load fraction (default 25%). A separate CAEN compliance
state becomes valid only near rated full load. The default threshold is 95% of
rated output power and is intentionally identified as an engineering test gate,
not a CAEN-defined tolerance.

The CSV reports:

  caen_full_load_compliance_valid
  caen_efficiency_compliance

Possible compliance states are:

  pass
  fail
  not_applicable
  invalid
  unknown_model

A lower-power test may still be useful for old-unit/replacement-unit comparison,
but it is not labeled a CAEN full-load compliance test.

Efficiency difference: percent, percentage points, and ppm
-----------------------------------------------------------

Efficiency is still reported directly in percent. When comparing two efficiency
values, the toolkit distinguishes:

  percentage-point difference
      eta_measured_pct - eta_reference_pct

  absolute fractional ppm
      percentage-point difference x 10,000

  relative ppm referenced to the named efficiency reference
      ((eta_measured_pct - eta_reference_pct) / eta_reference_pct) x 1e6

Example:

  measured efficiency = 96.4%
  reference efficiency = 97.0%

  difference = -0.6 percentage points
  absolute fractional difference = -6,000 ppm
  relative difference = approximately -6,186 ppm relative to 97.0%

Every ppm value should answer the question "ppm relative to what?"

PMM ppm/FS versus ppm of operating point
----------------------------------------

Use --model when running a saved PMM whenever the CDCU model is known:

  python3 cdcu_pmm_fft.py \
      --csv ./fault.csv \
      --model CDCU-300 \
      --channels iout_A \
      --fft-y ppm

With --model CDCU-300, the default references are:

  iout_A  -> 300 A full scale
  iset_A  -> 300 A full scale
  vout_V  -> 45 V full scale

The corresponding output is explicitly labeled ppm of full scale.

An explicit --iout-ref, --iset-ref, or --vout-ref overrides the model-derived
reference and is labeled as an operator reference.

If neither a model nor an explicit reference is supplied, the PMM utility uses
the channel DC mean and labels the result as ppm of operating point. This value
must not be called ppm/FS.

FFT normalization
-----------------

The FFT is a coherent-gain-corrected, single-sided RMS line spectrum. Interior
positive-frequency bins are doubled to account for the omitted negative-frequency
half of a real-valued FFT. DC and Nyquist are not doubled. Interior sinusoidal
peak amplitudes are converted to RMS by division by sqrt(2).

The FFT Y-axis is labeled RMS Amplitude. Depending on --fft-y it may be shown as:

  RMS Amplitude (A or mA)
  RMS Amplitude (V or mV)
  RMS Amplitude (%)
  RMS Amplitude (ppm)

Welch PSD and low-frequency resolution
--------------------------------------

PMM analysis now prefers a Welch nperseg of 16,384 samples when the record is
long enough. At a 10 kHz PMM sample rate this gives approximately:

  df = 10000 / 16384 = 0.61035 Hz

This improves integration of low-frequency bands such as 1-10 Hz compared with
a 4096-sample segment. Shorter records automatically step down to a practical
segment length.

Band RMS is calculated from:

  RMS_band = sqrt(integral PSD(f) df over the requested band)

The PSD is interpolated at each requested band edge before integration so a
coarse frequency bin landing just inside or outside a band has less influence on
the result.

Sampling uniformity
-------------------

A conventional FFT assumes uniformly spaced samples. PMM data normally meets
this requirement directly. Network polling does not necessarily do so.

Before FFT/PSD processing, the toolkit calculates the coefficient of variation
of the sample intervals:

  CV(dt) = standard_deviation(dt) / mean(dt)

FFT/PSD is PMM-only, so the software does not resample live polling data into a
spectrum.  An imported PMM file must retain an effectively uniform time base.
The current integrity limit is CV(dt) <= 0.0001 (0.01%).  A PMM file outside that
limit is rejected for spectral analysis so a damaged or non-PMM time series is
not made to look authoritative through interpolation.

Parseval consistency check
--------------------------

Each spectral analysis compares time-domain AC RMS against RMS recovered by
integrating the Welch PSD:

  RMS_time = sqrt(mean((x - mean(x))^2))

  RMS_PSD = sqrt(integral PSD(f) df)

The report calculates:

  Parseval error (%) = 100 x (RMS_PSD - RMS_time) / RMS_time

A difference within +/-3% is reported as PASS. This is an internal mathematical
quality check, not a CAEN acceptance limit.

## Live Monitor Signal Selection

The live polling signal set is controlled from one dictionary near the top of `cdcu_monitor.py`.  Add, remove, or comment out entries in this block; the polling list is generated automatically from the dictionary.

```python
SIGNALS = {
    "MRP":  {"label": "DC Bus Voltage",          "unit": "V",   "numeric": True,  "plot": True},
    "MGPC": {"label": "Input Current",           "unit": "A",   "numeric": True,  "plot": True},
    "MRV":  {"label": "Output Voltage",          "unit": "V",   "numeric": True,  "plot": True},
    "MRI":  {"label": "Output Current",          "unit": "A",   "numeric": True,  "plot": True},
    "SN":   {"label": "Serial Number",           "unit": "",    "numeric": False, "plot": False},
    "MSRI": {"label": "Current Ramp Slew Rate",  "unit": "A/s", "numeric": True,  "plot": False},
    "MFTR": {"label": "Fault Register",          "unit": "",    "numeric": False, "plot": False},
    "MRW":  {"label": "Estimated Active Power", "unit": "W",   "numeric": True,  "plot": False},
    "VER":  {"label": "Firmware Version",        "unit": "",    "numeric": False, "plot": False},
}
```

`numeric=True` tells the monitor to parse the reply as a floating-point value.  `plot=True` places that numeric signal on the **Electrical Values** panel.  Non-numeric registers are still saved in raw form to the CSV.

`MRP`, `MGPC`, `MRV`, and `MRI` feed the power-balance and efficiency calculations.  If one of those four signals is removed, the monitor continues to run, but any derived calculation that requires the missing signal is intentionally reported as `NaN`.

### Report branding

`ANL_RGB-APS-fullname_horiz.png` is loaded directly as a PNG and its alpha channel is preserved in matplotlib and ReportLab output.  The former typed footer string is intentionally disabled in `cdcu_monitor.py`:

```python
# _LOGO_TEXT_A = "Argonne National Laboratory – APS"
_LOGO_TEXT_A = None
```

The PNG now occupies the branding location previously used by that text.

## Dedicated Live Temperature Plot

Revision 14 adds a second live matplotlib figure for every temperature value exposed by the CDCU `MRT` command family. CAEN defines the available temperature reads as:

- `MRT` - maximum internal temperature readout
- `MRT:1` - Buck temperature
- `MRT:2` - Capacitor Bank temperature
- `MRT:3` - ADC and Shunt temperature
- `MRT:4` - Carrier Board temperature

These signals are configured in the same `SIGNALS` dictionary used by the rest of the live monitor:

```python
"MRT":   {"label": "Maximum Internal Temperature", "unit": "degC", "numeric": True, "plot": False, "temperature_plot": True},
"MRT:1": {"label": "Buck Temperature",             "unit": "degC", "numeric": True, "plot": False, "temperature_plot": True},
"MRT:2": {"label": "Capacitor Bank Temperature",   "unit": "degC", "numeric": True, "plot": False, "temperature_plot": True},
"MRT:3": {"label": "ADC and Shunt Temperature",    "unit": "degC", "numeric": True, "plot": False, "temperature_plot": True},
"MRT:4": {"label": "Carrier Board Temperature",    "unit": "degC", "numeric": True, "plot": False, "temperature_plot": True},
```

`temperature_plot=True` places the signal on the dedicated **CDCU Internal Temperatures** figure. It does not place the same signal on the mixed-unit Electrical Values panel. This keeps all temperature traces on one common degrees-Celsius scale.

The monitor saves the temperature plot beside the normal live plot:

```text
<PREFIX>_live.png
<temperature data is included in <PREFIX>_live.png>
```

The CSV preserves the raw MRT replies and also adds parsed numeric columns:

```text
MRT_float
MRT_1_float
MRT_2_float
MRT_3_float
MRT_4_float
```

To remove a temperature from the live figure, either comment out its `SIGNALS` entry or set `temperature_plot` to `False`. The remaining temperature channels continue to operate normally.

======================================================================
21. MAGNET LOAD CHARACTERIZATION AND LOAD-MAP COMPARISON (REVISION 15)
======================================================================

Revision 15 compares the magnet characteristics measured during a live CDCU run
against the nameplate/reference values already carried in
`load_map_with_magnetid.json`.

Existing APS load-map entries place the magnet values in `load_desc`, for example:

  Magnet: B400A_slot_5; DMM_Q3; Resistance: 0.064 Ohm; Inductance: 16.9 mH

The toolkit parses those values automatically. Future load maps can instead use
explicit numeric fields (`magnet_resistance_ohm`, `magnet_inductance_H`, or
`magnet_inductance_mH`) without changing the monitor.

Steady-state resistance
-----------------------

At a stable current plateau, dI/dt is approximately zero and the magnet equation
reduces to:

  V = R I
  R_measured = MRV / MRI

The toolkit uses steady-state points above 10% of the detected CDCU current
rating, then reports the median measured resistance. This avoids using the V/I
ratio close to zero current where sensor offset can dominate the result.

The comparison reports:

  measured resistance (ohm and mOhm)
  load-map/nameplate resistance
  absolute difference
  percent difference
  ppm of the load-map/nameplate value

Dynamic inductance estimate
---------------------------

During a current ramp:

  V = R I + L dI/dt

therefore:

  L_estimated = (MRV - R MRI) / (dI/dt)

`dI/dt` is estimated from consecutive timestamped MRI samples. Once a valid
steady-state resistance has been measured, that value is used in the inductance
calculation. Before a steady plateau is available, the load-map resistance is
used.

This is a live-polling estimate, not a precision LCR measurement. Ethernet
polling is slower than PMM acquisition and MRV/MRI are not truly simultaneous.
Use the value for trend comparison, fault investigation, and consistency checks.

Extrapolation to CDCU rated current
-----------------------------------

The toolkit detects the CDCU model from the SN response and uses the model's
rated current, voltage, and maximum output power. Using the measured steady-state
resistance when available:

  V_at_rated = I_rated R_measured
  P_at_rated = I_rated^2 R_measured

It then reports voltage and power utilization against the CDCU rating.

For dynamic headroom, the toolkit also estimates:

  (dI/dt)_max = (V_CDCU,max - I_rated R) / L

The best available measured R/L values are used first; load-map values are used
as fallbacks.

Files and output
----------------

Per-sample CSV columns include:

  Magnet_R_measured_ohm
  Magnet_R_measured_mOhm
  Magnet_R_nameplate_ohm
  Magnet_R_delta_mOhm
  Magnet_R_error_pct
  Magnet_R_error_ppm
  Magnet_dIdt_A_per_s
  Magnet_L_estimated_H
  Magnet_L_estimated_mH
  Magnet_L_nameplate_H
  Magnet_L_delta_mH
  Magnet_L_error_pct
  Magnet_L_error_ppm

Each run also creates:

  <PREFIX>_magnet_load_summary.txt

The run summary compares load-map/nameplate values with measured values and
projects the load to the CDCU maximum current rating.

Engineering interpretation
--------------------------

A resistance difference is not automatically a fault. Magnet winding resistance
changes with temperature, and the load-map value may have been measured under a
different thermal condition. Compare the deviation with coil temperature,
conditioning history, cable resistance, and the original basis of the load-map
value before assigning a failure mechanism.

Similarly, the live-ramp inductance value is an estimate. A consistent deviation
across several runs is more meaningful than one sample. For acceptance-quality
inductance measurements, use the approved magnet measurement method or dedicated
instrumentation.


REVISION 16 - INTEGRATED TEMPERATURE PANEL
-----------------------------------------
The MRT temperature channels are plotted in the same live monitor window as Power, Electrical Values, and Efficiency. The temperature panel is the fourth panel, directly below Efficiency. Temperature channels retain their own degree-Celsius axis and are included in the normal <PREFIX>_live.png output; a separate temperature PNG is no longer generated.


======================================================================
REVISION 16.1 - WINDOWS FINAL PMM SOCKET LIFECYCLE FIX
======================================================================

Corrected the final PMM acquisition sequence so the fallback PMM force and
final PMM fetch/analysis execute before the CDCU TCP socket context closes.
This resolves Windows WinError 10038 during end-of-run PMM acquisition.
Socket-timeout restoration is also guarded so cleanup cannot mask the original
PMM error if the socket is already unavailable.

======================================================================
REVISION 17 - WHITE-BACKGROUND BRANDING / PDF FOOTER
======================================================================

The bundled ANL_RGB-APS-fullname_horiz.png remains a true RGBA transparent
asset.  The APS name and Argonne National Laboratory text are rendered in a
dark, white-background-safe treatment while the existing Argonne symbol is
preserved.

FFT/PSD engineering PDFs place this branding block in the bottom-right page
footer.  The legacy monitor constant remains disabled:

  # _LOGO_TEXT_A = "Argonne National Laboratory – APS"
  _LOGO_TEXT_A = None

This avoids duplicate typed branding and lets the transparent image provide the
entire footer identity block.


======================================================================
REVISION 18 - 1 kHz STANDARD BAND + OFFICIAL APS BRANDING
======================================================================

Revision 18 adds a fourth standard integrated FFT/PSD band:

  720-1200 Hz

This band intentionally places 1 kHz inside the band rather than exactly on a
band edge.  The standard PMM spectral bands are now:

  1-10 Hz
  60-120 Hz
  360-720 Hz
  720-1200 Hz

PMM acquisition remains fixed at 10 kHz, giving a 5 kHz Nyquist limit, so the
new 1 kHz band is comfortably within the available PMM bandwidth.  The Welch
segment target remains 16384 samples.

The exact user-supplied transparent Argonne National Laboratory | Advanced
Photon Source PNG is also used as the PDF and plot branding asset.  The alpha
channel is preserved.  PDF and FFT/PSD plot branding is anchored at the
bottom-right footer/corner.

======================================================================
REVISION 19 - SINGLE PDF BRAND MARK + RUNTIME ACCOUNTING
======================================================================

PDF branding
------------
Standalone FFT/PSD/cumulative-ripple PNG plots keep the official transparent
Argonne | Advanced Photon Source mark in their lower-right footer.  When those
plot PNGs are embedded into the PMM PDF, the small plot-level logo is masked in
the PDF copy only.  The PDF page keeps one larger official footer logo at the
bottom-right.  The source PNG plot files are not modified.

Runtime accounting
------------------
`--duration` now means the live polling/plot DATA WINDOW itself.  Connection,
startup PMM acquisition, final PMM acquisition, FFT/PSD analysis, and report
writing no longer consume that configured live duration.

`cdcu_monitor.py` prints:

  - program start time,
  - configured live plot/data duration,
  - live polling start time,
  - actual live polling duration,
  - total runtime for that supply,
  - total program runtime from script start through final report completion,
  - program finish time.

For a single-supply `cdcu_monitor.py` run, "total runtime / supply" and
"program start -> finish" are intentionally the same measurement.  Both are
shown because they have different meanings when the toolkit is launched in a
multi-supply workflow.

`one_liners.py` additionally reports:

  - configured live duration per supply,
  - elapsed subprocess runtime for every launched supply,
  - total batch runtime from `one_liners.py` start through the last completed
    supply.

The live duration can therefore be compared directly with the additional PMM,
analysis, PDF-generation, launch, probe, and shutdown overhead.

======================================================================
REVISION 21 - DIRECT MULTI-IP CDCU MONITORING
======================================================================

cdcu_monitor.py can now run multiple supplies simultaneously while preserving
the complete normal single-supply workflow for every IP.  Each IP runs in its
own independent Python subprocess and therefore retains its own:

  - CDCU TCP socket
  - startup, fault-triggered, and final PMM captures
  - live four-panel plot window (unless --no-plot is used)
  - electrical, efficiency, and temperature monitoring
  - magnet-load characterization
  - fault cascade handling
  - PMM-only FFT / PSD / cumulative-ripple analysis
  - CSV, PNG, PDF, summary, and analysis files
  - per-supply runtime accounting

Run several supplies at once:

  python cdcu_monitor.py \
      --hosts 192.168.5.2 192.168.5.3 192.168.5.4 \
      --cabinet Test_2 \
      --sector B400A \
      --duration 90 \
      --interval 0.0007 \
      --outdir ./cdcu_logs

Comma-separated host input is also accepted:

  python cdcu_monitor.py --hosts 192.168.5.2,192.168.5.3,192.168.5.4 \
      --cabinet Test_2 --sector B400A

By default, one live matplotlib window opens for each monitored supply.  Use
--no-plot only when a headless batch run is desired.

The parent terminal prefixes each child monitor line with its IP address and
also writes a dedicated terminal log for every supply under:

  <outdir>/parallel_logs/

The final parent summary reports the configured live duration, runtime for
each individual supply process, and total program runtime from parallel-launch
start through completion of the last supply.

The existing single-IP syntax is unchanged:

  python cdcu_monitor.py --host 192.168.5.2 --cabinet Test_2 --sector B400A

Do not combine --host and --hosts in the same command.

======================================================================
REVISION 22 - WINDOWS PARALLEL UTF-8 STREAM FIX
======================================================================

The multi-IP launcher now forces each child cdcu_monitor.py process to use
UTF-8 and unbuffered stdout/stderr when its terminal output is redirected to
the parent process.  This prevents Windows cp1252 UnicodeEncodeError failures
on section-divider characters and preserves the complete single-supply
monitoring path for every parallel IP.

The parent process decodes each child stream explicitly as UTF-8 and continues
to mirror the full child terminal output into both the shared console and the
per-IP parallel_logs file.

======================================================================
REVISION 23 UPDATE - CONSOLIDATED MULTI-IP DASHBOARD + DCBUS CHARACTERIZATION
======================================================================

Multi-IP live plotting now defaults to one consolidated dashboard window.
Supplies are arranged two across: 2x1 for 2 supplies, 2x2 for 4, 2x3 for 6,
and 2x4 for 8. Each supply tile retains the four live monitoring groups:
Power, Electrical Values, Efficiency, and CDCU Internal Temperatures. The
individual child processes still execute the complete single-supply workflow
(startup/fault/final PMM, CSV/PNG/PDF outputs, diagnostics, FFT/PSD, magnet
characterization, and runtime reporting); only the visible GUI is consolidated.

Use --individual-plots to restore one live monitor window per supply. Use
--no-plot for headless operation. The final consolidated dashboard is saved as
cdcu_parallel_dashboard_final.png in the selected output root.

The per-run *_magnet_load_summary.txt report now includes a Steady-state DCBus
operating point section. It reports median steady-state MRP voltage, median
steady-state MGPC current, median |MRP x MGPC| input power in W/kW, a
median-V x median-I calculation check, and the number of qualifying samples.
The same >10% rated-current gate used for meaningful magnet resistance
characterization is applied so an idle plateau does not dominate the DCBus
summary.


======================================================================
REVISION 24 UPDATE - EFFICIENCY + SWITCHING-FREQUENCY REFERENCE
======================================================================

The generated *_magnet_load_summary.txt report now includes a dedicated
steady-state converter-efficiency section.  It reports median steady-state
output power, median measured Pout/Pin efficiency, a median-power ratio
cross-check, the selected diagnostic efficiency reference, the CAEN full-load
minimum, and the number of qualifying steady-state efficiency samples.

The same characterization report now records the CAEN manufacturer switching
frequency (100 kHz) and the model-specific equivalent switching frequency:
CDCU-100 = 100 kHz, CDCU-200 = 200 kHz, CDCU-300 = 300 kHz.  These are
manufacturer specifications, not values inferred from PMM data.  The standard
PMM sample rate is 10 kHz (5 kHz Nyquist), so it cannot directly resolve the
100 kHz switching waveform.  Direct verification requires an oscilloscope at
the PWM Logic Board PWM test points or sufficiently wide-bandwidth ripple
measurement.

======================================================================
REVISION 26 — DCBUS SPECTRAL ANALYSIS
======================================================================

The inactive default FFT/PSD analysis of PMM Set Current has been removed from
the normal spectral report. PMM Output Voltage and PMM Output Current remain
hardware-timed 10 kHz spectral channels.

A new module, cdcu_dcbus_fft.py, analyzes synchronized DCBus input voltage and
input current captures using the same FFT/PSD/band/ppm/report pipeline. A valid
DCBus spectral record must contain exactly 100,001 samples at 10 kHz
(100 us/sample) for both channels. Accepted source column aliases include:

  MRP / PS:DCBusVoltM / DCBusVoltM -> dcbus_v_V
  MGPC / PS:DCBusCurrM / DCBusCurrM -> dcbus_i_A

IMPORTANT: the documented CDCU PMM exposes output voltage, output current, and
setpoint current only. The documented embedded oscilloscope also exposes output
set/read values, not DCBus input voltage/current. Therefore normal sequential
MRP/MGPC Ethernet polling is NOT resampled or interpolated into a fictitious
10 kHz FFT record. The DCBus analyzer accepts a hardware-timed capture from an
external DAQ or a future/vendor high-speed CDCU acquisition backend.

Standalone example:

  python cdcu_dcbus_fft.py --csv dcbus_10khz.csv

Single-supply cdcu_monitor integration:

  python cdcu_monitor.py --host 192.168.5.2 --cabinet Test_2 --sector B400A \
      --dcbus-spectrum-csv dcbus_10khz.csv

When the DCBus CSV contains no time_s column, --dcbus-assume-10khz may be used
only when the acquisition hardware is known to have sampled at exactly 10 kHz.
The analyzer otherwise rejects missing, short, or irregular records rather than
producing a misleading FFT/PSD result.


======================================================================
REVISION 27 - EXTERNAL OSCILLOSCOPE CSV ANALYSIS
======================================================================

The toolkit can now analyze one to four hardware-timed oscilloscope channels
from a CSV export using cdcu_scope_fft.py.  Each selected channel receives the
same FFT / Welch PSD / cumulative-RMS spectral processing used by the existing
PMM path plus a time-domain stability summary for the acquired record.

The default target for DCBus work remains a 10 kHz, 100,001-sample record
(10.000 s span), but the generic oscilloscope utility accepts other genuinely
hardware-timed records when the CSV timestamps establish the sample interval or
when --sample-rate is supplied for a scope export with no time column.

IMPORTANT: The stability values describe variation during the acquired scope
record.  They are not replacements for CAEN's 24-hour or 7-day stability
specifications.

Per-channel stability metrics include:
  - mean and median
  - minimum and maximum
  - peak-to-peak variation
  - peak-to-peak stability in ppm and percent
  - standard deviation
  - AC RMS about the record mean and ppm
  - maximum absolute deviation from the mean and ppm
  - linear drift in engineering units/s and ppm/s

The run also writes:
  oscilloscope_stability_summary.txt
  oscilloscope_stability_summary.csv

Example - two-channel DCBus scope CSV with a Time column:

  python cdcu_scope_fft.py --csv dcbus_scope.csv \
      --expected-samples 100001 \
      --channel "CH1,DCBus Input Voltage,V,40" \
      --channel "CH2,DCBus Input Current,A,200"

Example - four scope channels:

  python cdcu_scope_fft.py --csv scope4.csv \
      --channel "CH1,DCBus Input Voltage,V,40" \
      --channel "CH2,DCBus Input Current,A,200" \
      --channel "CH3,Aux Voltage,V" \
      --channel "CH4,Aux Current,A"

If the CSV contains no time column, state the hardware sample rate explicitly:

  python cdcu_scope_fft.py --csv scope.csv --sample-rate 10000 \
      --expected-samples 100001 \
      --channel "CH1,DCBus Input Voltage,V" \
      --channel "CH2,DCBus Input Current,A"

cdcu_dcbus_fft.py remains the strict two-channel convenience path.  It now also
produces the same stability summary while continuing to require the PMM-like
100,001-sample / 10 kHz DCBus record.
