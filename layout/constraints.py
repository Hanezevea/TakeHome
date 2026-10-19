"""禁区构造与合法性校验。

三条业务约束（题目未给定数值的部分取值见 Config 与 README）：
1. 不遮挡门：门洞向室内预留 door_opening_depth 的通行带；
2. 内开门额外占据 N x N（N = 门宽），即门扇扫过扇形的包围盒；
3. 冰箱开门边前方不得有物体，预留 length x length。
"""
from __future__ import annotations

import math

from shapely.geometry import Point, Polygon
from shapely.prepared import prep

from .config import Config
from .model import Placement, Problem, door_clearance_polygon


def door_inward_normal(problem: Problem) -> tuple[float, float]:
    """门段指向室内的单位法向。

    用探针判定而非依赖轮廓绕向：门段必定落在某条轮廓边上，
    两侧法向中只有一侧在多边形内部。
    """
    (x1, y1), (x2, y2) = problem.door
    dx, dy = x2 - x1, y2 - y1
    n = math.hypot(dx, dy)
    if n <= 0:
        raise ValueError("门段长度为零")
    nx, ny = -dy / n, dx / n
    mid = ((x1 + x2) / 2.0, (y1 + y2) / 2.0)
    probe = max(n * 1e-3, 1e-6)
    if problem.boundary.contains(Point(mid[0] + nx * probe, mid[1] + ny * probe)):
        return (nx, ny)
    return (-nx, -ny)


def door_zone(problem: Problem, cfg: Config) -> Polygon:
    """门前禁区。

    外开门只需保证门洞不被堵（预留浅通行带）；内开门按题目要求
    预留 N x N，N 为门宽。两者取较深者构造同一个矩形。
    """
    (x1, y1), (x2, y2) = problem.door
    nx, ny = door_inward_normal(problem)
    depth = problem.door_width if problem.is_open_inward else cfg.door_opening_depth
    return Polygon([
        (x1, y1),
        (x2, y2),
        (x2 + nx * depth, y2 + ny * depth),
        (x1 + nx * depth, y1 + ny * depth),
    ])


def free_region(problem: Problem, cfg: Config) -> Polygon:
    """可用区域 = 轮廓 - 门禁区。"""
    region = problem.boundary.difference(door_zone(problem, cfg))
    if region.is_empty:
        raise ValueError("扣除门禁区后无可用空间")
    return region


class Validator:
    """封装自由区域与已放置物体，提供增量合法性校验。"""

    def __init__(self, problem: Problem, cfg: Config):
        self.problem = problem
        self.cfg = cfg
        self.region = free_region(problem, cfg)
        self._prepared = prep(self.region)
        self._door_names = {i.name for i in problem.items if i.has_door}
        self._clearance_cache: dict[tuple, Polygon] = {}
        # 冰箱开门区的容纳范围：默认只要求不越出墙体，允许与入户门扇区重叠
        self._clearance_host = (self.region if cfg.fridge_clearance_vs_door_zone
                                else problem.boundary)
        self._clearance_prepared = prep(self._clearance_host)

    def _contained_in(self, rect: Polygon, host: Polygon, prepared) -> bool:
        """rect 是否落在 host 内，按"溢出面积"判定。

        不对 host 做 buffer 膨胀（那会同时放宽墙体与门禁区），而是允许
        沿周长平均 geom_eps/2 的浮点噪声；1220x50 这种真实越界仍会被拒。
        """
        if prepared.contains(rect):
            return True
        leak = rect.difference(host).area
        tol = rect.length * self.cfg.geom_eps * 0.5
        return leak <= tol

    def contains_rect(self, rect: Polygon) -> bool:
        """物体矩形是否落在自由区域（轮廓扣除门禁区）内。"""
        return self._contained_in(rect, self.region, self._prepared)

    def contains_clearance(self, zone: Polygon) -> bool:
        """冰箱开门区是否落在允许范围内（默认为轮廓，不扣门禁区）。"""
        return self._contained_in(zone, self._clearance_host,
                                  self._clearance_prepared)

    def has_door(self, p: Placement) -> bool:
        return p.name in self._door_names

    def clearance_of(self, p: Placement) -> Polygon:
        key = (p.name, round(p.cx, 4), round(p.cy, 4), round(p.angle, 4))
        hit = self._clearance_cache.get(key)
        if hit is None:
            hit = door_clearance_polygon(p, self.cfg.fridge_clearance_depth)
            self._clearance_cache[key] = hit
        return hit

    def check(self, cand: Placement, placed: list[Placement]) -> bool:
        """校验 cand 在已放置 placed 的前提下是否合法。"""
        rect = cand.polygon
        if not self.contains_rect(rect):
            return False

        eps = self.cfg.overlap_area_eps
        zone = self.clearance_of(cand) if self.has_door(cand) else None
        if zone is not None and self.cfg.require_fridge_clearance_inside:
            if not self.contains_clearance(zone):
                return False

        for other in placed:
            other_rect = other.polygon
            if rect.intersection(other_rect).area > eps:
                return False
            # 新物体不得侵占已有冰箱的开门区
            if self.has_door(other):
                if rect.intersection(self.clearance_of(other)).area > eps:
                    return False
            # 已有物体不得落在新冰箱的开门区
            if zone is not None and other_rect.intersection(zone).area > eps:
                return False
        return True
