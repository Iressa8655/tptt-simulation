# Tibialis posterior tendon transfer: simulation code and results

Code, models and results for the study **"Window Height, Insertion Site and Route in Tibialis Posterior Tendon Transfer: A Sequential Simulation Study"** (manuscript submitted to *Foot & Ankle International*).

The study treats the transfer as the sequence of decisions a surgeon makes in theatre. It sweeps the window height, then the insertion site for each route (interosseous, IO, and circumtibial, CT), then compares the routes, using the OpenSim Gait2392 model. It then simulates walking with OpenSim Moco to see which muscles take up the swing-phase dorsiflexion load.

An interactive planner built on the same engine is a separate project, at [iressa8655.github.io/tendon-transfer-planner](https://iressa8655.github.io/tendon-transfer-planner/) ([source](https://github.com/Iressa8655/tendon-transfer-planner)).

## What is in each folder

| Folder or file | Contents |
|---|---|
| `transfer_engine.py` | The engine. Rebuilds the tibialis posterior path for a given route, window height and insertion, re-tensions the muscle, and returns moment arms and moments. |
| `model/` | The unmodified Gait2392 model used as the starting point. |
| `static/` | The three study steps as notebook cells (`_part1_cells.py` insertion sweep, `_part2_cells.py` route comparison, `_part3_cells.py` window height), the scripts that build them into notebooks, and the original notebooks in `notebooks/`. |
| `run_static.py` | Runs the three steps without Jupyter at a chosen window height. |
| `peroneal_rescale.py` | Net subtalar moments with the peroneal moment arms scaled to cadaveric values. |
| `results/static_7cm/` | The CSVs and figures reported in the paper, window at 7.0 cm. |
| `models/` | The `.osim` models written by each step. |
| `validation/` | The model check against cadaveric moment arms, the palsy minima and the 14 versus 18 degree reselection (`model_check.py`). |
| `moco/` | The walking simulation. Script, inputs, models, solutions and summary tables. |
| `data/gait_cycle.json` | Ankle angle across the reference gait cycle (Supplementary Figure S1). |
| `platform/insertion_line.py` | The continuous insertion line from the navicular to the base of the fifth metatarsal. |

## Where each result comes from

| In the paper | File | Made by |
|---|---|---|
| Figure 3B, window height | `results/static_7cm/V2_part3_height_at_best.csv` | `run_static.py`, part 3 |
| Figure 4 and Table 2, insertion site | `results/static_7cm/V2_part1_attachment_sweep.csv` | `run_static.py`, part 1 |
| Figure 5 and Table 3, routes and hindfoot | `results/static_7cm/V2_part2_routing_at_best.csv`, `V2_part2_curves.csv` | `run_static.py`, part 2 |
| Table 3, scaled deep palsy column | `results/static_7cm/V2_net_peroneal_rescaled_klein.csv` | `peroneal_rescale.py` |
| Model check and Supplementary Figure S3 | `validation/gait2392_native_subtalar_ma.csv` | `validation/model_check.py` |
| Palsy minima and the 18 degree reselection | `validation/palsy_net_by_insertion.csv`, `sweep_14_vs_18.csv` | `validation/model_check.py` |
| Figures 6 and 7 and Table 4, walking | `moco/summary.csv`, `moco/timeseries_*.csv` | `moco/run_moco_v2.py` |

## How to run it

1. Install OpenSim 4.6 with its Python package ([conda package](https://anaconda.org/opensim-org/opensim)), then `pip install -r requirements.txt`.
2. Static steps, about 20 minutes on a laptop.
   ```
   python run_static.py output --height 7.0 --geometry "C:\OpenSim 4.6\Geometry"
   python peroneal_rescale.py output
   python validation/model_check.py
   ```
   `--geometry` is the `Geometry` folder of the OpenSim install, used to place the lateral cuneiform anchor on the bone.
3. Walking simulation, several minutes per condition.
   ```
   cd moco
   python run_moco_v2.py check
   python run_moco_v2.py intact IO CT
   ```
   On Windows, set `OPENSIM_BIN` to the OpenSim `bin` folder if IPOPT does not load.

Re-running `run_static.py` reproduces every CSV in `results/static_7cm/` exactly (checked with OpenSim 4.6, NumPy 2.5, pandas 3.0).

## Notes

- The notebooks in `static/notebooks/` are the original working notebooks, with commentary in Traditional Chinese, run with the window at 7.5 cm. The paper uses 7.0 cm. Moment values differ by less than 0.1 Nm between the two heights.
- Part 2 also contains a sensitivity analysis of the point where the tendon passes beneath the extensor retinaculum. The paper does not report it, because that point is a simplification of the anatomy and has not been measured.
- All moments are at full activation unless stated, so they describe capacity rather than walking demand.

## Licence and credit

- Code (`*.py`) is under the MIT licence, see `LICENSE`.
- Results, figures and the models written by this study are under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), see `LICENSE-DATA.md`.
- Gait2392 is by Delp, Loan, Hoy, Zajac, Topp, Rosen, Thelen, Anderson and Seth, under [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/). The walking model and data come from the OpenSim Moco `example3DWalking` example (Rajagopal et al. 2016, Lai et al. 2017, Uhlrich et al. 2022). Please credit the original authors when reusing them.

## How to cite

See `CITATION.cff`, or use the citation of the paper once published.
