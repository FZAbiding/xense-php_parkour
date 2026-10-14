#!/usr/bin/env python3
"""Score pelvis traces against the geometry in Holosoma's bundled OBJ course.

Evidence rule: a block is classified as mounted when the pelvis is above its
footprint by at least 0.45 m beyond block height; foot contact is not checked.
It is cleared only if, at the first sampled position 1.5 m beyond the block,
the pelvis is on the course (|y| <= 1.0 m) and upright (z >= 0.55 m).
Later recovery into the corridor is recorded separately. This is an operational sim2sim criterion,
not a claim of the paper's IsaacSim success rate.
"""

import argparse
import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TERRAIN = (ROOT / "thirdparty/holosoma/src/holosoma/holosoma/data/terrains/terrain.obj")


def inside(x: float, y: float, points: list[tuple[float, float]]) -> bool:
    hit = False
    j = len(points) - 1
    for i in range(len(points)):
        xi, yi = points[i]
        xj, yj = points[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            hit = not hit
        j = i
    return hit


def blocks(path: Path):
    vertices = [tuple(map(float, line.split()[1:])) for line in path.read_text().splitlines()
                if line.startswith("v ")]
    # First eight vertices describe the 80 m ground slab; each subsequent group
    # of eight is one raised block (four bottom and four top corners).
    if (len(vertices) - 8) % 8:
        raise ValueError("expected ground slab followed by eight-vertex blocks")
    for index, offset in enumerate(range(8, len(vertices), 8), start=1):
        group = vertices[offset:offset + 8]
        yield index, group[:4], max(v[2] for v in group)


def score(trace: Path, terrain: Path) -> dict:
    with trace.open() as stream:
        rows = [{key: float(value) for key, value in row.items()}
                for row in csv.DictReader(stream)]
    if not rows:
        raise ValueError(f"empty trace: {trace}")
    outcomes = []
    for index, corners, height in blocks(terrain):
        polygon = [(vertex[0], vertex[1]) for vertex in corners]
        xmin = min(x for x, _ in polygon)
        xmax = max(x for x, _ in polygon)
        mounted_index = next((position for position, row in enumerate(rows)
                              if inside(row["x"], row["y"], polygon)
                              and row["z"] >= height + 0.45), None)
        mounted = rows[mounted_index] if mounted_index is not None else None
        later = rows[mounted_index + 1:] if mounted_index is not None else []
        first_exit = next((row for row in later if row["x"] >= xmax + 1.5), None)
        cleared = (first_exit if first_exit and abs(first_exit["y"]) <= 1.0
                   and first_exit["z"] >= 0.55 else None)
        recovered = (next((row for row in later if first_exit
                           and row["wall_s"] > first_exit["wall_s"]
                           and row["x"] >= xmax + 1.5 and abs(row["y"]) <= 1.0
                           and row["z"] >= 0.55), None) if first_exit and not cleared else None)
        status = ("cleared" if cleared else
                  "off_course_at_exit" if first_exit and abs(first_exit["y"]) > 1.0 else
                  "low_at_exit" if first_exit else "mounted" if mounted else
                  "approached" if any(row["x"] >= xmin - 0.5 for row in rows)
                  else "not_reached")
        outcomes.append({"block": index, "height_m": height,
                         "x_range_m": [round(xmin, 2), round(xmax, 2)],
                         "status": status,
                         "mounted_at_s": round(mounted["wall_s"], 2) if mounted else None,
                         "first_exit_at_s": round(first_exit["wall_s"], 2) if first_exit else None,
                         "first_exit_y_m": round(first_exit["y"], 3) if first_exit else None,
                         "recovered_later_at_s": round(recovered["wall_s"], 2)
                                                 if recovered else None,
                         "cleared_at_s": round(cleared["wall_s"], 2) if cleared else None})
    consecutive = 0
    for outcome in outcomes:
        if outcome["status"] != "cleared":
            break
        consecutive += 1
    return {"trace": str(trace), "max_x_m": round(max(row["x"] for row in rows), 3),
            "blocks_cleared": sum(b["status"] == "cleared" for b in outcomes),
            "consecutive_cleared": consecutive,
            "full_course_complete": consecutive == len(outcomes),
            "blocks_mounted": sum(b["mounted_at_s"] is not None for b in outcomes),
            "blocks_recovered_later": sum(b["recovered_later_at_s"] is not None
                                          for b in outcomes),
            "blocks": outcomes}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--terrain", type=Path, default=DEFAULT_TERRAIN)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = score(args.trace, args.terrain)
    body = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(body)
    print(body, end="")


if __name__ == "__main__":
    main()
