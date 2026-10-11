"""肌腱轉位手術規劃引擎。

⭐ 平台的第一層。網頁版與批次腳本都呼叫這裡，數字只有一個來源。

三個手術軸
    via_z        中段路徑點的內外側位置，公尺。⚠️ 左腳的 +z 是內側：
                 負值在外側、穿過骨間膜（IO，-20 mm），
                 正值在內側、繞過脛骨內緣（CT，+28 mm）。
                 驗證：內側楔狀骨 z +30.5 mm，第五蹠骨基底 z -34.3 mm。
    via_y        中段路徑點的高度，公尺，tibia_l 座標系（原點在膝關節）。
                 介面上改用「內踝尖以上公分」，換算見 via_y_from_height()。
    insertion    止點，INSERTION_INFO 裡的鍵。

⛔⛔ 最重要的一件事：retension()
    路徑一改，肌腱單元總長就變了。肌腱鬆弛長度沒跟著調，
    肌肉會停在力─長度曲線的死區，算出來的力矩是 0 N·m。
    set_route() 每次都會自動呼叫它，不給關。

驗證基準（見 test_engine.py）
    IO 中立位　總槓桿 ‖M‖ 36.2 mm、距下力臂 −9.25 mm、背屈佔比 62%
    CT 中立位　總槓桿 ‖M‖ 24.9 mm、距下力臂 +8.50 mm、背屈佔比 84%
"""

import io
import math
import os
import re

import opensim as osim

DEG = math.pi / 180.0

DONOR = "tib_post_l"
SOLEUS = "soleus_l"
PERONEALS = ["per_long_l", "per_brev_l"]

# 深腓神經支配的四條，腓總神經再多兩條腓骨肌
DEEP_PERONEAL = ["tib_ant_l", "ext_dig_l", "ext_hal_l", "per_tert_l"]
SUPERFICIAL_PERONEAL = ["per_long_l", "per_brev_l"]
PALSY_LEVELS = {
    "none": [],
    "deep": DEEP_PERONEAL,
    "common": DEEP_PERONEAL + SUPERFICIAL_PERONEAL,
}

# 肌肉的起點不動，維持原本的脛骨後方
ORIGIN = (-0.0094, -0.1348, -0.0019)

# 下段轉折點。支持帶把肌腱束在踝前方，所以它跟著中段點走但幅度較小。
# 它的高度 -0.4150 和內踝尖只差 0.3 mm，可以讀成「內踝尖高度的支持帶」。
LOWER_POINT_Y = -0.4150
LOWER_POINT_X = 0.0300

# ⚠️ 兩條已發表路徑的下段點是各自手擺的，不是同一個比例：
#       IO  中段 z=-0.0200 → 下段 z=-0.0050
#       CT  中段 z=+0.0280 → 下段 z=+0.0120
#   所以用這兩個錨點做線性內插，中間的路徑才會平滑過渡。
LOWER_Z_SLOPE = 0.354167
LOWER_Z_OFFSET = 0.00208333

ANKLE_CENTRE_Y = -0.43

# 內踝尖在 tibia_l 座標系的高度，從 tibia_l.vtp 最遠端的頂點量出來。
# ⚠️ 那個網格只有 145 個頂點，這是估計值，誤差可能有幾毫米。
MEDIAL_MALLEOLUS_TIP_Y = -0.4153
TIBIA_LENGTH_M = 0.43

# 目前研究用的止點，介於 ext_hal_l-P3 與 ext_dig_l-P3 之間的內插點
INTERMEDIATE_CUNEIFORM = (0.0946, 0.0389, 0.0106)

INSERTION_ORDER = [
    "navicular",
    "medial_cuneiform",
    "intermediate_cuneiform",
    "lateral_cuneiform",
    "cuboid",
    "base_5th_metatarsal",
]

