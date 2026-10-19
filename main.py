"""命令行入口。

用法：
    python main.py examples/example1.json              # 求解并打印结果
    python main.py examples/example1.json --plot        # 同时出图
    python main.py --all --plot                         # 批量跑全部样例
    python main.py examples/example1.json -o out.json   # 结果写入文件
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time

from layout.config import Config
from layout.geometry import load_problem
from layout.solver import solve


def run_one(path: str, cfg: Config, plot: bool, out_dir: str,
            quiet: bool = False) -> dict:
    t0 = time.perf_counter()
    problem = load_problem(path, cfg)
    solution = solve(problem, cfg)
    elapsed = time.perf_counter() - t0

    stem = os.path.splitext(os.path.basename(path))[0]
    result = solution.to_dict()
    result["source"] = path
    result["elapsedSec"] = round(elapsed, 3)

    if not quiet:
        flush = sum(1 for p in solution.placements if p.is_flush)
        print(f"\n=== {os.path.basename(path)} ===")
        print(f"  feasible : {solution.feasible}")
        print(f"  placed   : {len(solution.placements)}/{len(problem.items)}"
              f"  (贴墙 {flush})")
        if solution.unplaced:
            print(f"  unplaced : {solution.unplaced}")
        print(f"  note     : {solution.note}")
        print(f"  time     : {elapsed:.3f}s  nodes={solution.nodes}")
        print(f"  {'item':<14}{'center x':>13}{'center y':>13}"
              f"{'angle':>9}{'wall':>6}")
        for p in solution.placements:
            wall = "-" if p.wall_index is None else str(p.wall_index)
            print(f"  {p.name:<14}{p.cx:>13.3f}{p.cy:>13.3f}"
                  f"{p.angle % 360:>9.2f}{wall:>6}")

    if plot:
        from layout.visualize import plot as do_plot
        os.makedirs(out_dir, exist_ok=True)
        png = do_plot(problem, solution, os.path.join(out_dir, f"{stem}.png"),
                      cfg, title=stem)
        if not quiet:
            print(f"  plot     : {png}")

    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="矩形物体沿墙摆放求解器")
    ap.add_argument("input", nargs="?", help="输入 JSON 路径")
    ap.add_argument("--all", action="store_true",
                    help="批量求解 examples/ 下全部样例")
    ap.add_argument("--plot", action="store_true", help="输出可视化 PNG")
    ap.add_argument("-o", "--output", help="结果 JSON 输出路径")
    ap.add_argument("--out-dir", default="output", help="图片输出目录")
    ap.add_argument("--fridge-clearance", type=float, default=None,
                    help="冰箱开门边预留进深(mm)，默认 600")
    args = ap.parse_args(argv)

    cfg = Config()
    if args.fridge_clearance is not None:
        cfg.fridge_clearance_depth = args.fridge_clearance

    if args.all:
        paths = sorted(glob.glob(os.path.join("examples", "*.json")))
    elif args.input:
        paths = [args.input]
    else:
        ap.error("需指定输入文件，或使用 --all")
        return 2

    if not paths:
        print("未找到输入文件", file=sys.stderr)
        return 1

    results = [run_one(p, cfg, args.plot, args.out_dir) for p in paths]

    if args.all:
        ok = sum(1 for r in results if r["feasible"])
        print(f"\n汇总: {ok}/{len(results)} 可行")

    if args.output:
        payload = results[0] if len(results) == 1 else results
        with open(args.output, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        print(f"\n结果已写入 {args.output}")

    return 0 if all(r["feasible"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
