"""V2 平台共用的止點線、軸速率表、最佳止點搜尋。

⭐ 和 V2 Part 1 notebook §3.1 同一條線。
   六個錨點依序是舟狀骨、內側楔、中間楔、外側楔（重新定位）、骰骨、
   第五蹠骨基底，位置 0 到 5，兩個錨點之間直線內插。
⭐ 軸速率表和 V2 Part 2 notebook §8.1、§9.1 同一個算法。
   每轉 1° 帶出幾度內翻、內收、背屈，只跟踝角度有關，和路徑無關。
"""

import math
import os
import sys

import numpy as np

V2_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if V2_ROOT not in sys.path:
    sys.path.insert(0, V2_ROOT)

from transfer_engine import INTERMEDIATE_CUNEIFORM  # noqa: E402

# 外側楔狀骨：Part 1 notebook §2.1 在 third_cuneiform_lv.vtp 背側面
# 射線找到的點，數字抄自 V2_part1_attachment_sweep.csv 位置 3.00 那一列
LATERAL_CUNEIFORM_V2 = (0.0885523, 0.0304915, 0.0005641)

# 選最佳止點的角度：步態裡最需要背屈的那一刻
SELECTION_ANGLE_DEG = 14.0
# 舟狀骨是原生止點，只當對照，不參加選拔（和 Part 1 一樣）
SELECTION_RANGE = (1.0, 5.0)

# 靜態版與伺服器共用的止點格點，每 0.125 一點
LINE_POSITIONS = [round(index * 0.125, 3) for index in range(41)]

ANCHOR_INFO = [
    ("navicular", "Navicular", "control",
     "Native tibialis posterior insertion. Shown for comparison only."),
    ("medial_cuneiform", "Medial cuneiform", "true",
     "Tibialis anterior insertion in the model."),
    ("intermediate_cuneiform", "Intermediate cuneiform", "interpolated",
     "The insertion used in the first routing study."),
    ("lateral_cuneiform", "Lateral cuneiform", "relocated",
     "Placed on the dorsal surface of the lateral cuneiform bone mesh."),
    ("cuboid", "Cuboid", "proxy",
     "Proxy: a peroneus longus via point near the cuboid groove."),
    ("base_5th_metatarsal", "Base of 5th metatarsal", "true",
     "Peroneus brevis insertion in the model."),
]


def make_anchors(engine):
    """六個錨點，座標在 calcn_l 座標系，公尺。

    :param engine: 已載入模型的 TransferEngine
    :type engine: TransferEngine
    :return: 每個錨點一個 dict，含 key、label、kind、note、position、xyz
    :rtype: list
    """
    coordinates = {
        "intermediate_cuneiform": INTERMEDIATE_CUNEIFORM,
        "lateral_cuneiform": LATERAL_CUNEIFORM_V2,
    }
    anchors = []
    for position, (key, label, kind, note) in enumerate(ANCHOR_INFO):
        # 其他四個錨點從模型的路徑點讀，和 Part 1 一樣
        xyz = coordinates.get(key, engine.insertions[key]["xyz"])
        anchors.append({
            "key": key,
            "label": label,
            "kind": kind,
            "note": note,
            "position": float(position),
            "xyz": tuple(float(value) for value in xyz),
        })
    return anchors


def point_at(anchors, position):
    """止點線上某個位置的座標，兩個錨點之間直線內插。

    :param anchors: make_anchors 的結果
    :type anchors: list
    :param position: 0 到 5，超出就夾回來
    :type position: float
    :return: calcn_l 座標系裡的 (x, y, z)，公尺
    :rtype: tuple
    """
    position = min(max(float(position), 0.0), len(anchors) - 1.0)
    low = min(int(math.floor(position)), len(anchors) - 2)  # 左邊的錨點
    fraction = position - low
    start = np.array(anchors[low]["xyz"])
    end = np.array(anchors[low + 1]["xyz"])
    return tuple(float(value) for value in start + fraction * (end - start))


def describe(anchors, position):
    """位置換成給人看的文字。"""
    position = min(max(float(position), 0.0), len(anchors) - 1.0)
    nearest = int(round(position))
    if abs(position - nearest) < 1e-6:
        return anchors[nearest]["label"]
    low = int(math.floor(position))
    fraction = position - low
    return "%s to %s, %d%% of the way" % (
        anchors[low]["label"], anchors[low + 1]["label"],
        round(fraction * 100),
    )


