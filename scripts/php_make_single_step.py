#!/usr/bin/env python3
"""Extract one raised block from the bundled PHP demo OBJ as a diagnostic course.

The policy and block geometry are unchanged; only the chosen block's X position
is shifted so it is the first obstacle encountered from the default spawn.
"""

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "thirdparty/holosoma/src/holosoma/holosoma/data/terrains/terrain.obj"
DEFAULT_OUTPUT = ROOT / "outputs/reproduction/official_benchmark/single_high_076.obj"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--block", type=int, default=3, help="1-based source block index")
    parser.add_argument("--center-x", type=float, default=5.0)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    lines = args.source.read_text().splitlines()
    vertices = [tuple(map(float, line.split()[1:])) for line in lines if line.startswith("v ")]
    faces = [list(map(int, line.split()[1:])) for line in lines if line.startswith("f ")]
    if (len(vertices) - 8) % 8 or args.block < 1 or args.block > (len(vertices) - 8) // 8:
        parser.error("expected an eight-vertex ground slab followed by eight-vertex blocks")

    offset = 8 * args.block  # zero-indexed first vertex of selected block
    block = vertices[offset:offset + 8]
    source_center = sum(v[0] for v in block) / len(block)
    shift = args.center_x - source_center
    selected = vertices[:8] + [(x + shift, y, z) for x, y, z in block]
    ground_faces = [face for face in faces if all(1 <= index <= 8 for index in face)]
    block_faces = [[index - offset + 8 for index in face] for face in faces
                   if all(offset + 1 <= index <= offset + 8 for index in face)]
    if not ground_faces or not block_faces:
        parser.error("could not find ground or selected-block faces")

    header = (f"# Diagnostic mesh: source block {args.block} shifted "
              f"{shift:.6f} m along X\n")
    body = "".join(f"v {x:.8f} {y:.8f} {z:.8f}\n" for x, y, z in selected)
    body += "".join("f " + " ".join(map(str, face)) + "\n"
                    for face in ground_faces + block_faces)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(header + body)
    print(args.output, f"block_height={max(v[2] for v in block):.2f}m")


if __name__ == "__main__":
    main()
