#!/usr/bin/env python3
"""Turn a captured trial into a labeled, verifiable H.264 demo video."""

from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
FONT = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc")
FONT_BOLD = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc")
SIZE = (1280, 720)
BG = "#0b1220"
FG = "#f1f5f9"
MUTED = "#94a3b8"
GREEN = "#34d399"
BLUE = "#38bdf8"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_BOLD if bold else FONT), size)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for piece in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(piece)
    return value.hexdigest()


def line(draw: ImageDraw.ImageDraw, text: str, xy: tuple[int, int],
         size: int = 24, fill: str = FG, bold: bool = False) -> None:
    draw.text(xy, text, font=font(size, bold), fill=fill)


def slate(title: str, details: list[str], badge: str) -> Image.Image:
    image = Image.new("RGB", SIZE, BG)
    d = ImageDraw.Draw(image)
    d.rounded_rectangle((72, 65, 1208, 655), radius=25, fill="#142238")
    d.rectangle((72, 65, 90, 655), fill=GREEN)
    line(d, badge, (127, 125), 25, BLUE)
    line(d, title, (127, 212), 58, FG, True)
    for i, item in enumerate(details):
        line(d, item, (130, 328 + i * 56), 25, MUTED)
    return image


def load_trace(path: Path) -> list[dict[str, float]]:
    with path.open(newline="") as handle:
        return [{name: float(value) for name, value in row.items()}
                for row in csv.DictReader(handle)]


def draw_frame(frame: np.ndarray, t: float, trace: list[dict[str, float]],
               trace_t: list[float], score: dict, result: dict, version: str,
               trial_name: str) -> Image.Image:
    image = Image.new("RGB", SIZE, BG)
    d = ImageDraw.Draw(image)
    line(d, "PHP Parkour  ·  官方模型 MuJoCo 演示", (30, 18), 29, FG, True)
    line(d, f"{version}  /  {trial_name}", (865, 24), 19, MUTED)
    # Crop only the rendered camera viewport; retain raw recording unchanged.
    height, width = frame.shape[:2]
    camera = frame[:, int(width * 0.255):int(width * 0.745)]
    view = Image.fromarray(cv2.cvtColor(camera, cv2.COLOR_BGR2RGB))
    view.thumbnail((495, 630), Image.Resampling.LANCZOS)
    vx = 34 + (495 - view.width) // 2
    vy = 76 + (630 - view.height) // 2
    image.paste(view, (vx, vy))
    d.rounded_rectangle((25, 68, 538, 711), radius=10, outline="#334155", width=2)
    d.line((558, 68, 558, 696), fill="#334155", width=2)

    index = min(bisect.bisect_right(trace_t, t) - 1, len(trace) - 1)
    row = trace[max(index, 0)]
    cleared = 0
    for block in score["blocks"]:
        if block.get("cleared_at_s") is None or block["cleared_at_s"] > t:
            break
        cleared += 1
    line(d, f"时间  {t:05.1f} 秒", (585, 89), 23, MUTED)
    line(d, f"连续通过  {cleared} / 12", (585, 130), 39, GREEN, True)
    line(d, f"前进 x  {row['x']:+06.2f} m", (587, 205), 23)
    line(d, f"横向 y  {row['y']:+06.2f} m", (873, 205), 23)
    line(d, f"骨盆 z  {row['z']:.2f} m", (587, 244), 23)

    d.rounded_rectangle((582, 300, 1254, 388), radius=13, fill="#18283e")
    for j, block in enumerate(score["blocks"]):
        left = 596 + j * 53
        done = block.get("cleared_at_s") is not None and block["cleared_at_s"] <= t
        d.rounded_rectangle((left, 323, left + 42, 366), radius=8,
                            fill=GREEN if done else "#334155")
        line(d, str(j + 1), (left + (11 if j < 9 else 6), 328), 20,
             BG if done else MUTED, True)
    line(d, "默认 12 块台阶 · 逐块首次出块判定", (590, 398), 21, MUTED)

    # Lateral path and the scoring corridor, using the same raw pelvis trace.
    px0, py0, px1, py1 = 600, 449, 1235, 611
    d.rounded_rectangle((582, 439, 1254, 635), radius=13, fill="#18283e")
    x_limit = max(28.0, score["max_x_m"] + 0.5)
    def point(x: float, y: float) -> tuple[int, int]:
        return (int(px0 + max(0, min(x, x_limit)) / x_limit * (px1 - px0)),
                int((py0 + py1) / 2 - max(-2.5, min(y, 2.5)) / 5 * (py1 - py0)))
    hi = point(0, 1)[1]
    lo = point(0, -1)[1]
    d.rectangle((px0, hi, px1, lo), fill="#173a38")
    for y in (-1, 0, 1):
        yy = point(0, y)[1]
        d.line((px0, yy, px1, yy), fill="#475569" if y else "#64748b", width=1)
    for block in score["blocks"]:
        x_start, x_end = block["x_range_m"]
        if x_start > x_limit:
            break
        xx0, xx1 = point(x_start, 0)[0], point(x_end, 0)[0]
        d.rectangle((xx0, py0, xx1, py1), outline="#64748b", width=1)
    path = [point(sample["x"], sample["y"])
            for sample in trace[:max(1, index + 1):3]]
    if len(path) > 1:
        d.line(path, fill=BLUE, width=3)
    dot = point(row["x"], row["y"])
    d.ellipse((dot[0]-6, dot[1]-6, dot[0]+6, dot[1]+6), fill=GREEN)
    line(d, "横向轨迹：绿色带为 |y|≤1 m", (590, 647), 19, MUTED)
    input_label = (f"{result['steer']} 方向输入，上限 {result['guided_max_pulse']:.2f} 秒"
                   if result["steer"] == "guided" else f"{result['steer']} 方向输入")
    line(d, f"官方 ONNX 推理 · {input_label} · 独立显示器录制", (30, 681), 17, MUTED)
    return image