def axis_in_tibia(engine, key):
    """目前姿勢下，關節軸在脛骨座標裡的單位向量。要先擺好姿勢。

    ⭐ 和 Part 2 notebook §9.1 的 axis_in_tibia 一樣。
    """
    engine.model.realizePosition(engine.state)
    direction = np.array(engine.joint_axes()[key]["direction"])
    tibia = engine.model.getBodySet().get("tibia_l")
    rotation = tibia.getTransformInGround(engine.state).R()
    matrix = np.array(
        [[rotation.get(i, j) for j in range(3)] for i in range(3)]
    )
    local = matrix.T @ direction  # 地面座標換到脛骨座標
    return local / np.linalg.norm(local)


def anatomical(vector):
    """脛骨座標的向量換成臨床方向：內翻 ＝ −x、內收 ＝ −y、背屈 ＝ +z。"""
    return [-vector[0], -vector[1], vector[2]]


def axis_rates(engine, angles_deg):
    """每個踝角度，兩個關節每轉 1° 帶出幾度內翻、內收、背屈。

    ⭐ 分量 ＝ 力矩 × 這張表，所以網頁不用多存資料。
    ⚠️ 軸只跟姿勢有關，和捐贈肌走哪條路無關。

    :param engine: 已載入模型的 TransferEngine
    :type engine: TransferEngine
    :param angles_deg: 踝角度清單
    :type angles_deg: list
    :return: angles、ankle、subtalar 三個欄位，後兩個是每角度一組三個數
    :rtype: dict
    """
    ankle, subtalar = [], []
    for angle in angles_deg:
        engine._pose(float(angle), 0.0)
        ankle.append([
            round(float(value), 6)
            for value in anatomical(axis_in_tibia(engine, "ankle"))
        ])
        subtalar.append([
            round(float(value), 6)
            for value in anatomical(axis_in_tibia(engine, "subtalar"))
        ])
    return {
        "angles": [float(angle) for angle in angles_deg],
        "order": ["inversion", "adduction", "dorsiflexion"],
        "ankle": ankle,
        "subtalar": subtalar,
    }


def sweep_line(engine, anchors, via_z, via_y, lower_z, positions=None):
    """沿止點線，每個位置算 0° 和 14° 的背屈力臂與旋後力臂。

    ⚠️ 會改掉模型的路徑，呼叫完要把目前的路徑重新設回來。

    :param via_z: 中段點內外側座標，公尺
    :type via_z: float
    :param via_y: 中段點高度座標，公尺
    :type via_y: float
    :param lower_z: 支持帶點內外側座標，公尺，None 代表跟著中段點
    :type lower_z: float or None
    :return: positions 與四條力臂曲線（mm）
    :rtype: dict
    """
    if positions is None:
        positions = LINE_POSITIONS
    curves = {
        "dorsi_arm_0": [], "dorsi_arm_14": [],
        "sup_arm_0": [], "sup_arm_14": [],
    }
    for position in positions:
        engine.set_route(
            via_z, via_y, insertion=point_at(anchors, position),
            lower_z=lower_z,
        )
        neutral, flexed = engine.sweep_ankle([0.0, SELECTION_ANGLE_DEG])
        curves["dorsi_arm_0"].append(neutral["arm_ankle_mm"])
        curves["dorsi_arm_14"].append(flexed["arm_ankle_mm"])
        curves["sup_arm_0"].append(neutral["arm_subtalar_mm"])
        curves["sup_arm_14"].append(flexed["arm_subtalar_mm"])
    curves["positions"] = list(positions)
    curves["best"] = best_position(positions, curves["dorsi_arm_14"])
    return curves


def best_position(positions, dorsi_arm_14):
    """14° 背屈力臂最大的位置，只在選拔範圍 1 到 5 裡找。"""
    candidates = [
        (arm, position) for position, arm in zip(positions, dorsi_arm_14)
        if SELECTION_RANGE[0] - 1e-9 <= position <= SELECTION_RANGE[1] + 1e-9
        and math.isfinite(arm)
    ]
    if not candidates:
        return None
    arm, position = max(candidates)
    return {"position": position, "dorsi_arm_14_mm": arm}
