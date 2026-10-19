"""轮廓清洗的回归测试。

这些用例针对输入数据中实际存在的脏数据，不是假想的边界情况。
"""
from __future__ import annotations

import json

import pytest
from shapely.geometry import Polygon

from layout.config import Config
from layout.geometry import (build_polygon, cluster_angles, extract_walls,
                             inward_normal, load_problem, merge_collinear)

CFG = Config()


def test_example4_raw_polygon_is_invalid():
    """前置事实：example4 原始数据构造出的多边形是无效的。

    末点回绕到第 2 个点，形成自接触退化环。若此断言失效，说明输入
    数据被改动过，清洗逻辑的必要性需重新评估。
    """
    pts = json.load(open("examples/example4.json", encoding="utf-8"))["boundary"]
    assert not Polygon([tuple(p) for p in pts]).is_valid


def test_cleaning_repairs_all_examples():
    for i in (1, 2, 3, 4):
        prob = load_problem(f"examples/example{i}.json", CFG)
        assert prob.boundary.is_valid
        assert prob.boundary.area > 0
        assert prob.boundary.exterior.is_ccw, "外环须规范为逆时针"


def test_cleaning_preserves_area():
    """清洗只应去除零面积退化结构，不得改变实际面积。"""
    for i in (1, 2, 3, 4):
        pts = json.load(open(f"examples/example{i}.json", encoding="utf-8"))["boundary"]
        cleaned = build_polygon(pts, CFG)
        merged = merge_collinear(cleaned, CFG)
        assert merged.area == pytest.approx(cleaned.area, abs=1.0)


def test_known_areas():
    """面积回归值。example1 的 8.813m2 与 reference/image01.png
    标注的"储物区面积 8.8m2"一致，可据此确认图文对应关系。"""
    expected = {1: 8.8131, 2: 7.7039, 3: 11.5190, 4: 6.5730}
    for i, m2 in expected.items():
        prob = load_problem(f"examples/example{i}.json", CFG)
        assert prob.boundary.area / 1e6 == pytest.approx(m2, abs=1e-3)


def test_sliver_notch_excluded_from_walls():
    """example2 的 30x100mm 凹槽不得成为可贴墙边。"""
    prob = load_problem("examples/example2.json", CFG)
    assert all(w.length >= CFG.min_wall_length for w in prob.walls)
    ring_edges = len(prob.boundary.exterior.coords) - 1
    assert len(prob.walls) < ring_edges, "应有短边被过滤"


def test_no_adjacent_collinear_edges_remain():
    """清洗后，环上不应再有相邻共线边。

    注意不能断言"任意两条边方向都不同"：example1 的墙 #1 与 #3 同为
    285.852 度，是被 320mm 台阶隔开的两段真实平行墙，不是应被合并的
    共线重复边。只有相邻边才有合并意义。
    """
    import math
    for i in (1, 2, 3, 4):
        prob = load_problem(f"examples/example{i}.json", CFG)
        ring = list(prob.boundary.exterior.coords)[:-1]
        n = len(ring)
        for k in range(n):
            a, b, c = ring[k - 1], ring[k], ring[(k + 1) % n]
            a1 = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
            a2 = math.degrees(math.atan2(c[1] - b[1], c[0] - b[0]))
            turn = abs((a2 - a1 + 180.0) % 360.0 - 180.0)
            assert turn > CFG.collinear_angle_tol, \
                f"example{i} 顶点 {k} 处仍有共线边，转角仅 {turn:.6f} 度"


def test_micro_tilt_edge_survives_as_own_wall():
    """example1 的 179.975 度边与 90 度边不被误并为同一条墙。

    该边偏离 180 度仅 0.025 度，肉眼不可见，但长 1325mm，是真实墙面。
    """
    prob = load_problem("examples/example1.json", CFG)
    tilted = [w for w in prob.walls if abs(w.angle % 180.0 - 180.0) < 0.1
              or abs(w.angle % 180.0) < 0.1]
    assert tilted, "应保留近水平的那条墙"
    assert any(w.length > 1000.0 for w in tilted)


def test_example1_has_two_orthogonal_families():
    """example1 的斜墙与轴对齐墙构成两个相差非 90 度的正交族。"""
    prob = load_problem("examples/example1.json", CFG)
    reps = cluster_angles(prob.walls, CFG)
    assert len(reps) == 2, f"应聚出 2 个正交族，实际 {reps}"
    # 两族之间相差约 15.85 度，确非同一族
    diff = abs((reps[0] - reps[1] + 45.0) % 90.0 - 45.0)
    assert diff > CFG.angle_cluster_tol


def test_inward_normal_points_inside():
    for i in (1, 2, 3, 4):
        prob = load_problem(f"examples/example{i}.json", CFG)
        for w in prob.walls:
            mid = ((w.ax + w.bx) / 2.0, (w.ay + w.by) / 2.0)
            probe = min(w.length * 1e-3, 1.0)
            pt = (mid[0] + w.inward[0] * probe, mid[1] + w.inward[1] * probe)
            assert prob.boundary.covers(
                __import__("shapely").geometry.Point(pt)), \
                f"example{i} wall#{w.index} 内法向指向了外部"


def test_closure_handled_both_ways():
    """首尾闭合与不闭合两种输入应得到相同结果。"""
    pts = [(0.0, 0.0), (1000.0, 0.0), (1000.0, 1000.0), (0.0, 1000.0)]
    open_poly = build_polygon(pts, CFG)
    closed_poly = build_polygon(pts + [pts[0]], CFG)
    assert open_poly.area == pytest.approx(closed_poly.area)
    assert len(open_poly.exterior.coords) == len(closed_poly.exterior.coords)


def test_short_walls_filtered_by_threshold():
    """长度低于 min_wall_length 的边不参与摆放。"""
    square = build_polygon([(0.0, 0.0), (5000.0, 0.0), (5000.0, 50.0),
                            (5050.0, 50.0), (5050.0, 5000.0), (0.0, 5000.0)],
                           CFG)
    walls = extract_walls(square, CFG)
    assert all(w.length >= CFG.min_wall_length for w in walls)


def test_inward_normal_independent_of_winding():
    """顺时针输入也应得到正确内法向。"""
    ccw = [(0.0, 0.0), (1000.0, 0.0), (1000.0, 1000.0), (0.0, 1000.0)]
    poly = build_polygon(list(reversed(ccw)), CFG)
    n = inward_normal(poly, (0.0, 0.0), (1000.0, 0.0))
    assert n[1] == pytest.approx(1.0, abs=1e-9), "底边内法向应指向 +y"
