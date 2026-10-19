"""轮廓清洗与墙面提取。

输入的 boundary 直接来自 CAD 导出，存在三类脏数据，必须先处理：
1. 闭合方式不一致：example1/2/3 首尾点重复，example4 不重复；
2. 退化自接触：example4 末点回绕到第 2 个点，shapely 直接构造报
   Ring Self-intersection，面积仍可算但拓扑运算会失败；
3. 制图伪影：example2 存在 30x100mm 凹槽，不是可用摆放空间。
"""
from __future__ import annotations

import json
import math

from shapely.geometry import MultiPolygon, Point, Polygon
from shapely.geometry.polygon import orient
from shapely.validation import make_valid

from .config import Config
from .model import ItemSpec, Problem, Wall


def _dedupe(points: list[tuple[float, float]], eps: float) -> list[tuple[float, float]]:
    """去掉连续重合点，并去掉与首点重合的尾点（统一为不闭合表示）。"""
    out: list[tuple[float, float]] = []
    for p in points:
        if not out or math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > eps:
            out.append(p)
    while len(out) > 1 and math.hypot(out[0][0] - out[-1][0],
                                     out[0][1] - out[-1][1]) <= eps:
        out.pop()
    return out


def _largest_polygon(geom) -> Polygon:
    """make_valid 可能返回 MultiPolygon/GeometryCollection，取最大面积的面。"""
    if isinstance(geom, Polygon):
        return geom
    polys: list[Polygon] = []
    if isinstance(geom, MultiPolygon):
        polys = list(geom.geoms)
    elif hasattr(geom, "geoms"):
        polys = [g for g in geom.geoms if isinstance(g, Polygon)]
    if not polys:
        raise ValueError(f"无法从 {geom.geom_type} 中提取多边形")
    return max(polys, key=lambda g: g.area)


def build_polygon(points: list[tuple[float, float]], cfg: Config) -> Polygon:
    """由原始顶点构造有效多边形，并规范为逆时针绕向。"""
    pts = _dedupe([tuple(map(float, p)) for p in points], cfg.point_eps)
    if len(pts) < 3:
        raise ValueError(f"轮廓点数不足：{len(pts)}")

    poly = Polygon(pts)
    if not poly.is_valid:
        poly = _largest_polygon(make_valid(poly))
    # buffer(0) 清掉零宽度的退化枝（example4 的回绕边）
    if not poly.is_valid or poly.is_empty:
        poly = _largest_polygon(poly.buffer(0))
    if poly.is_empty or poly.area <= 0:
        raise ValueError("轮廓面积为零")
    return orient(poly, sign=1.0)  # sign=1.0 -> 外环逆时针


def merge_collinear(poly: Polygon, cfg: Config) -> Polygon:
    """合并方向差小于阈值的相邻边。

    example1 中存在 179.97 度的边，不合并会让同一面墙被切成两段，
    进而生成两个几乎相同、只差 0.03 度的候选朝向。
    """
    ring = list(poly.exterior.coords)[:-1]
    n = len(ring)
    if n < 4:
        return poly

    keep: list[tuple[float, float]] = []
    for i in range(n):
        prev_p, cur, next_p = ring[i - 1], ring[i], ring[(i + 1) % n]
        a1 = math.degrees(math.atan2(cur[1] - prev_p[1], cur[0] - prev_p[0]))
        a2 = math.degrees(math.atan2(next_p[1] - cur[1], next_p[0] - cur[0]))
        turn = abs((a2 - a1 + 180.0) % 360.0 - 180.0)
        if turn > cfg.collinear_angle_tol:
            keep.append(cur)

    if len(keep) < 3:
        return poly
    merged = Polygon(keep)
    if not merged.is_valid:
        return poly
    return orient(merged, sign=1.0)


def extract_walls(poly: Polygon, cfg: Config) -> list[Wall]:
    """提取可作为摆放基准的墙边。

    过滤掉短于 min_wall_length 的边：这类边要么是制图伪影，要么比
    最窄的物体还窄，贴上去也放不下任何东西。
    """
    ring = list(poly.exterior.coords)[:-1]
    walls: list[Wall] = []
    for i in range(len(ring)):
        ax, ay = ring[i]
        bx, by = ring[(i + 1) % len(ring)]
        seg_len = math.hypot(bx - ax, by - ay)
        if seg_len < cfg.min_wall_length:
            continue
        inward = inward_normal(poly, (ax, ay), (bx, by))
        walls.append(Wall(index=len(walls), ax=ax, ay=ay, bx=bx, by=by,
                          inward=inward))
    return walls


def inward_normal(poly: Polygon, a: tuple[float, float],
                  b: tuple[float, float]) -> tuple[float, float]:
    """线段 a->b 指向多边形内部的单位法向。

    逆时针外环的左法向即为内法向，但仍做一次探针校验，避免
    make_valid 之后绕向被改写导致整套坐标系翻转。
    """
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = math.hypot(dx, dy)
    nx, ny = -dy / n, dx / n
    mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
    probe = max(n * 1e-3, 1e-6)
    if not poly.contains(Point(mid[0] + nx * probe, mid[1] + ny * probe)):
        return (-nx, -ny)
    return (nx, ny)


def cluster_angles(walls: list[Wall], cfg: Config) -> list[float]:
    """把墙面方向按 mod 90 聚类，返回每个正交族的代表角度。

    用于生成离墙摆放时的候选朝向。按 mod 90 而非 mod 180 聚类，是因为
    摆放时会同时尝试 angle 与 angle+90（长边/短边贴墙两种），互相垂直的
    方向已被覆盖，无需作为独立代表。example1 的 6 条边因此压缩为
    2 个代表角（轴对齐族 + 旋转约 15.85 度族）。

    贴墙摆放仍使用各边的精确角度：若把 179.975 度的边归一到 180 度，
    沿 1325mm 长墙会累积约 0.6mm 的偏差而戳出轮廓。
    """
    reps: list[float] = []
    for w in sorted(walls, key=lambda x: -x.length):
        a = w.angle % 90.0
        if not any(abs((a - r + 45.0) % 90.0 - 45.0) <= cfg.angle_cluster_tol
                   for r in reps):
            reps.append(a)
    return reps


def load_problem(path: str, cfg: Config | None = None) -> Problem:
    cfg = cfg or Config()
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)

    poly = merge_collinear(build_polygon(data["boundary"], cfg), cfg)
    door = tuple(tuple(map(float, p)) for p in data["door"])
    items = [ItemSpec(name=k, length=float(v[0]), width=float(v[1]))
             for k, v in data["algoToPlace"].items()]

    problem = Problem(
        boundary=poly,
        door=door,  # type: ignore[arg-type]
        is_open_inward=bool(data.get("isOpenInward", False)),
        items=items,
        source=path,
    )
    problem.walls = extract_walls(poly, cfg)
    return problem
