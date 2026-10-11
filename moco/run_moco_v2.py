"""Re-run of the walking simulation (MocoInverse) on the V2 transfer configurations.

Conditions: intact, IO (pos 2.75, 7.0 cm window), CT (medial cuneiform, 7.0 cm window).
Model: OpenSim example3DWalking subject_walk_scaled.osim (80 muscles, subtalar welded).
Settings follow exampleMocoInverse.py (0.48 to 1.61 s, mesh 0.02 s, DeGrooteFregly, rigid tendon,
reserves 1.0), except tibialis posterior (and tibialis anterior in the intact model) keep their
geometric paths so the transferred route is actually simulated.

Usage:  python run_moco_v2.py check          (re-tension + moment arm check, seconds)
        python run_moco_v2.py intact IO CT   (full solves, several minutes each)
"""
import os, sys, math, csv
HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
# The pip opensim package cannot load the IPOPT plugin by itself (WIN32 error 126), so point
# CasADi and the DLL loader at the OpenSim 4.6 install, which ships casadi_nlpsol_ipopt.dll and its dependencies.
OSIM_BIN = os.environ.get("OPENSIM_BIN", r"C:\OpenSim 4.6\bin")
if os.path.isdir(OSIM_BIN):
    os.environ["PATH"] = OSIM_BIN + os.pathsep + os.environ.get("PATH", "")
    os.environ["CASADIPATH"] = OSIM_BIN
    if hasattr(os, "add_dll_directory"): os.add_dll_directory(OSIM_BIN)
import opensim as osim
T0, T1, MESH = 0.48, 1.61, 0.02
ANKLE = "/jointset/ankle_l/ankle_angle_l"
MUSCLES = ["tibpost_l", "tibant_l", "edl_l", "ehl_l", "perlong_l", "perbrev_l",
           "soleus_l", "gasmed_l", "gaslat_l", "fdl_l", "fhl_l"]
FBP = {"intact": "fbp_intact.xml", "IO": "fbp_transfer.xml", "CT": "fbp_transfer.xml"}

def log(*a):
    print(*a, flush=True)
    with open(os.path.join(HERE, "run_log.txt"), "a") as f: print(*a, file=f)

def tensioned_model(cond):
    """Load the condition model; for transfers, reset tendon slack length so the fibres sit at
    optimal length with the ankle at neutral: L_ts = L_mt - L_of * cos(alpha)."""
    out = f"model_{cond}_tensioned.osim"
    m = osim.Model(f"model_{cond}.osim"); s = m.initSystem()
    for c in ["ankle_angle_l", "knee_angle_l"]:
        m.updCoordinateSet().get(c).setValue(s, 0.0)
    m.realizePosition(s)
    tp = osim.Millard2012EquilibriumMuscle.safeDownCast(m.updMuscles().get("tibpost_l"))
    lmt = tp.getLength(s)
    if cond != "intact":
        lts = lmt - tp.getOptimalFiberLength() * math.cos(tp.getPennationAngleAtOptimalFiberLength())
        log(f"[{cond}] L_mt at neutral {lmt*1000:.2f} mm, tendon slack {tp.getTendonSlackLength()*1000:.2f} -> {lts*1000:.2f} mm")
        tp.setTendonSlackLength(lts)
    else:
        log(f"[{cond}] L_mt at neutral {lmt*1000:.2f} mm, tendon slack unchanged {tp.getTendonSlackLength()*1000:.2f} mm")
    m.printToXML(out)
    return out

def moment_arm_check(path, cond):
    m = osim.Model(path); s = m.initSystem()
    ank = m.getCoordinateSet().get("ankle_angle_l")
    for deg in (-20, 0, 14, 20):
        ank.setValue(s, math.radians(deg)); m.realizePosition(s)
        ma = m.getMuscles().get("tibpost_l").computeMomentArm(s, ank)
        log(f"[{cond}] tibpost_l ankle moment arm at {deg:+d} deg: {ma*1000:+.2f} mm (+ = dorsiflexion)")

def swing_window():
    """First swing of the left foot after T0: contiguous run of left vertical GRF below 20 N."""
    t = osim.TimeSeriesTable("grf_walk.mot"); times = list(t.getIndependentColumn())
    fy = t.getDependentColumn("ground_force_l_vy").to_numpy()
    sw = []
    for ti, f in zip(times, fy):
        if ti < T0 - 1e-9 or ti > T1: continue
        if f < 20.0: sw.append(ti)
        elif sw: break
    return min(sw), max(sw)

def processor(cond, model_path):
    mp = osim.ModelProcessor(model_path)
    mp.append(osim.ModOpAddExternalLoads("grf_walk.xml"))
    weld = osim.StdVectorString(); weld.append("mtp_r"); weld.append("mtp_l")
    mp.append(osim.ModOpReplaceJointsWithWelds(weld))
    mp.append(osim.ModOpAddResiduals(250.0, 50.0, 1.0))
    mp.append(osim.ModOpIgnoreTendonCompliance())
    mp.append(osim.ModOpReplaceMusclesWithDeGrooteFregly2016())
    mp.append(osim.ModOpIgnorePassiveFiberForcesDGF())
    mp.append(osim.ModOpScaleActiveFiberForceCurveWidthDGF(1.5))
    mp.append(osim.ModOpReplacePathsWithFunctionBasedPaths(FBP[cond]))
    mp.append(osim.ModOpAddReserves(1.0))
    return mp

