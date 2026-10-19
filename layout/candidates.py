"""候选摆放生成。

关键取舍：沿墙的候选位置不做均匀网格采样，只取"接触点"——墙段端点、
已放置物体在该墙轴上的投影端点、以及轮廓顶点的投影。理由是最优的贴靠
解必然与某个已有边界对齐（否则可以继续推紧而不破坏合法性），因此接触点
枚举不会漏掉贴墙最优解，且候选数是 O(已放置数) 而非 O(墙长/步长)。
"""
from __future__ import annotations

import math

from .config import Config
from .model import ItemSpec, Placement, Wall

# 相对墙面的朝向：
#   0   -> length 沿墙、width 进深，开门边朝室内
#   90  -> width 沿墙、length 进深，开门边朝 -u（沿墙反向）
#   180 -> length 沿墙，开门边朝墙（冰箱不可用）
#   270 -> width 沿墙、length 进深，开门边朝 +u
PLAIN_PHIS = (0.0, 90.0)
DOOR_PHIS = (0.0, 90.0, 270.0)


def phis_for(spec: ItemSpec) -> tuple[float, ...]:
    """普通矩形 180 度对称，只需两种朝向；冰箱需区分开门边指向。"""
    return DOOR_PHIS if spec.has_door else PLAIN_PHIS


def footprint(spec: ItemSpec, phi: float) -> tuple[float, float]:
    """返回 (沿墙跨度, 进深)。"""
    if phi in (0.0, 180.0):
        return (spec.length, spec.width)
    return (spec.width, spec.length)


def make_flush(spec: ItemSpec, wall: Wall, phi: float, u0: float) -> Placement:
    """构造贴墙摆放：沿墙起点 u0、紧贴墙面。"""
    span, depth = footprint(spec, phi)
    nx, ny = wall.inward
    # 中心 = 墙上 (u0 + span/2) 处 + 法向 depth/2
    bx, by = wall.point_at(u0 + span / 2.0)
    return Placement(
        name=spec.name,
        cx=bx + nx * depth / 2.0,
        cy=by + ny * depth / 2.0,
        angle=(wall.angle + phi) % 360.0,
        length=spec.length,
        width=spec.width,
        wall_index=wall.index,
        wall_gap=0.0,
    )


def _project_u(wall: Wall, x: float, y: float) -> float:
    dx, dy = wall.direction
    return (x - wall.ax) * dx + (y - wall.ay) * dy


def _project_v(wall: Wall, x: float, y: float) -> float:
    nx, ny = wall.inward
    return (x - wall.ax) * nx + (y - wall.ay) * ny


def _blockers(wall: Wall, depth: float, placed: list[Placement],
              cfg: Config) -> list[tuple[float, float]]:
    """返回会沿该墙构成阻挡的已放置物体在墙轴上的 (u_min, u_max)。

    只有进深区间与待放物体 [0, depth] 相交的物体才算阻挡：贴在对面墙上
    的物体虽然投影到同一墙轴，但不会挡住本次摆放。
    """
    out: list[tuple[float, float]] = []
    for p in placed:
        coords = list(p.polygon.exterior.coords)[:-1]
        vs = [_project_v(wall, x, y) for x, y in coords]
        if min(vs) >= depth - cfg.geom_eps or max(vs) <= cfg.geom_eps:
            continue
        us = [_project_u(wall, x, y) for x, y in coords]
        out.append((min(us), max(us)))
    return out


def contact_us(wall: Wall, span: float, depth: float, placed: list[Placement],
               boundary_pts: list[tuple[float, float]],
               cfg: Config) -> list[float]:
    """生成沿墙的候选起点 u0。

    来源三类：墙段两端（贴角）、阻挡物投影的两端（推紧贴靠）、
    轮廓顶点投影（L 形房间里在凹角处停住）。
    """
    anchors: list[float] = [0.0, wall.length - span]

    for u_min, u_max in _blockers(wall, depth, placed, cfg):
        anchors.append(u_max)          # 紧贴其正向一侧
        anchors.append(u_min - span)   # 紧贴其反向一侧

    for x, y in boundary_pts:
        u = _project_u(wall, x, y)
        if -span <= u <= wall.length + span:
            anchors.append(u)
            anchors.append(u - span)

    seen: set[int] = set()
    out: list[float] = []
    for u in anchors:
        if u < -cfg.geom_eps or u + span > wall.length + cfg.geom_eps:
            continue
        u = max(0.0, min(u, wall.length - span))
        key = int(round(u * 10.0))  # 0.1mm 去重
        if key not in seen:
            seen.add(key)
            out.append(u)
    return out


