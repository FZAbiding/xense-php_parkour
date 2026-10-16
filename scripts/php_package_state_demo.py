#!/usr/bin/env python3
"""Package a same-trial state replay video with checkable score and provenance."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import shutil
import statistics
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FFMPEG = Path("/tmp/php-ffmpeg/usr/bin/ffmpeg")
FFPROBE = Path("/tmp/php-ffmpeg/usr/bin/ffprobe")


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--other-trial", type=Path, action="append", default=[])
    args = parser.parse_args()
    args.trial = args.trial.resolve()
    package = ROOT / "demos" / args.version
    video = package / "demo.mp4"
    render = json.loads((package / "demo.json").read_text())
    result = json.loads((args.trial / "result.json").read_text())
    score = json.loads((args.trial / "course_score.json").read_text())
    audit = json.loads((args.trial / "audit.json").read_text())
    capture = json.loads((args.trial / "demo_capture.json").read_text())
    if not result.get("interactive_demo") or capture["status"] != "complete":
        parser.error("trial must contain interactive states and a complete raw capture")
    for name, path in (("video", video), ("model", args.trial / "replay_model.mjb"),
                       ("qpos", args.trial / "qpos.csv")):
        if digest(path) != render["sha256"][name]:
            parser.error(f"{name} SHA-256 does not match the render report")
    metadata = json.loads(subprocess.check_output([
        str(FFPROBE), "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,width,height,avg_frame_rate,nb_frames",
        "-of", "json", str(video)]))["streams"][0]
    if metadata["codec_name"] != "h264" or metadata["avg_frame_rate"] != "30/1":
        parser.error("video must be H.264 at 30 fps")
    if int(metadata["nb_frames"]) != render["frames"]:
        parser.error("video frame count differs from render report")
    with (args.trial / "qpos.csv").open(newline="") as stream:
        times = [float(row["wall_s"]) for row in csv.DictReader(stream)]
    gaps = [right - left for left, right in zip(times, times[1:])]
    poster = package / "poster.jpg"
    subprocess.run([str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y",
                    "-ss", str(min(20.0, render["duration_s"] / 2)),
                    "-i", str(video), "-frames:v", "1", "-q:v", "2", str(poster)],
                   check=True)
    # Keep the interactive scene and score evidence with the version. The
    # uncompressed original trial remains in outputs for full log inspection.
    for source_name, target_name in (("replay_model.mjb", "replay_model.mjb.gz"),
                                     ("qpos.csv", "qpos.csv.gz")):
        with (args.trial / source_name).open("rb") as source:
            with (package / target_name).open("wb") as compressed:
                with gzip.GzipFile(fileobj=compressed, mode="wb", filename="",
                                   mtime=0, compresslevel=6) as sink:
                    shutil.copyfileobj(source, sink)
    for name in ("result.json", "course_score.json", "audit.json", "pelvis.csv",
                 "demo_capture.json", "sim.log", "inference.log",
                 "visual_diagnostics.json"):
        shutil.copyfile(args.trial / name, package / name)
    preflight = (args.trial / "preflight.json").is_file()
    if preflight:
        shutil.copyfile(args.trial / "preflight.json", package / "preflight.json")
    shutil.copyfile(args.trial / "demo_capture.mp4", package / "raw_capture.mp4")
    diagnostic = (args.trial / "depth_diagnostic.json").is_file()
    diagnostic_names = ("depth_diagnostic.json", "depth_diagnostic.npz",
                        "qvel.csv", "solver_contacts.jsonl")
    if diagnostic:
        for name in diagnostic_names:
            shutil.copyfile(args.trial / name, package / name)
    other_trials = []
    for folder in args.other_trial:
        folder = folder.resolve()
        other_result = json.loads((folder / "result.json").read_text())
        other_score = json.loads((folder / "course_score.json").read_text())
        other_audit = json.loads((folder / "audit.json").read_text())
        other_trials.append({"trial": str(folder), "status": other_result["status"],
                             "consecutive_cleared": other_score["consecutive_cleared"],
                             "quality": other_audit["quality"]})
    paths = {"video": video, "poster": poster,
             "portable_model": package / "replay_model.mjb.gz",
             "portable_states": package / "qpos.csv.gz",
             "portable_raw_capture": package / "raw_capture.mp4",
             "portable_trajectory": package / "pelvis.csv",
             "portable_result": package / "result.json",
             "portable_score": package / "course_score.json",
             "portable_audit": package / "audit.json",
             "portable_visual_diagnostics": package / "visual_diagnostics.json",
             "source_model": args.trial / "replay_model.mjb",
             "source_states": args.trial / "qpos.csv",
             "raw_capture": args.trial / "demo_capture.mp4",
             "trajectory": args.trial / "pelvis.csv",
             "result": args.trial / "result.json",
             "course_score": args.trial / "course_score.json",
             "audit": args.trial / "audit.json",
             "visual_diagnostics": args.trial / "visual_diagnostics.json",
             "render_script": ROOT / "scripts/php_render_state_video.py",
             "replay_script": ROOT / "scripts/php_replay_demo.py"}
    if diagnostic:
        for name in diagnostic_names:
            paths[f"portable_{name}"] = package / name
            paths[f"source_{name}"] = args.trial / name
    if preflight:
        paths["portable_preflight"] = package / "preflight.json"
        paths["source_preflight"] = args.trial / "preflight.json"
    manifest = {"version": args.version, "trial": str(args.trial),
                "trial_kind": "separate_depth_diagnostic" if diagnostic else "fixed_protocol",
                "method": "full-frame MuJoCo state replay of the same scored trial",
                "source_truth": "qpos.csv and replay_model.mjb sampled during ONNX evaluation",
                "interpolation": "MuJoCo mj_differentiatePos/mj_integratePos",
                "visual_only_changes": "solid tan block colors, dark gray ground, camera/sidebars",
                "input": {"model_sha256": result["model_sha256"],
                          "speed_mode": result["speed_mode"], "steer": result["steer"],
                          "guided_max_pulse": result["guided_max_pulse"],
                          "target_x": result["target_x"],
                          "forward_key": "held W as in prior evaluations"},
                "outcome": {"status": result["status"],
                            "consecutive_cleared": score["consecutive_cleared"],
                            "blocks_cleared_total": score["blocks_cleared"],
                            "max_x_m": score["max_x_m"],
                            "quality": audit["quality"],
                            "sim_fps_median": audit["sim_fps_median"],
                            "policy_fps_median": audit["policy_fps_median"]},
                "video": metadata,
                "state_samples": {"count": len(times),
                                  "median_gap_ms": round(statistics.median(gaps) * 1000, 1),
                                  "max_gap_ms": round(max(gaps) * 1000, 1)},
                "raw_capture": {key: capture[key] for key in
                                ("fps", "frames", "frames_duplicated", "status")},
                "preflight_recorded": preflight,
                "other_trials": other_trials,
                "files": {name: {"path": str(path.relative_to(ROOT)),
                                 "sha256": digest(path)}
                          for name, path in paths.items()}}
    (package / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    steer_description = (
        "仅保持官方前进指令 W，无额外左右修正"
        if result["steer"] == "none"
        else f"额外 `{result['steer']}` 方向修正，短按上限 {result['guided_max_pulse']} 秒"
    )
    diagnostic_note = (
        "这是一条单独的深度/接触诊断试次，额外采集负载可能改变运行条件，"
        "不能并入固定协议成绩分布；旁路深度帧不保证与策略每个 tick 的输入完全相同。\n\n"
        if diagnostic else "")
    preflight_note = (
        "[启动资源预检](preflight.json)保存了这次试验实际采用的门槛、逐次 GPU/CPU 读数"
        "和运行器哈希。\n\n" if preflight else "")
    (package / "README.md").write_text(
        f"# {args.version}\n\n"
        f"[观看 30 fps 实体仿真视频](demo.mp4) · [预览图](poster.jpg) · "
        f"[核验清单](manifest.json)\n\n"
        f"官方 ONNX 权重、默认 12 块台阶；{steer_description}。"
        f"本次试验 `{args.trial.name}` 的严格连续成绩 "
        f"**{score['consecutive_cleared']}/12**，最大前进 x≈{score['max_x_m']} m；"
        f"总通过块数 {score['blocks_cleared']}。运行质量 `{audit['quality']}`，"
        f"仿真速率中位数 {audit['sim_fps_median']} Hz。"
        "视觉颜色和镜头只改变展示，不改变碰撞几何或官方策略。\n\n"
        "视频按同一次评测保存的 `qpos.csv` 与 `replay_model.mjb` 在 MuJoCo 中逐帧回放，"
        "帧间采用关节与四元数安全插值；原始窗口录屏也保留在试验目录。"
        "视频是评测状态的可视化，成绩来自同一次 `pelvis.csv` 的逐块评分。\n\n"
        f"{diagnostic_note}"
        f"{preflight_note}"
        "此目录还包含压缩模型、关节状态、原始窗口录屏与评分依据。"
        "在仓库根目录启动可拖动、缩放的回放：\n\n"
        "```bash\n"
        "/home/xense/miniforge3/envs/php/bin/python scripts/php_open_demo.py "
        f"--trial demos/{args.version}\n"
        "```\n\n"
        "打开终端打印的本机网址。鼠标左键拖动旋转，滚轮缩放；Space 播放/暂停，"
        "R 从头播放，左右箭头快进/后退 5 秒，Home 复位镜头。"
        "回放只使用独立的 `:99` 虚拟显示器；Xvfb 软件渲染占用多个 CPU 核，"
        "请仅在查看时启动，Ctrl-C 随手关闭服务。\n"
    )
    print(json.dumps({"version": args.version, "trial": str(args.trial),
                      "video": str(video), "score": score["consecutive_cleared"],
                      "quality": audit["quality"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
