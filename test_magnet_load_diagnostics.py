#!/usr/bin/env python3
import math
import magnet_load_diagnostics as m

entry={"load_desc":"Magnet: B400A_slot_5; DMM_Q3; Resistance: 0.064 Ohm; Inductance: 16.9 mH"}
np=m.parse_nameplate(entry)
assert abs(np.resistance_ohm-0.064)<1e-12
assert abs(np.inductance_h-0.0169)<1e-12
assert abs(m.measured_resistance(19.2,300)-0.064)<1e-12
assert abs(m.estimate_didt(0,100,0.1,200)-1000)<1e-9
L=m.estimated_inductance(30.0,200.0,1000.0,0.064)
assert abs(L-0.0172)<1e-12
d,pct,ppm=m.deviation(0.066,0.064)
assert abs(d-0.002)<1e-12
assert abs(pct-3.125)<1e-9
assert abs(ppm-31250)<1e-6
v,p=m.extrapolate_at_current(0.064,300)
assert abs(v-19.2)<1e-12 and abs(p-5760)<1e-9
slew=m.max_slew_rate(45,300,0.064,0.0169)
assert abs(slew-1526.6272189349114)<1e-6
print('magnet_load_diagnostics tests: PASS')
