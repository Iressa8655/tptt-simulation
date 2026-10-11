"""Checks reported in the paper's Results ("Model check") and Supplementary Methods.

Writes into this folder
    gait2392_native_subtalar_ma.csv  native subtalar moment arms, -20 to +20 degrees (compared with Klein et al. 1996)
    gait2392_native_ankle_ma.csv     native ankle moment arms, -20 to +20 degrees
    palsy_net_by_insertion.csv       net subtalar moment with common peroneal palsy at every dorsal insertion
    sweep_14_vs_18.csv               dorsiflexion moment arm at 14 and 18 degrees along the insertion line

Usage
    python validation/model_check.py
"""
import math
import os
import sys

import numpy as np
import opensim as osim
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
from transfer_engine import TransferEngine, via_y_from_height  # noqa: E402

osim.Logger.setLevelString("error")
MODEL = os.path.join(REPO, "model", "gait2392_simbody_original.osim")
SWEEP = pd.read_csv(os.path.join(REPO, "results", "static_7cm", "V2_part1_attachment_sweep.csv"))
VIA_Y = via_y_from_height(7.0)
ROUTES = {"IO": -0.020, "CT": 0.028}
MUSCLES = ["tib_post_l", "tib_ant_l", "per_long_l", "per_brev_l", "soleus_l", "med_gas_l", "flex_hal_l"]

# 1. native moment arms
model = osim.Model(MODEL)
state = model.initSystem()
subtalar = model.getCoordinateSet().get("subtalar_angle_l")
ankle = model.getCoordinateSet().get("ankle_angle_l")
for coord, other, name in [(subtalar, ankle, "subtalar"), (ankle, subtalar, "ankle")]:
    rows = []
    for deg in np.arange(-20, 21, 1):
        coord.setValue(state, math.radians(deg))
        other.setValue(state, 0.0)
        model.realizePosition(state)
        rows.append({f"{name}_deg": deg, **{m: model.getMuscles().get(m).computeMomentArm(state, coord) * 1000 for m in MUSCLES}})
    pd.DataFrame(rows).to_csv(os.path.join(HERE, f"gait2392_native_{name}_ma.csv"), index=False)

# 2. net subtalar moment along the insertion line, and the 14 versus 18 degree selection
engine = TransferEngine(MODEL)
palsy, sweep = [], []
for _, row in SWEEP.iterrows():
    engine.set_route(ROUTES[row.route], VIA_Y, insertion=(row.x_mm / 1000, row.y_mm / 1000, row.z_mm / 1000))
    profile = engine.profile([0, 14, 18])
    palsy.append({"route": row.route, "position": row.position, "insertion": row.insertion,
                  "common0": profile[0]["net_subtalar_nm"]["common"], "common14": profile[1]["net_subtalar_nm"]["common"],
                  "deep0": profile[0]["net_subtalar_nm"]["deep"], "deep14": profile[1]["net_subtalar_nm"]["deep"]})
    sweep.append({"route": row.route, "position": row.position, "insertion": row.insertion,
                  "ma14": profile[1]["arm_ankle_mm"], "ma18": profile[2]["arm_ankle_mm"]})
palsy, sweep = pd.DataFrame(palsy), pd.DataFrame(sweep)
palsy.to_csv(os.path.join(HERE, "palsy_net_by_insertion.csv"), index=False)
sweep.to_csv(os.path.join(HERE, "sweep_14_vs_18.csv"), index=False)

for route in ROUTES:
    dorsal = palsy[(palsy.route == route) & (palsy.position >= 1)]
    print(route, "lowest common palsy net moment over dorsal insertions",
          round(min(dorsal.common0.min(), dorsal.common14.min()), 1), "Nm")
    s = sweep[(sweep.route == route) & (sweep.position >= 1)]
    print(route, "best at 14 deg", s.loc[s.ma14.idxmax(), "position"], "best at 18 deg", s.loc[s.ma18.idxmax(), "position"])
