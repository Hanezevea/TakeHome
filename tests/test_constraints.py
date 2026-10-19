"""对四个样例的输出做全约束校验。

这些断言是本项目的正确性依据：出图只能发现明显错误，毫米级的越界与
零宽度重叠必须靠数值断言兜住。
"""
from __future__ import annotations

import glob
import math
import os

import pytest

from layout.config import Config
from layout.constraints import Validator, door_zone
from layout.geometry import load_problem
from layout.model import rect_polygon
from layout.solver import solve

EXAMPLES = sorted(glob.glob(os.path.join("examples", "*.json")))
assert EXAMPLES, "未找到 examples/*.json"
IDS = [os.path.splitext(os.path.basename(p))[0] for p in EXAMPLES]


@pytest.fixture(scope="module", params=EXAMPLES, ids=IDS)
def solved(request):
    cfg = Config()
    problem = load_problem(request.param, cfg)
    return problem, solve(problem, cfg), cfg


def test_all_examples_feasible(solved):
    problem, sol, _ = solved
    assert sol.feasible, f"{problem.source} 不可行，未放置：{sol.unplaced}"
    assert len(sol.placements) == len(problem.items)
    assert not sol.unplaced


def test_every_item_placed_once(solved):
    problem, sol, _ = solved
    names = [p.name for p in sol.placements]
    assert sorted(names) == sorted(i.name for i in problem.items)
    assert len(names) == len(set(names)), "存在重复摆放"


def test_sizes_preserved(solved):
    """只允许旋转，不允许缩放：边长必须与输入一致。"""
    problem, sol, _ = solved
    spec = {i.name: (i.length, i.width) for i in problem.items}
    for p in sol.placements:
        assert (p.length, p.width) == spec[p.name]
        # 由中心点与角度重建的矩形面积应等于 length*width
        assert rect_polygon(p.cx, p.cy, p.length, p.width, p.angle).area == \
            pytest.approx(p.length * p.width, rel=1e-9)


def test_inside_boundary(solved):
    """不与轮廓重叠：溢出面积须可忽略。"""
    problem, sol, cfg = solved
    for p in sol.placements:
        leak = p.polygon.difference(problem.boundary).area
        assert leak <= p.polygon.length * cfg.geom_eps, \
            f"{p.name} 越出轮廓 {leak:.1f}mm2"


def test_no_pairwise_overlap(solved):
    """物体之间互不重叠。"""
    _, sol, cfg = solved
    rects = [(p.name, p.polygon) for p in sol.placements]
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            (n1, r1), (n2, r2) = rects[i], rects[j]
            area = r1.intersection(r2).area
            assert area <= cfg.overlap_area_eps, \
                f"{n1} 与 {n2} 重叠 {area:.1f}mm2"


def test_door_not_blocked(solved):
    """不遮挡门：门禁区内不得有物体。"""
    problem, sol, cfg = solved
    zone = door_zone(problem, cfg)
    for p in sol.placements:
        area = p.polygon.intersection(zone).area
        assert area <= cfg.overlap_area_eps, \
            f"{p.name} 侵占门禁区 {area:.1f}mm2"


def test_inward_door_reserves_square(solved):
    """内开门须预留 N x N（N 为门宽）。"""
    problem, _, cfg = solved
    if not problem.is_open_inward:
        pytest.skip("外开门")
    n = problem.door_width
    assert door_zone(problem, cfg).area == pytest.approx(n * n, rel=1e-6)


def test_fridge_clearance_unoccupied(solved):
    """冰箱开门边前方不得有任何物体。"""
    problem, sol, cfg = solved
    v = Validator(problem, cfg)
    fridges = [p for p in sol.placements if v.has_door(p)]
    if not fridges:
        pytest.skip("无冰箱")
    for f in fridges:
        zone = v.clearance_of(f)
        assert zone.area == pytest.approx(f.length * cfg.fridge_clearance_depth,
                                          rel=1e-9)
        for other in sol.placements:
            if other.name == f.name:
                continue
            area = other.polygon.intersection(zone).area
            assert area <= cfg.overlap_area_eps, \
                f"{other.name} 落在 {f.name} 开门区内 {area:.1f}mm2"


def test_fridge_clearance_within_walls(solved):
    """冰箱开门区不得越出墙体，否则门物理上打不开。"""
    problem, sol, cfg = solved
    v = Validator(problem, cfg)
    for f in [p for p in sol.placements if v.has_door(p)]:
        zone = v.clearance_of(f)
        leak = zone.difference(problem.boundary).area
        assert leak <= zone.length * cfg.geom_eps, \
            f"{f.name} 开门区越出墙体 {leak:.1f}mm2"


def test_angles_parallel_to_some_wall(solved):
    """物体须与某条轮廓边平行或垂直。"""
    problem, sol, cfg = solved
    wall_angles = [w.angle % 90.0 for w in problem.walls]
    for p in sol.placements:
        a = p.angle % 90.0
        diffs = [abs((a - w + 45.0) % 90.0 - 45.0) for w in wall_angles]
        assert min(diffs) <= cfg.angle_cluster_tol, \
            f"{p.name} 角度 {p.angle:.3f} 不与任何墙平行/垂直"


def test_flush_items_touch_wall(solved):
    """标记为贴墙的物体必须真的贴在墙上。"""
    problem, sol, cfg = solved
    for p in sol.placements:
        if not p.is_flush:
            continue
        d = p.polygon.distance(problem.boundary.exterior)
        assert d <= cfg.geom_eps, f"{p.name} 标记贴墙但离墙 {d:.3f}mm"


def test_wall_preference_is_hard_priority(solved):
    """贴墙为硬优先：四个样例应全部贴墙摆放。"""
    _, sol, _ = solved
    off_wall = [p.name for p in sol.placements if not p.is_flush]
    assert not off_wall, f"存在离墙摆放：{off_wall}"


def test_angle_in_canonical_range(solved):
    """输出角度规范在 [0, 360)。"""
    _, sol, _ = solved
    for p in sol.placements:
        a = p.to_dict()["angle"]
        assert 0.0 <= a < 360.0
        assert not math.isnan(a)
