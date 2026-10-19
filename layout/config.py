"""可调参数集中在此，便于在不改算法的前提下调整几何容差与业务假设。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Config:
    # --- 几何容差（输入坐标精度到 0.1mm，容差取毫米级） ---
    point_eps: float = 1e-3
    """判断两个顶点重合的距离阈值(mm)。"""

    geom_eps: float = 1.0
    """包含性判断容差(mm)。轮廓边存在 0.025 度级别的微小倾斜，
    严格 contains 会因浮点噪声误判，故对自由区域做 eps 膨胀后再判断。"""

    overlap_area_eps: float = 1.0
    """允许的重叠面积(mm^2)。相邻物体贴合时边界会产生零宽度交集。"""

    collinear_angle_tol: float = 0.5
    """合并共线相邻边的角度阈值(度)。"""

    angle_cluster_tol: float = 0.5
    """墙面方向聚类阈值(度)。example1 中存在 179.97 度的边，
    需与 180 度归为一类，否则候选角度会膨胀出肉眼不可见的歪斜。"""

    min_wall_length: float = 200.0
    """可贴墙边的最小长度(mm)。短于此值的边来自制图伪影
    (如 example2 的 30x100 凹槽)，不作为摆放基准。"""

    # --- 业务假设（题目未给定，取值已在 README 说明） ---
    door_opening_depth: float = 50.0
    """门洞向室内预留的进深(mm)。题目仅要求"不遮挡门的位置"，
    此值用于拒绝紧贴门洞的摆放。"""

    fridge_clearance_depth: float = 600.0
    """冰箱开门边前方预留进深(mm)，该范围内不得有任何物体。

    题目只要求"开门边不能放任何东西"，未给定进深。取 600mm 的理由：
    这是取物所需的最小身位，也是厨房设计中电器前的常用通行净宽。

    注意不要取 length(1220)：那等于要求预留门板全开的 1220x1220 包围盒，
    使冰箱总占用进深达 1330+1220=2550mm。而 example3 可用空间约 2150mm、
    example4 约 1900mm，会导致这两例无解——并非真正不可行，而是假设过严。
    """

    require_fridge_clearance_inside: bool = True
    """是否要求开门区完整落在轮廓内。

    与上一条是两件事：开门区"不被物体占用"是题目硬要求；而开门区"不能
    越出墙体"是物理前提(否则门开不了)。两者解耦后，可用较浅的
    clearance 保证可行性，同时仍然禁止任何物体进入开门区。
    """

    fridge_clearance_vs_door_zone: bool = False
    """冰箱开门区是否禁止与入户门扇扫过区重叠。

    置 False 的理由：墙体不可穿越，但两扇门共用摆动空间只是"不能同时
    打开"，现实中普遍可接受。example3 的房间最宽通道仅 1400-1500mm
    (buffer(-750) 为空)，若连门扇区也禁止重叠，冰箱必然无解——而这是
    假设过严，不是真正不可行。
    """

    # --- 搜索规模上限 ---
    max_nodes: int = 400_000
    max_candidates_per_item: int = 4000
