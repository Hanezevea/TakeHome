"""结果出图，用于与 reference/image0*.png 人工对照。

这一步不是锦上添花：几何约束写错时，数值输出往往看不出问题，
叠图是最快的自检手段。
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # 无界面环境下直接存图
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MplPolygon

from .config import Config
from .constraints import Validator, door_zone
from .model import Problem, Solution, parse_kind

KIND_COLOR = {
    "fridge": "#4e79a7",
    "iceMaker": "#59a14f",
    "shelf": "#f28e2b",
    "overShelf": "#b07aa1",
}


def _ring(geom) -> list[tuple[float, float]]:
    return list(geom.exterior.coords)


def plot(problem: Problem, solution: Solution, out_path: str,
         cfg: Config | None = None, title: str = "") -> str:
    cfg = cfg or Config()
    validator = Validator(problem, cfg)

    fig, ax = plt.subplots(figsize=(9, 9))

    # 轮廓
    ax.add_patch(MplPolygon(_ring(problem.boundary), closed=True,
                            facecolor="#f5f5f5", edgecolor="#333333",
                            linewidth=2.0, zorder=1))

    # 门禁区与门段
    dz = door_zone(problem, cfg)
    ax.add_patch(MplPolygon(_ring(dz), closed=True, facecolor="#e15759",
                            alpha=0.18, edgecolor="#e15759", linewidth=1.0,
                            linestyle="--", zorder=2))
    (dx1, dy1), (dx2, dy2) = problem.door
    ax.plot([dx1, dx2], [dy1, dy2], color="#e15759", linewidth=4.0, zorder=5)

    # 物体
    for p in solution.placements:
        color = KIND_COLOR.get(parse_kind(p.name), "#999999")
        ax.add_patch(MplPolygon(_ring(p.polygon), closed=True, facecolor=color,
                                alpha=0.55, edgecolor=color, linewidth=1.5,
                                zorder=3))
        if validator.has_door(p):
            ax.add_patch(MplPolygon(_ring(validator.clearance_of(p)),
                                    closed=True, facecolor="none",
                                    edgecolor=color, hatch="///",
                                    linewidth=1.0, linestyle=":", zorder=2))
        ax.annotate(f"{p.name}\n{p.angle:.1f}°", (p.cx, p.cy),
                    ha="center", va="center", fontsize=7, zorder=6)

    minx, miny, maxx, maxy = problem.boundary.bounds
    pad = max(maxx - minx, maxy - miny) * 0.08
    ax.set_xlim(minx - pad, maxx + pad)
    ax.set_ylim(miny - pad, maxy + pad)
    ax.set_aspect("equal")
    ax.grid(True, linestyle=":", alpha=0.3)

    status = "FEASIBLE" if solution.feasible else "INFEASIBLE"
    head = title or out_path
    flush = sum(1 for p in solution.placements if p.is_flush)
    ax.set_title(f"{head}  [{status}]\n"
                 f"placed {len(solution.placements)}/{len(problem.items)}, "
                 f"flush {flush}, door {problem.door_width:.0f}mm "
                 f"({'inward' if problem.is_open_inward else 'outward'})",
                 fontsize=10)
    ax.set_xlabel("x (mm)")
    ax.set_ylabel("y (mm)")

    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)
    return out_path