def anchored_sides(u0: float, span: float, depth: float, wall: Wall,
                   placed: list[Placement], cfg: Config) -> int:
    """该位置沿墙方向有几侧被顶住（0/1/2），用于紧凑度排序。

    两侧独立计数：左侧顶住墙起点或某个阻挡物，右侧顶住墙终点或某个
    阻挡物。顶住两侧意味着恰好填满一个空隙，优先探索。
    """
    tol = max(cfg.geom_eps, 1.0)
    u1 = u0 + span
    blockers = _blockers(wall, depth, placed, cfg)

    left = abs(u0) <= tol or any(abs(u_max - u0) <= tol for _, u_max in blockers)
    right = (abs(u1 - wall.length) <= tol
             or any(abs(u_min - u1) <= tol for u_min, _ in blockers))
    return int(left) + int(right)


def flush_candidates(spec: ItemSpec, walls: list[Wall], placed: list[Placement],
                     boundary_pts: list[tuple[float, float]],
                     cfg: Config) -> list[tuple[int, Placement]]:
    """生成全部贴墙候选，按紧凑度降序返回 (score, placement)。"""
    out: list[tuple[int, Placement]] = []
    for wall in sorted(walls, key=lambda w: -w.length):
        for phi in phis_for(spec):
            span, depth = footprint(spec, phi)
            if span > wall.length + cfg.geom_eps:
                continue
            for u0 in contact_us(wall, span, depth, placed, boundary_pts, cfg):
                score = anchored_sides(u0, span, depth, wall, placed, cfg)
                out.append((score, make_flush(spec, wall, phi, u0)))
    out.sort(key=lambda t: (-t[0], t[1].cx, t[1].cy, t[1].angle))
    return out[:cfg.max_candidates_per_item]


def interior_candidates(spec: ItemSpec, walls: list[Wall], angles: list[float],
                        placed: list[Placement],
                        cfg: Config) -> list[tuple[int, Placement]]:
    """离墙候选（降级策略）。

    位置取已放置物体的角点对齐，而非撒网格：若贴墙全失败，紧贴已有
    物体仍是最省空间的选择。
    """
    out: list[tuple[int, Placement]] = []
    base_angles = []
    for a in angles:
        base_angles.extend([a % 360.0, (a + 90.0) % 360.0])
        if spec.has_door:
            base_angles.extend([(a + 180.0) % 360.0, (a + 270.0) % 360.0])

    seen: set[tuple[int, int, int]] = set()
    for angle in base_angles:
        rad = math.radians(angle)
        ux, uy = math.cos(rad), math.sin(rad)
        vx, vy = -math.sin(rad), math.cos(rad)
        hl, hw = spec.length / 2.0, spec.width / 2.0
        for p in placed:
            for cx0, cy0 in list(p.polygon.exterior.coords)[:-1]:
                for su in (1.0, -1.0):
                    for sv in (1.0, -1.0):
                        cx = cx0 + ux * hl * su + vx * hw * sv
                        cy = cy0 + uy * hl * su + vy * hw * sv
                        key = (int(round(cx * 10)), int(round(cy * 10)),
                               int(round(angle * 10)))
                        if key in seen:
                            continue
                        seen.add(key)
                        out.append((0, Placement(
                            name=spec.name, cx=cx, cy=cy, angle=angle,
                            length=spec.length, width=spec.width,
                            wall_index=None,
                        )))
    return out[:cfg.max_candidates_per_item]
