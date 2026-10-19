"""核心数据结构。

角度约定：逆时针为正，单位度。angle=0 时物体 length 沿 +x、width 沿 +y。
冰箱开门边固定为局部 +y 一侧（即 length 所在的那条边），因此冰箱的
angle 需在 0-360 内区分，普通矩形只需 mod 180。
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from shapely.geometry import Polygon

# 摆放优先级：数值大者先放。冰箱带开门约束且面积最大，最难安置。
KIND_PRIORITY = {
    "fridge": 40,
    "iceMaker": 30,
    "shelf": 20,
    "overShelf": 10,
}

_SUFFIX_RE = re.compile(r"-\d+$")


def parse_kind(name: str) -> str:
    """'shelf-1' -> 'shelf'；无后缀则原样返回。"""
    return _SUFFIX_RE.sub("", name)


@dataclass(frozen=True)
class ItemSpec:
    name: str
    length: float
    width: float

    @property
    def kind(self) -> str:
        return parse_kind(self.name)

    @property
    def area(self) -> float:
        return self.length * self.width

    @property
    def priority(self) -> int:
        return KIND_PRIORITY.get(self.kind, 0)

    @property
    def has_door(self) -> bool:
        """是否带开门边。仅冰箱有此约束（题目 Notes 第 1 条）。"""
        return self.kind == "fridge"


@dataclass
class Placement:
    """一个物体的最终位置。center 为世界坐标，angle 为度。"""

    name: str
    cx: float
    cy: float
    angle: float
    length: float
    width: float
    wall_index: int | None = None
    """贴靠的墙边序号；None 表示离墙摆放。"""

    wall_gap: float = 0.0
    """离最近墙面的距离(mm)，贴墙时为 0。"""

    @property
    def polygon(self) -> Polygon:
        return rect_polygon(self.cx, self.cy, self.length, self.width, self.angle)

    @property
    def is_flush(self) -> bool:
        return self.wall_index is not None

    def to_dict(self) -> dict:
        return {
            "center": [round(self.cx, 4), round(self.cy, 4)],
            "angle": round(self.angle % 360.0, 4),
            "size": [self.length, self.width],
            "againstWall": self.is_flush,
        }


def rect_polygon(cx: float, cy: float, length: float, width: float,
                 angle_deg: float) -> Polygon:
    """以 (cx, cy) 为中心、逆时针旋转 angle_deg 的矩形。"""
    rad = math.radians(angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    hl, hw = length / 2.0, width / 2.0
    corners = []
    for dx, dy in ((-hl, -hw), (hl, -hw), (hl, hw), (-hl, hw)):
        corners.append((cx + dx * cos_a - dy * sin_a,
                        cy + dx * sin_a + dy * cos_a))
    return Polygon(corners)


def door_clearance_polygon(p: Placement, depth: float) -> Polygon:
    """冰箱开门区：从局部 +y 边向外延伸 depth，宽度等于 length。"""
    rad = math.radians(p.angle)
    nx, ny = -math.sin(rad), math.cos(rad)  # 局部 +y 的世界方向
    offset = p.width / 2.0 + depth / 2.0
    return rect_polygon(p.cx + nx * offset, p.cy + ny * offset,
                        p.length, depth, p.angle)


@dataclass
class Wall:
    """轮廓的一条边，附带指向室内的法向与局部坐标系。"""

    index: int
    ax: float
    ay: float
    bx: float
    by: float
    inward: tuple[float, float]

    @property
    def length(self) -> float:
        return math.hypot(self.bx - self.ax, self.by - self.ay)

    @property
    def direction(self) -> tuple[float, float]:
        n = self.length
        return ((self.bx - self.ax) / n, (self.by - self.ay) / n)

    @property
    def angle(self) -> float:
        """边方向角，度，取值 [0, 360)。"""
        return math.degrees(math.atan2(self.by - self.ay, self.bx - self.ax)) % 360.0

    def point_at(self, u: float) -> tuple[float, float]:
        dx, dy = self.direction
        return (self.ax + dx * u, self.ay + dy * u)


@dataclass
class Problem:
    boundary: Polygon
    door: tuple[tuple[float, float], tuple[float, float]]
    is_open_inward: bool
    items: list[ItemSpec]
    walls: list[Wall] = field(default_factory=list)
    source: str = ""

    @property
    def door_width(self) -> float:
        (x1, y1), (x2, y2) = self.door
        return math.hypot(x2 - x1, y2 - y1)


@dataclass
class Solution:
    feasible: bool
    placements: list[Placement]
    unplaced: list[str]
    nodes: int = 0
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "feasible": self.feasible,
            "placements": {p.name: p.to_dict() for p in self.placements},
            "unplaced": self.unplaced,
            "stats": {"nodes": self.nodes, "note": self.note},
        }