# 每個止點的座標優先從模型裡對應的路徑點讀，讀不到才用 fallback
INSERTION_INFO = {
    "navicular": {
        "label": "Navicular",
        "kind": "control",
        "source": ("tib_post_l", "tib_post_l-P3"),
        "fallback": (0.0417, 0.0334, 0.0286),
        "note": "Native tibialis posterior insertion. "
                "Shown for comparison only.",
    },
    "medial_cuneiform": {
        "label": "Medial cuneiform",
        "kind": "true",
        "source": ("tib_ant_l", "tib_ant_l-P3"),
        "fallback": (0.1166, 0.0178, 0.0305),
        "note": "Tibialis anterior insertion in the model.",
    },
    "intermediate_cuneiform": {
        "label": "Intermediate cuneiform",
        "kind": "interpolated",
        "source": None,
        "fallback": INTERMEDIATE_CUNEIFORM,
        "note": "The insertion used in the routing study.",
    },
    "lateral_cuneiform": {
        "label": "Lateral cuneiform",
        "kind": "proxy",
        "source": ("ext_dig_l", "ext_dig_l-P3"),
        "fallback": (0.0922, 0.0388, 0.0001),
        "note": "Proxy: an extensor digitorum via point, not an insertion. "
                "Position is approximate.",
    },
    "cuboid": {
        "label": "Cuboid",
        "kind": "proxy",
        "source": ("per_long_l", "per_long_l-P5"),
        "fallback": (0.0681, 0.0106, -0.0284),
        "note": "Proxy: a peroneus longus via point near the cuboid groove.",
    },
    "base_5th_metatarsal": {
        "label": "Base of 5th metatarsal",
        "kind": "true",
        "source": ("per_brev_l", "per_brev_l-P5"),
        "fallback": (0.0677, 0.0219, -0.0343),
        "note": "Peroneus brevis insertion in the model.",
    },
}

# 舊的寫法只有座標，保留給既有腳本用
INSERTIONS = {key: info["fallback"] for key, info in INSERTION_INFO.items()}
INSERTIONS["cuneiform_2"] = INTERMEDIATE_CUNEIFORM

# 兩條已發表路徑的中段點，當作介面的預設與對照
PRESETS = {
    "IO": {"via_z": -0.0200, "via_y": -0.34},
    "CT": {"via_z": 0.0280, "via_y": -0.34},
}

# 超出就標警告，不擋。高度下限 7 cm，12 cm 以上很難取腱（來源見 vault 的 H1 頁）。
LIMITS = {
    "via_z": (-0.0350, 0.0400),
    "height_cm": (7.0, 12.0),
}

# 網頁三維要畫的骨頭與肌肉
VIEW_BODIES = ["femur_l", "tibia_l", "talus_l", "calcn_l", "toes_l"]
VIEW_MUSCLES = ["tib_post_l", "tib_ant_l", "per_long_l", "per_brev_l"]


def via_y_from_height(height_cm):
    """內踝尖以上幾公分，換成模型的 via_y。"""
    return MEDIAL_MALLEOLUS_TIP_Y + height_cm / 100.0


def height_from_via_y(via_y):
    """模型的 via_y，換成內踝尖以上幾公分。"""
    return (via_y - MEDIAL_MALLEOLUS_TIP_Y) * 100.0


def lower_z_default(via_z):
    """支持帶點跟著中段點走時的內外側座標，公尺。"""
    return LOWER_Z_SLOPE * via_z + LOWER_Z_OFFSET


