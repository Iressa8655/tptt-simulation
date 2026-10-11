"""Re-run the static steps of the study (window height, insertion sweep and route comparison).

Usage
    python run_static.py OUTPUT_DIR [--height 7.0] [--parts 1,2,3] [--geometry PATH]

The three step scripts in static/ are the cells of the original notebooks. This runner
executes their code cells without Jupyter, writes CSVs, figures and models into OUTPUT_DIR,
and uses the window height given (7.0 cm in the paper). --geometry points at the Geometry
folder of an OpenSim 4.6 install, which part 1 needs to place the lateral cuneiform anchor
on the bone surface. It can also be set with the OPENSIM_GEOMETRY environment variable.
"""
import argparse
import importlib.util
import os
import shutil

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

plt.show = lambda *a, **k: plt.close("all")

HERE = os.path.dirname(os.path.abspath(__file__))

parser = argparse.ArgumentParser()
parser.add_argument("output")
parser.add_argument("--height", type=float, default=7.0, help="window height above the medial malleolus, cm")
parser.add_argument("--parts", default="1,2,3")
parser.add_argument("--geometry", default=os.environ.get("OPENSIM_GEOMETRY", r"C:\OpenSim 4.6\Geometry"))
args = parser.parse_args()
root = os.path.abspath(args.output)

for folder in ["model", "data", "platform", "figures", "models/part1", "models/part2", "models/part3"]:
    os.makedirs(os.path.join(root, folder), exist_ok=True)
shutil.copy(os.path.join(HERE, "transfer_engine.py"), root)
shutil.copy(os.path.join(HERE, "model", "gait2392_simbody_original.osim"), os.path.join(root, "model"))
shutil.copy(os.path.join(HERE, "data", "gait_cycle.json"), os.path.join(root, "data"))
shutil.copy(os.path.join(HERE, "platform", "insertion_line.py"), os.path.join(root, "platform"))
# parts 2 and 3 read the part 1 sweep, so a later part can start from the published one
published = os.path.join(HERE, "results", "static_7cm", "V2_part1_attachment_sweep.csv")
if "1" not in args.parts.split(",") and not os.path.exists(os.path.join(root, "V2_part1_attachment_sweep.csv")):
    shutil.copy(published, root)


def cells(part):
    spec = importlib.util.spec_from_file_location(f"part{part}", os.path.join(HERE, "static", f"_part{part}_cells.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.CELLS


for part in args.parts.split(","):
    namespace = {"__name__": f"part{part}"}
    for kind, key, text in cells(part):
        if kind != "code":
            continue
        text = text.replace(r'r"D:\OpenSim 4.6\Tendon transfer model\V2"', repr(root))
        text = text.replace(r'r"D:\OpenSim 4.6\Geometry"', repr(args.geometry))
        text = text.replace("HEIGHT_CM = 7.5", f"HEIGHT_CM = {args.height}")
        text = text.replace("via_y_from_height(7.5)", f"via_y_from_height({args.height})")
        try:
            exec(compile(text, f"part{part}:{key}", "exec"), namespace)
        except Exception as error:  # a figure cell failing should not stop the numbers
            print(f"!! part {part}, cell {key}: {type(error).__name__}: {error}")
    print(f"== part {part} done")
