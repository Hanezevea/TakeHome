"""带剪枝的深度优先搜索。

目标函数按字典序：放置件数 > 贴墙件数 > 总离墙距离（越小越好）。
"贴墙优先"按硬优先实现：先只用贴墙候选穷尽搜索（阶段一），仅当无法
全部放下时，才允许剩余物体离墙摆放（阶段二）。
"""
from __future__ import annotations

from .candidates import flush_candidates, interior_candidates
from .config import Config
from .constraints import Validator
from .geometry import cluster_angles
from .model import ItemSpec, Placement, Problem, Solution

# DFS 每层展开的候选数上限。贴墙候选已按紧凑度排序，
# 靠前的几个几乎覆盖全部有价值的分支。
BEAM = 14


def order_items(items: list[ItemSpec]) -> list[ItemSpec]:
    """难放的先放：先按类型优先级，再按面积降序。

    冰箱带开门约束且面积最大，若最后放极易无解。
    """
    return sorted(items, key=lambda i: (-i.priority, -i.area, i.name))


class Solver:
    def __init__(self, problem: Problem, cfg: Config | None = None):
        self.problem = problem
        self.cfg = cfg or Config()
        self.validator = Validator(problem, self.cfg)
        self.boundary_pts = list(problem.boundary.exterior.coords)[:-1]
        self.angles = cluster_angles(problem.walls, self.cfg)
        self.nodes = 0
        self._best: list[Placement] = []
        self._best_key: tuple = (-1, -1, 0.0)

    # --- 目标函数 ---
    @staticmethod
    def score(placed: list[Placement]) -> tuple:
        n = len(placed)
        flush = sum(1 for p in placed if p.is_flush)
        gap = sum(p.wall_gap for p in placed)
        return (n, flush, -gap)

    def _record(self, placed: list[Placement]) -> None:
        key = self.score(placed)
        if key > self._best_key:
            self._best_key = key
            self._best = list(placed)

    # --- 搜索 ---
    def _dfs(self, remaining: list[ItemSpec], placed: list[Placement],
             allow_interior: bool) -> bool:
        self._record(placed)
        if not remaining:
            return True
        if self.nodes >= self.cfg.max_nodes:
            return False

        spec, rest = remaining[0], remaining[1:]
        cands = flush_candidates(spec, self.problem.walls, placed,
                                 self.boundary_pts, self.cfg)
        if allow_interior:
            cands = cands + interior_candidates(
                spec, self.problem.walls, self.angles, placed, self.cfg)

        tried = 0
        for _score, cand in cands:
            if tried >= BEAM or self.nodes >= self.cfg.max_nodes:
                break
            self.nodes += 1
            if not self.validator.check(cand, placed):
                continue
            tried += 1
            placed.append(cand)
            if self._dfs(rest, placed, allow_interior):
                return True
            placed.pop()

        # 该物体放不下时，跳过它继续排后面的，保留"尽力而为"的部分解
        if rest:
            self._dfs(rest, placed, allow_interior)
        return False

    def solve(self) -> Solution:
        ordered = order_items(self.problem.items)

        # 阶段一：只允许贴墙
        self.nodes = 0
        self._best, self._best_key = [], (-1, -1, 0.0)
        ok = self._dfs(ordered, [], allow_interior=False)
        note = "全部贴墙" if ok else ""

        # 阶段二：贴墙放不下时允许离墙
        if not ok:
            phase1_best, phase1_key = self._best, self._best_key
            self._best, self._best_key = [], (-1, -1, 0.0)
            ok2 = self._dfs(ordered, [], allow_interior=True)
            if self._best_key < phase1_key:
                self._best, self._best_key = phase1_best, phase1_key
                note = "部分物体无法放置（仅贴墙方案最优）"
            else:
                note = "全部放下，部分物体离墙" if ok2 else "部分物体无法放置"

        placed_names = {p.name for p in self._best}
        unplaced = [i.name for i in self.problem.items if i.name not in placed_names]
        return Solution(
            feasible=not unplaced,
            placements=self._finalize(self._best),
            unplaced=unplaced,
            nodes=self.nodes,
            note=note,
        )

    def _finalize(self, placed: list[Placement]) -> list[Placement]:
        """按输入顺序输出，并补算离墙距离。"""
        order = {it.name: k for k, it in enumerate(self.problem.items)}
        for p in placed:
            if not p.is_flush:
                p.wall_gap = p.polygon.distance(self.problem.boundary.exterior)
        return sorted(placed, key=lambda p: order.get(p.name, 1 << 30))


def solve(problem: Problem, cfg: Config | None = None) -> Solution:
    return Solver(problem, cfg).solve()