def read_ascii_vtp(path):
    """讀 ascii 格式的 .vtp，回傳頂點座標與三角面索引。

    :param path: .vtp 檔路徑
    :type path: str
    :return: (平攤的頂點座標串列, 平攤的三角面索引串列)
    :rtype: tuple
    """
    text = io.open(path, encoding="utf-8", errors="replace").read()

    points_block = re.search(
        r"<Points>\s*<DataArray[^>]*>(.*?)</DataArray>", text, re.S
    )
    polys_block = re.search(r"<Polys>(.*?)</Polys>", text, re.S)
    if not points_block or not polys_block:
        raise ValueError("no ascii Points or Polys block")

    connectivity_block = re.search(
        r'Name="connectivity"[^>]*>(.*?)</DataArray>',
        polys_block.group(1),
        re.S,
    )
    offsets_block = re.search(
        r'Name="offsets"[^>]*>(.*?)</DataArray>',
        polys_block.group(1),
        re.S,
    )
    if not connectivity_block or not offsets_block:
        raise ValueError("Polys block has no connectivity or offsets")

    positions = [float(v) for v in points_block.group(1).split()]
    connectivity = [int(v) for v in connectivity_block.group(1).split()]
    offsets = [int(v) for v in offsets_block.group(1).split()]

    # 多邊形用扇形切成三角形
    indices = []
    start = 0
    for end in offsets:
        polygon = connectivity[start:end]
        for k in range(1, len(polygon) - 1):
            indices.extend([polygon[0], polygon[k], polygon[k + 1]])
        start = end
    return positions, indices


