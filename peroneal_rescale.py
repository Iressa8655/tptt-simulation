"""Net subtalar moments with the peroneus longus and brevis moment arms scaled to cadaveric values.

Gait2392 overestimates the peroneal subtalar moment arms (Klein et al. 1996), so their
contributions are multiplied by cadaveric / model mean moment arm (-20 to +20 degrees).

Usage
    python peroneal_rescale.py [RESULTS_DIR]

RESULTS_DIR holds V2_part1_attachment_sweep.csv and receives
V2_net_peroneal_rescaled_klein.csv (default results/static_7cm).
"""
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from transfer_engine import PALSY_LEVELS, TransferEngine, via_y_from_height  # noqa: E402

RESULTS = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(HERE, "results", "static_7cm")
KLEIN = {"per_long_l": 21.8 / 27.2, "per_brev_l": 20.5 / 28.4}
engine = TransferEngine(os.path.join(HERE, "model", "gait2392_simbody_original.osim"))
VIA_Y = via_y_from_height(7.0)
ROUTES = {"IO": -0.020, "CT": 0.028}
part1 = pd.read_csv(os.path.join(RESULTS, "V2_part1_attachment_sweep.csv"))


def xyz(route, pos):
    row = part1[(part1.route == route) & (part1.position == pos)].iloc[0]
    return (row.x_mm / 1000, row.y_mm / 1000, row.z_mm / 1000)


# set A, each route at its own best insertion; set B, IO at the medial cuneiform
CONF = {"A_IO": ("IO", 2.75), "A_CT": ("CT", 1.0), "B_IO": ("IO", 1.0)}
rows = []
for name, (route, pos) in CONF.items():
    engine.set_route(ROUTES[route], VIA_Y, insertion=xyz(route, pos))
    for angle in (0.0, 14.0):
        engine._pose(angle, 0.0, activate=True)
        state = engine.state
        donor = engine.donor.computeMomentArm(state, engine.subtalar) * engine.donor.getActuation(state)
        parts = {n: engine.muscles.get(n).computeMomentArm(state, engine.subtalar) * engine.muscles.get(n).getActuation(state)
                 for n in engine.subtalar_contributors}
        out = dict(config=name, angle=angle, donor=donor)
        for level, removed in PALSY_LEVELS.items():
            kept = {n: v for n, v in parts.items() if n not in removed}
            out[f"net_{level}"] = donor + sum(kept.values())
            out[f"net_{level}_klein"] = donor + sum(v * KLEIN.get(n, 1.0) for n, v in kept.items())
        out["peronei"] = parts["per_long_l"] + parts["per_brev_l"]
        rows.append(out)
table = pd.DataFrame(rows)
table.to_csv(os.path.join(RESULTS, "V2_net_peroneal_rescaled_klein.csv"), index=False, float_format="%.4f")
print(table.round(2).to_string(index=False))