def solve(cond, model_path):
    out = f"solution_{cond}.sto"
    if os.path.exists(out):
        log(f"[{cond}] reusing existing {out}")
        return osim.MocoTrajectory(out)
    inv = osim.MocoInverse(); inv.setName(f"v2_{cond}")
    inv.setModel(processor(cond, model_path))
    inv.setKinematics(osim.TableProcessor("coordinates.sto"))
    inv.set_initial_time(T0); inv.set_final_time(T1); inv.set_mesh_interval(MESH)
    inv.set_kinematics_allow_extra_columns(True)
    res = inv.solve()  # keep a reference: getMocoSolution() on a temporary segfaults
    sol = res.getMocoSolution()
    if sol.isSealed(): sol.unseal()
    sol.write(out)
    log(f"[{cond}] solved, success={sol.success()}, objective={sol.getObjective():.4f}")
    # The solution belongs to `res`, which is freed on return, so hand back a copy read from file.
    return osim.MocoTrajectory(out)

def post(cond, model_path, sol, sw0, sw1):
    """Rebuild each time point in the processed (DeGrooteFregly, rigid tendon) model: prescribed
    kinematics from a GCV spline of coordinates.sto (values and speeds) plus solved activations,
    then read tendon force and ankle moment arm for each muscle."""
    model = processor(cond, model_path).process()
    s = model.initSystem()
    sto = osim.Storage("coordinates.sto"); spl = osim.GCVSplineSet(5, sto)
    labels = [sto.getColumnLabels().get(k) for k in range(1, sto.getColumnLabels().getSize())]
    cs = model.getCoordinateSet()
    coords = []
    for lab in labels:
        name = lab.split("/")[-2]
        if cs.contains(name): coords.append((cs.get(name), spl.get(lab)))
    def vec(v):
        if hasattr(v, "to_numpy"): return [float(z) for z in v.to_numpy()]
        try: return [float(v[k]) for k in range(v.size())]
        except Exception: return [float(v.getElt(0, k)) for k in range(v.size())]
    times = vec(sol.getTime())
    actnames = [n for n in sol.getStateNames() if n.endswith("/activation")]
    acts = {n: vec(sol.getState(n)) for n in actnames}
    ank = cs.get("ankle_angle_l")
    present = [mu for mu in MUSCLES if model.getMuscles().contains(mu)]
    d1 = osim.StdVectorInt(); d1.append(0)
    rows = []
    for i, t in enumerate(times):
        s.setTime(t); x = osim.Vector(1, t)
        for c, f in coords:
            c.setValue(s, f.calcValue(x), False); c.setSpeedValue(s, f.calcDerivative(d1, x))
        for n in actnames:
            model.setStateVariableValue(s, n, acts[n][i])
        model.realizeDynamics(s)
        row = {"time": t, "ankle_deg": math.degrees(ank.getValue(s)),
               "act_tibpost": acts.get("/forceset/tibpost_l/activation", [float("nan")] * len(times))[i]}
        for mu in present:
            m = model.getMuscles().get(mu)
            F = m.getTendonForce(s); r = m.computeMomentArm(s, ank)
            row[f"F_{mu}"] = F; row[f"r_{mu}_mm"] = r * 1000; row[f"M_{mu}"] = F * r
        rows.append(row)
    with open(f"timeseries_{cond}.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    swing = [r for r in rows if sw0 <= r["time"] <= sw1]
    summ = []
    for mu in present:
        summ.append({"condition": cond, "muscle": mu,
                     "peak_swing_force_N": round(max(r[f"F_{mu}"] for r in swing), 2),
                     "peak_stride_force_N": round(max(r[f"F_{mu}"] for r in rows), 2),
                     "mean_swing_ankle_moment_Nm": round(sum(r[f"M_{mu}"] for r in swing) / len(swing), 3),
                     "peak_swing_ankle_moment_Nm": round(max(r[f"M_{mu}"] for r in swing), 3),
                     "peak_swing_activation": round(max(acts[f"/forceset/{mu}/activation"][times.index(r["time"])] for r in swing), 3),
                     "moment_arm_min_mm": round(min(r[f"r_{mu}_mm"] for r in rows), 2),
                     "moment_arm_max_mm": round(max(r[f"r_{mu}_mm"] for r in rows), 2)})
    newf = not os.path.exists("summary.csv")
    with open("summary.csv", "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summ[0].keys()))
        if newf: w.writeheader()
        w.writerows(summ)
    for r in summ: log(r)

if __name__ == "__main__":
    args = sys.argv[1:] or ["check"]
    log("=== run", args, "opensim", osim.GetVersionAndDate())
    sw0, sw1 = swing_window(); log(f"swing {sw0:.3f} to {sw1:.3f} s")
    conds = ["intact", "IO", "CT"] if args == ["check"] else args
    for c in conds:
        p = tensioned_model(c); moment_arm_check(p, c)
        if args != ["check"]:
            sol = solve(c, p); post(c, p, sol, sw0, sw1)
    log("=== done")