class TransferEngine:
    """載入一次模型，之後反覆改路徑、反覆算。"""

    def __init__(self, model_path):
        """:param model_path: 原始未轉位的 .osim 檔"""
        self.model_path = model_path
        self.model = osim.Model(model_path)
        self.state = self.model.initSystem()

        self.muscles = self.model.getMuscles()
        self.donor = self.muscles.get(DONOR)
        self.ankle = self.model.getCoordinateSet().get("ankle_angle_l")
        self.subtalar = self.model.getCoordinateSet().get("subtalar_angle_l")

        # 原始最大等長力，做麻痺模擬時要能還原
        self.original_force = {}
        for index in range(self.muscles.getSize()):
            muscle = self.muscles.get(index)
            self.original_force[muscle.getName()] = (
                muscle.getMaxIsometricForce()
            )

        self.axes = {
            "ankle": self._read_axis("ankle_l", "ankle_angle_l"),
            "subtalar": self._read_axis("subtalar_l", "subtalar_angle_l"),
        }

        # ⚠️ 一定要在任何 set_route() 之前讀，因為 set_route 會改掉脛後肌的點
        self.insertions = self._read_insertions()
        self.subtalar_contributors = self._find_subtalar_contributors()
        self.waypoints = []

    # ── 讀模型 ────────────────────────────────────────────────

    def _read_axis(self, joint_name, coordinate_name):
        """讀出這個關節的旋轉軸單位向量。"""
        joint = osim.CustomJoint.safeDownCast(
            self.model.getJointSet().get(joint_name)
        )
        transform = joint.getSpatialTransform()

        for index in range(3):
            axis = transform.getTransformAxis(index)

            # ⚠️ 回傳的是 PropertyStringList，只有 getValue(i)
            raw_names = axis.getCoordinateNames()
            names = []
            position = 0
            while True:
                try:
                    names.append(raw_names.getValue(position))
                    position += 1
                except Exception:
                    break

            if coordinate_name in names:
                vector = axis.getAxis()
                raw = [vector.get(0), vector.get(1), vector.get(2)]
                norm = math.sqrt(sum(v * v for v in raw))
                return [v / norm for v in raw]
        raise ValueError("axis not found for " + coordinate_name)

    def _read_insertions(self):
        """每個止點優先讀模型裡對應路徑點的座標。"""
        insertions = {}
        for key in INSERTION_ORDER:
            info = INSERTION_INFO[key]
            xyz = info["fallback"]

            if info["source"]:
                muscle_name, point_name = info["source"]
                points = (
                    self.muscles.get(muscle_name)
                    .getGeometryPath()
                    .getPathPointSet()
                )
                for index in range(points.getSize()):
                    point = osim.PathPoint.safeDownCast(points.get(index))
                    if point is None or point.getName() != point_name:
                        continue
                    # 只接受附著在跟骨上的點，否則代表模型已經被改過
                    if point.getParentFrame().getName() == "calcn_l":
                        location = point.getLocation(self.state)
                        xyz = (
                            location.get(0),
                            location.get(1),
                            location.get(2),
                        )

            insertions[key] = {
                "label": info["label"],
                "kind": info["kind"],
                "note": info["note"],
                "xyz": xyz,
            }
        return insertions

    def _find_subtalar_contributors(self):
        """找出除了捐贈肌以外，所有跨過左距下關節的肌肉。"""
        self._pose(0.0, 0.0)
        names = []
        for index in range(self.muscles.getSize()):
            muscle = self.muscles.get(index)
            name = muscle.getName()
            if name == DONOR or not name.endswith("_l"):
                continue
            arm = muscle.computeMomentArm(self.state, self.subtalar)
            if abs(arm) > 1e-4:
                names.append(name)
        return names

    # ── 改路徑 ────────────────────────────────────────────────

    def _insertion_xyz(self, insertion):
        """止點可以給鍵，也可以直接給一組座標。"""
        if not isinstance(insertion, str):
            return tuple(insertion)
        if insertion in self.insertions:
            return self.insertions[insertion]["xyz"]
        if insertion == "cuneiform_2":
            return INTERMEDIATE_CUNEIFORM
        raise KeyError("unknown insertion: " + insertion)

    def set_route(self, via_z, via_y, insertion="intermediate_cuneiform",
                  lower_z=None):
        """把捐贈肌整條路徑換掉，然後自動重調張力。

        :param via_z: 中段點的內外側座標，公尺。左腳 +z 是內側，負值是外側的骨間膜。
        :type via_z: float
        :param via_y: 中段點的高度座標，公尺。
        :type via_y: float
        :param insertion: 止點的鍵，或直接給一組 (x, y, z)
        :param lower_z: 支持帶點的內外側座標，公尺。None 代表跟著中段點走。
        :type lower_z: float or None
        :return: 這次設定產生的警告清單
        :rtype: list
        """
        target = self._insertion_xyz(insertion)

        # ⭐ A1 發現這一點決定後足力矩的方向，所以讓它可以單獨指定
        if lower_z is None:
            lower_z = lower_z_default(via_z)
        self.lower_z = lower_z

        waypoints = [
            ("tibia_l", ORIGIN),
            ("tibia_l", (0.0050, via_y, via_z)),
            ("tibia_l", (LOWER_POINT_X, LOWER_POINT_Y, lower_z)),
            ("calcn_l", target),
        ]
        self.waypoints = waypoints

        # ⭐ 原始的 tib_post_l 剛好也是 4 個點，所以直接改現有的點。
        # ⛔ 自己 new 一個 PathPoint 或先清空再 append，都會留下
        #   沒有 owner 的 Component，finalizeConnections 就會炸。
        points = self.donor.getGeometryPath().updPathPointSet()
        bodies = self.model.getBodySet()
        for index, (body_name, location) in enumerate(waypoints):
            point = osim.PathPoint.safeDownCast(points.get(index))
            point.setParentFrame(bodies.get(body_name))
            point.setLocation(osim.Vec3(*location))

        self.model.finalizeConnections()
        self.state = self.model.initSystem()

        self.retension()
        return self._check_limits(via_z, via_y)

    def retension(self):
        """把肌腱鬆弛長度調到「中立位時肌纖維剛好在最佳長度」。

        ⛔⛔⛔ 少了這一步，算出來的力矩會是 0。

        公式　L_ts ＝ L_mt − L_of × cos(羽狀角)
        已驗證：IO 推出 0.2819、CT 推出 0.2840，和手調的值差 0.05 mm。
        """
        self._pose(0.0, 0.0)

        length_mt = self.donor.getGeometryPath().getLength(self.state)
        fibre = self.donor.getOptimalFiberLength()
        pennation = self.donor.getPennationAngleAtOptimalFiberLength()

        self.donor.setTendonSlackLength(
            length_mt - fibre * math.cos(pennation)
        )
        self.state = self.model.initSystem()

    def _check_limits(self, via_z, via_y):
        """超出合理範圍就回警告，但不擋。訊息是給外科醫師看的，所以用英文。"""
        warnings = []

        low, high = LIMITS["via_z"]
        if not low <= via_z <= high:
            warnings.append(
                "Mid-leg via point %.0f mm is outside the %.0f to %.0f mm "
                "range." % (via_z * 1000, low * 1000, high * 1000)
            )

        height = height_from_via_y(via_y)
        low, high = LIMITS["height_cm"]
        if height > high:
            warnings.append(
                "Window %.1f cm above the malleolus tip. Harvesting "
                "tendon above 12 cm is difficult." % height
            )
        if height < low:
            warnings.append(
                "Window %.1f cm above the malleolus tip is below the "
                "7 cm target, so the tendon may bend sharply." % height
            )

        if via_y <= LOWER_POINT_Y + 0.005:
            warnings.append(
                "The window is at or below the retinaculum point, so the "
                "path folds back on itself."
            )
        return warnings

    # ── 擺姿勢 ────────────────────────────────────────────────

    def _pose(self, ankle_deg, subtalar_deg, activate=False):
        """把模型擺到指定姿勢。activate 為真時所有肌肉全力收縮。"""
        self.ankle.setValue(self.state, ankle_deg * DEG, False)
        self.subtalar.setValue(self.state, subtalar_deg * DEG, False)
        self.model.assemble(self.state)

        if activate:
            # ⚠️ assemble 會重新投影 state，活化度每次都要重設
            for index in range(self.muscles.getSize()):
                self.muscles.get(index).setActivation(self.state, 1.0)
            self.model.equilibrateMuscles(self.state)

    # ── 算 ────────────────────────────────────────────────────

    def sweep_ankle(self, angles_deg, subtalar_deg=0.0):
        """掃踝角度，回傳捐贈肌的力臂與力矩。"""
        rows = []
        for angle in angles_deg:
            self._pose(angle, subtalar_deg, activate=True)

            arm_ankle = self.donor.computeMomentArm(self.state, self.ankle)
            arm_subtalar = self.donor.computeMomentArm(
                self.state, self.subtalar
            )
            force = self.donor.getActuation(self.state)

            rows.append({
                "angle": angle,
                "arm_ankle_mm": arm_ankle * 1000,
                "arm_subtalar_mm": arm_subtalar * 1000,
                "force_n": force,
                "moment_ankle_nm": arm_ankle * force,
                "moment_subtalar_nm": arm_subtalar * force,
            })
        return rows

    def profile(self, angles_deg):
        """一次掃完踝角度：捐贈肌的力矩，加上三種麻痺情境的淨後足力矩。

        ⭐ 淨值 ＝ 捐贈肌 ＋ 其他所有跨過距下關節、且神經還在的肌肉，全部全力收縮。
        ⚠️ 被麻痺的肌肉不必真的把力設成零，直接不加進總和就好，
           這樣三種情境一次就算完，不用重新 initSystem。
        """
        rows = []
        for angle in angles_deg:
            self._pose(angle, 0.0, activate=True)

            arm_ankle = self.donor.computeMomentArm(self.state, self.ankle)
            arm_subtalar = self.donor.computeMomentArm(
                self.state, self.subtalar
            )
            force = self.donor.getActuation(self.state)
            donor_subtalar = arm_subtalar * force

            others = {}
            for name in self.subtalar_contributors:
                muscle = self.muscles.get(name)
                others[name] = (
                    muscle.computeMomentArm(self.state, self.subtalar)
                    * muscle.getActuation(self.state)
                )

            net = {}
            for level, removed in PALSY_LEVELS.items():
                kept = [
                    value for name, value in others.items()
                    if name not in removed
                ]
                net[level] = donor_subtalar + sum(kept)

            rows.append({
                "angle": angle,
                "arm_ankle_mm": arm_ankle * 1000,
                "arm_subtalar_mm": arm_subtalar * 1000,
                "force_n": force,
                "moment_ankle_nm": arm_ankle * force,
                "moment_subtalar_nm": donor_subtalar,
                "net_subtalar_nm": net,
            })
        return rows

    def decompose(self, ankle_deg=0.0, subtalar_deg=0.0):
        """把兩個關節的力臂合成一個三維向量，再拆成三個臨床方向。

        ⚠️ 符號約定（已用脛前肌與腓骨肌驗證）
            內翻 ＝ −M[0]　　內收 ＝ −M[1]　　背屈 ＝ M · n̂踝
        """
        self._pose(ankle_deg, subtalar_deg)

        arm_ankle = self.donor.computeMomentArm(self.state, self.ankle) * 1000
        arm_subtalar = (
            self.donor.computeMomentArm(self.state, self.subtalar) * 1000
        )

        vector = [
            arm_ankle * self.axes["ankle"][i]
            + arm_subtalar * self.axes["subtalar"][i]
            for i in range(3)
        ]
        total = math.sqrt(sum(v * v for v in vector))

        dorsi = sum(vector[i] * self.axes["ankle"][i] for i in range(3))
        inversion = -vector[0]
        adduction = -vector[1]

        # ⚠️ 百分比用三個分量的絕對值總和當分母，和 notebook 一致
        share = abs(dorsi) + abs(inversion) + abs(adduction)
        if share == 0:
            share = 1.0

        return {
            "norm_mm": total,
            "dorsiflexion_mm": dorsi,
            "inversion_mm": inversion,
            "adduction_mm": adduction,
            "dorsiflexion_pct": dorsi / share * 100,
            "inversion_pct": inversion / share * 100,
            "adduction_pct": adduction / share * 100,
            "wasted_pct": (abs(inversion) + abs(adduction)) / share * 100,
            "arm_ankle_mm": arm_ankle,
            "arm_subtalar_mm": arm_subtalar,
        }

    def zajac(self, ankle_deg=0.0):
        """Zajac 1992 的三個準則，相對於脛前肌。1.00 代表完全複製。"""
        self._pose(ankle_deg, 0.0)

        target = self.muscles.get("tib_ant_l")
        target_arm = target.computeMomentArm(self.state, self.ankle) * 1000
        target_values = (
            target.getMaxIsometricForce() * target_arm / 1000,
            target.getOptimalFiberLength() * 1000 / target_arm,
            target.getTendonSlackLength() / target.getOptimalFiberLength(),
        )

        donor_arm = self.donor.computeMomentArm(self.state, self.ankle) * 1000
        donor_values = (
            self.donor.getMaxIsometricForce() * donor_arm / 1000,
            self.donor.getOptimalFiberLength() * 1000 / donor_arm,
            self.donor.getTendonSlackLength()
            / self.donor.getOptimalFiberLength(),
        )

        labels = ["force", "excursion", "character"]
        return {
            label: {
                "donor": donor_values[i],
                "target": target_values[i],
                "ratio": donor_values[i] / target_values[i],
            }
            for i, label in enumerate(labels)
        }

    @staticmethod
    def _angle_deg(first, vertex, last):
        """vertex 那一點，兩段路徑的夾角。180 度 ＝ 完全打直。"""
        u = [first[i] - vertex[i] for i in range(3)]
        v = [last[i] - vertex[i] for i in range(3)]
        norm_u = math.sqrt(sum(x * x for x in u))
        norm_v = math.sqrt(sum(x * x for x in v))
        if norm_u == 0 or norm_v == 0:
            return None
        cosine = sum(u[i] * v[i] for i in range(3)) / (norm_u * norm_v)
        return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))

    def bend_angles(self):
        """骨間膜窗口與支持帶兩處的轉折角，中立位，地面座標。"""
        self._pose(0.0, 0.0)
        self.model.realizePosition(self.state)
        points = [xyz for _, xyz in self.path_points(DONOR)]
        return {
            "window_deg": self._angle_deg(points[0], points[1], points[2]),
            "retinaculum_deg": self._angle_deg(
                points[1], points[2], points[3]
            ),
        }

    # ── 給三維畫面用 ──────────────────────────────────────────

    def path_points(self, muscle_name):
        """這條肌肉目前的路徑點，地面座標。要先 realizePosition。"""
        path = self.muscles.get(muscle_name).getGeometryPath()
        current = path.getCurrentPath(self.state)
        points = []
        for index in range(current.getSize()):
            point = current.get(index)
            location = point.getLocationInGround(self.state)
            points.append((
                point.getName(),
                [location.get(0), location.get(1), location.get(2)],
            ))
        return points

    def frames(self, names=None):
        """每塊骨頭在地面座標的旋轉矩陣與位置。"""
        if names is None:
            names = VIEW_BODIES
        bodies = self.model.getBodySet()
        result = {}
        for name in names:
            transform = bodies.get(name).getTransformInGround(self.state)
            rotation = transform.R()
            position = transform.p()
            result[name] = {
                "R": [
                    [rotation.get(i, j) for j in range(3)] for i in range(3)
                ],
                "p": [position.get(0), position.get(1), position.get(2)],
            }
        return result

    def joint_axes(self):
        """踝與距下關節軸在地面座標的通過點與方向。要先 realizePosition。

        ⭐ 網頁用它把支持帶高度的平面分成背屈／蹠屈、內翻／外翻四區。
        已驗證：用這組軸算的幾何力臂，和 computeMomentArm 相差 0.0000 mm。
        """
        axes = {}
        for key, joint_name, coordinate in (
            ("ankle", "ankle_l", self.ankle),
            ("subtalar", "subtalar_l", self.subtalar),
        ):
            joint = self.model.getJointSet().get(joint_name)
            # 軸定義在父座標系裡，轉到地面才能和路徑點一起算
            transform = joint.getParentFrame().getTransformInGround(
                self.state
            )
            local = self._read_axis(joint_name, coordinate.getName())
            rotation = transform.R()
            position = transform.p()
            axes[key] = {
                "centre": [position.get(i) for i in range(3)],
                "direction": [
                    sum(rotation.get(i, j) * local[j] for j in range(3))
                    for i in range(3)
                ],
            }
        return axes

    def scene(self, ankle_deg=0.0, subtalar_deg=0.0):
        """目前路徑下，指定姿勢的骨頭位置與肌肉路徑。"""
        self._pose(ankle_deg, subtalar_deg)
        self.model.realizePosition(self.state)
        return {
            "ankle_deg": ankle_deg,
            "frames": self.frames(),
            "axes": self.joint_axes(),
            "paths": {
                name: self.path_points(name) for name in VIEW_MUSCLES
            },
        }

    def geometry(self, geometry_dir):
        """把要畫的骨頭網格讀出來，座標在各自骨頭的座標系裡。"""
        meshes = []
        problems = []
        bodies = self.model.getBodySet()

        for body_name in VIEW_BODIES:
            body = bodies.get(body_name)
            attached = body.getPropertyByName("attached_geometry")
            for index in range(attached.size()):
                geometry = body.get_attached_geometry(index)
                mesh = osim.Mesh.safeDownCast(geometry)
                if mesh is None:
                    continue

                file_name = mesh.get_mesh_file()
                try:
                    positions, indices = read_ascii_vtp(
                        os.path.join(geometry_dir, file_name)
                    )
                except Exception as problem:
                    problems.append("%s: %s" % (file_name, problem))
                    continue

                scale = mesh.get_scale_factors()
                factors = [scale.get(0), scale.get(1), scale.get(2)]
                scaled = [
                    round(value * factors[i % 3], 5)
                    for i, value in enumerate(positions)
                ]

                meshes.append({
                    "frame": geometry.getFrame().getName(),
                    "file": file_name,
                    "positions": scaled,
                    "indices": indices,
                })
        return {"meshes": meshes, "problems": problems}

    # ── 一次拿到全部 ──────────────────────────────────────────

    def evaluate(self, via_z, height_cm, insertion="intermediate_cuneiform",
                 angles=None, lower_z=None):
        """網頁版用的入口。高度用內踝尖以上公分，lower_z 見 set_route。"""
        if angles is None:
            angles = list(range(-20, 21, 2))

        via_y = via_y_from_height(height_cm)
        warnings = self.set_route(via_z, via_y, insertion, lower_z)

        rows = self.profile(angles)
        neutral = self.decompose(0.0)
        criteria = self.zajac()
        bend = self.bend_angles()
        path_length = self.donor.getGeometryPath().getLength(self.state)

        return {
            "input": {
                "via_z_mm": via_z * 1000,
                "height_cm": height_cm,
                "height_pct_tibia": height_cm / (TIBIA_LENGTH_M * 100) * 100,
                "insertion": insertion,
                "lower_z_mm": self.lower_z * 1000,
                "lower_z_auto": lower_z is None,
            },
            "angles": angles,
            "dorsi_moment": [row["moment_ankle_nm"] for row in rows],
            "hindfoot_moment": [row["moment_subtalar_nm"] for row in rows],
            "force": [row["force_n"] for row in rows],
            "net_hindfoot": {
                level: [row["net_subtalar_nm"][level] for row in rows]
                for level in PALSY_LEVELS
            },
            "neutral": neutral,
            "zajac_excursion": criteria["excursion"]["ratio"],
            "bend": bend,
            "tendon_slack_mm": self.donor.getTendonSlackLength() * 1000,
            "path_length_mm": path_length * 1000,
            "warnings": warnings,
        }

    def net_in_palsy(self, subtalar_angles, ankle_deg=0.0, level="common"):
        """舊版：麻痺情境下的淨距下力矩，只算捐贈肌、比目魚肌與剩下的腓骨肌。"""
        palsied = list(PALSY_LEVELS[level])

        # ⚠️ 不刪肌肉，只把力設成 1 N，否則致動器數目會變
        for name in palsied:
            self.muscles.get(name).setMaxIsometricForce(1.0)
        self.state = self.model.initSystem()
        self.retension()

        contributors = [DONOR, SOLEUS] + [
            name for name in PERONEALS if name not in palsied
        ]

        rows = []
        for angle in subtalar_angles:
            self._pose(ankle_deg, angle, activate=True)

            total = 0.0
            parts = {}
            for name in contributors:
                muscle = self.muscles.get(name)
                value = (
                    muscle.computeMomentArm(self.state, self.subtalar)
                    * muscle.getActuation(self.state)
                )
                parts[name] = value
                total += value

            rows.append({"subtalar": angle, "net_nm": total, "parts": parts})

        for name in palsied:
            self.muscles.get(name).setMaxIsometricForce(
                self.original_force[name]
            )
        self.state = self.model.initSystem()
        self.retension()
        return rows

    def analyse(self, via_z, via_y, insertion="intermediate_cuneiform",
                angles=None):
        """舊版的入口，保留給既有腳本。"""
        if angles is None:
            angles = list(range(-20, 21, 2))

        warnings = self.set_route(via_z, via_y, insertion)
        subtalar_angles = list(range(-20, 21, 4))

        return {
            "input": {
                "via_z_mm": via_z * 1000,
                "height_above_ankle_cm": (via_y - ANKLE_CENTRE_Y) * 100,
                "insertion": insertion,
            },
            "sweep": self.sweep_ankle(angles),
            "neutral": self.decompose(),
            "zajac": self.zajac(),
            "palsy": self.net_in_palsy(subtalar_angles),
            "tendon_slack_m": self.donor.getTendonSlackLength(),
            "warnings": warnings,
        }