def render(trial: Path, version: str, output: Path, ffmpeg: Path) -> dict:
    result = json.loads((trial / "result.json").read_text())
    audit = json.loads((trial / "audit.json").read_text())
    score = json.loads((trial / "course_score.json").read_text())
    capture = json.loads((trial / "demo_capture.json").read_text())
    if capture["status"] != "complete" or score["consecutive_cleared"] < 0:
        raise RuntimeError("trial recording or score is incomplete")
    trace = load_trace(trial / "pelvis.csv")
    trace_t = [row["wall_s"] for row in trace]
    if not trace or not ffmpeg.exists():
        raise RuntimeError("trace or FFmpeg missing")
    raw = cv2.VideoCapture(str(trial / "demo_capture.mp4"))
    if not raw.isOpened():
        raise RuntimeError("cannot open captured trial video")
    fps = int(capture["fps"])
    source_frames = int(raw.get(cv2.CAP_PROP_FRAME_COUNT))
    if output.exists():
        raw.release()
        raise FileExistsError(f"versioned demo already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-n",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "1280x720",
               "-r", str(fps), "-i", "pipe:0", "-an", "-c:v", "libx264",
               "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
               "-movflags", "+faststart", str(output)]
    proc = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        intro = slate("当前版本演示", ["官方发布的深度模型 + 学生策略",
                                "MuJoCo 默认 12 块台阶；真实仿真画面",
                                "视频含额外方向修正，逐块成绩以轨迹评分为准"],
                      f"{version}  ·  {trial.name}")
        for _ in range(2 * fps):
            proc.stdin.write(intro.tobytes())
        frames_rendered = 0
        while True:
            ok, frame = raw.read()
            if not ok:
                break
            dashboard = draw_frame(frame, frames_rendered / fps, trace, trace_t,
                                   score, result, version, trial.name)
            proc.stdin.write(dashboard.tobytes())
            frames_rendered += 1
        next_block = next((block for block in score["blocks"]
                           if block["status"] != "cleared"), None)
        next_note = (f"第 {next_block['block']} 块尚未到达"
                     if next_block and next_block["status"] == "not_reached" else
                     f"第 {next_block['block']} 块未通过（{next_block['status']}）"
                     if next_block else "默认路线已通过")
        outro = slate(f"连续通过 {score['consecutive_cleared']} / 12 块",
                      [f"运行质量：{audit['quality']}  ·  仿真中位速率 {audit['sim_fps_median']:.1f} Hz",
                       f"终点 x={score['max_x_m']:.2f} m；{next_note}",
                       "同目录保留原始录屏、骨盆轨迹、评分和日志"],
                      f"{trial.name}  ·  默认地形  ·  官方 ONNX")
        for _ in range(3 * fps):
            proc.stdin.write(outro.tobytes())
        proc.stdin.close()
        stderr = proc.stderr.read().decode(errors="replace")
        if proc.wait() != 0:
            raise RuntimeError(f"FFmpeg encoding failed: {stderr[-1000:]}")
    finally:
        raw.release()
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    manifest = {
        "version": version, "trial": str(trial), "video": str(output),
        "video_sha256": digest(output), "raw_capture_sha256": digest(trial / "demo_capture.mp4"),
        "trace_sha256": digest(trial / "pelvis.csv"),
        "score_sha256": digest(trial / "course_score.json"),
        "audit_sha256": digest(trial / "audit.json"),
        "recorded_at": result["started"], "trial_finished_at": result["finished"],
        "benchmark_script_sha256": result["benchmark_script_sha256"],
        "model_sha256": result["model_sha256"], "terrain": result["terrain_obj"],
        "steer": result["steer"], "guided_max_pulse": result["guided_max_pulse"],
        "approach_guard": result["approach_guard"],
        "guided_reversal_guard": result["guided_reversal_guard"],
        "quality": audit["quality"], "run_status": result["status"],
        "sim_fps_median": audit["sim_fps_median"],
        "sim_fps_min": audit["sim_fps_min"],
        "sim_fps_longest_below_400": audit["sim_fps_longest_below_400"],
        "depth_stale_events": audit["depth_stale_events"],
        "consecutive_cleared": score["consecutive_cleared"],
        "full_course_complete": score["full_course_complete"],
        "fps": fps, "source_frames": source_frames,
        "rendered_frames": frames_rendered + 5 * fps,
        "duration_s": round((frames_rendered + 5 * fps) / fps, 2),
        "capture": capture,
    }
    (output.parent / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ffmpeg", type=Path,
                        default=Path(shutil.which("ffmpeg") or "/tmp/php-ffmpeg/usr/bin/ffmpeg"))
    args = parser.parse_args()
    print(json.dumps(render(args.trial, args.version, args.output, args.ffmpeg),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
