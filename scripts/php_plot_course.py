#!/usr/bin/env python3
"""Plot official-student MuJoCo trajectories and actual OBJ block footprints."""

import argparse
import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon

from php_score_course import DEFAULT_TERRAIN, blocks


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRIALS = ROOT / "outputs/reproduction/official_benchmark"


def read_trace(path: Path):
    return [{key: float(value) for key, value in row.items()}
            for row in csv.DictReader(path.open())]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=Path, default=DEFAULT_TRIALS)
    parser.add_argument("--trial", action="append", dest="trial_names",
                        help="trial directory name; repeat to compare multiple runs")
    parser.add_argument("--max-blocks", type=int, default=4)
    parser.add_argument("--terrain", type=Path, default=DEFAULT_TERRAIN)
    parser.add_argument("--output", type=Path,
                        default=DEFAULT_TRIALS / "course_xy.png")
    args = parser.parse_args()
    if args.max_blocks < 1:
        parser.error("--max-blocks must be positive")
    trial_names = args.trial_names or ["trial_002", "trial_006", "trial_007"]
    figure, (plan, height) = plt.subplots(2, 1, figsize=(11, 7), sharex=True,
                                          gridspec_kw={"height_ratios": [2, 1]})
    colors = ("#3976bc", "#cf6b17", "#538448", "#a34e82", "#745ca7")
    for index, corners, block_height in blocks(args.terrain):
        if index > args.max_blocks:
            break
        polygon = [(v[0], v[1]) for v in corners]
        plan.add_patch(Polygon(polygon, facecolor="#ddd7c9", edgecolor="#786951",
                               linewidth=1.0, zorder=0))
        x_center = sum(v[0] for v in corners) / len(corners)
        plan.text(x_center, 0, f"{index}\n{block_height:.2f} m", ha="center", va="center",
                  fontsize=8, color="#3c332b")
        xmin = min(v[0] for v in corners)
        xmax = max(v[0] for v in corners)
        height.hlines(block_height, xmin, xmax, colors="#786951", linewidth=3)
    end_x = 0.0
    for trial_number, trial_name in enumerate(trial_names):
        color = colors[trial_number % len(colors)]
        trace = read_trace(args.trials / trial_name / "pelvis.csv")
        plan.plot([r["x"] for r in trace], [r["y"] for r in trace],
                  color=color, linewidth=1.6, label=trial_name.replace("trial_", "trial "))
        plan.scatter(trace[-1]["x"], trace[-1]["y"], color=color, s=20)
        height.plot([r["x"] for r in trace], [r["z"] for r in trace],
                    color=color, linewidth=1.4, label=trial_name.replace("trial_", "trial "))
        end_x = max(end_x, max(r["x"] for r in trace))
    plan.axhline(1.0, color="#b1b1b1", linestyle="--", linewidth=0.8)
    plan.axhline(-1.0, color="#b1b1b1", linestyle="--", linewidth=0.8)
    plan.set_ylabel("Lateral position y (m)")
    plan.set_ylim(-3.3, 3.3)
    plan.set_xlim(0, max(22, end_x + 0.5))
    plan.grid(alpha=0.2)
    plan.legend(loc="upper left")
    height.set_xlabel("Forward position x (m)")
    height.set_ylabel("Pelvis height z (m)")
    height.set_ylim(0, 1.7)
    height.grid(alpha=0.2)
    height.legend(loc="upper left")
    figure.suptitle("Released PHP student on the bundled MuJoCo stepped course")
    figure.tight_layout()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(args.output, dpi=180)
    print(args.output)


if __name__ == "__main__":
    main()
