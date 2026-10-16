# PHP Parkour 版本演示视频流程

目标：**每个可展示版本都有一段真实仿真视频和可核对的实验记录**。视频负责展示动作，成绩只来自同一次运行的 `pelvis.csv` 与 `php_score_course.py`；不能用视觉印象或最大前进距离代替逐块评分。当前只覆盖第一阶段官方 ONNX 推理，不涉及重新训练。

## 2026-10-16 新版本索引

| 版本与 30 fps 视频 | 源试次 | 严格连续成绩 | 解释 |
|---|---|---:|---|
| [W-only v4 视频](demos/phase1-onnx-w-only-v4/demo.mp4) · [交互包](demos/phase1-onnx-w-only-v4/README.md) | 038 | 2/12，`nominal` | W-only 固定协议三条合格样本 `[1,2,2]` 的中位档 |
| [`guided` v3 视频](demos/phase1-onnx-guided016-v3/demo.mp4) · [交互包](demos/phase1-onnx-guided016-v3/README.md) | 037 | 2/12，`nominal` | 仅两条合格样本 `[2,1]`，取首条并公开全部结果 |
| [深度诊断 v1 视频](demos/phase1-onnx-depth-diagnostic-v1/demo.mp4) · [交互包](demos/phase1-onnx-depth-diagnostic-v1/README.md) | 诊断 002 | 3/12，`nominal` | 被动深度/求解器接触记录的**独立诊断**，不计入固定协议 |
| [`guided` v4 视频](demos/phase1-onnx-guided016-v4/demo.mp4) · [交互包](demos/phase1-onnx-guided016-v4/README.md) | 044 | 1/12，`nominal` | viewer 启动修复后的新代码哈希首条正式试次 |
| [W-only v5 视频](demos/phase1-onnx-w-only-v5/demo.mp4) · [交互包](demos/phase1-onnx-w-only-v5/README.md) | 045 | 1/12，`nominal` | 同一修复后代码；包内 `preflight.json` 记录显式 60% GPU 启动门槛，第二块正侧绕过 |

这五套均包含 1280×720、H.264、30 fps 视频、原始窗口录制、状态/模型压缩包、评分与哈希清单。使用 `/home/xense/miniforge3/envs/php/bin/python scripts/php_open_demo.py --trial demos/<版本ID>` 在本机交互浏览，可拖动旋转、滚轮缩放，关闭后释放 `:99`。深度诊断包额外附逐帧深度、关节速度和接触采样。视频是**同次评分轨迹的状态回放**，按关节空间插值至 30 fps；这消除了旧 8 fps 窗口录像的卡顿，但不意味着策略以 30 Hz 运行或动作被重新执行。详细证据和失败试次见[前轮报告](reports/phase1_cohort_depth_and_startup_2026-10-16.md)及[045–047 续行报告](reports/phase1_followup_045_047_2026-10-16.md)。

## W-only 基线 v3（2026-10-15）

[30 fps 实体仿真视频](demos/phase1-onnx-w-only-v3/demo.mp4) · [交互回放与成绩说明](demos/phase1-onnx-w-only-v3/README.md) · [版本清单](demos/phase1-onnx-w-only-v3/manifest.json)。官方双 ONNX、默认 12 块台阶，只保持 W 前进，不额外发送左右方向修正。032 试次质量 `nominal`，严格连续 **1/12**：第 2 块首次出块 y=−1.342 m，超出 ±1 m 判据。物理仿真中位数 499.8 Hz，策略中位数 50.7 Hz，深度过期 0 次。它是单次 W-only 基线，不代表稳定成功率；与旧版额外 `guided` 的 5/12 不能直接解释为方向修正的因果收益。下一阶段的复测协议见 [计划](NEXT_STAGE_PLAN.md)。

交互启动方式与 v2 相同，只需把 `--trial` 换成 `demos/phase1-onnx-w-only-v3`。录屏、完整关节状态和评分来自同次试验；30 fps 成片是状态回放，不是重新执行策略。

## 交互版 v2（2026-10-14）

[30 fps、1280×720 实体台阶视频](demos/phase1-onnx-guided016-v2/demo.mp4) · [预览图](demos/phase1-onnx-guided016-v2/poster.jpg) · [版本说明](demos/phase1-onnx-guided016-v2/README.md) · [哈希与评分清单](demos/phase1-onnx-guided016-v2/manifest.json)。视频从 `trial_030_interactive` **同一次评测保存的完整关节状态**在 MuJoCo 中重放，帧间按 MuJoCo 关节空间插值；对应 8 fps 原始窗口录屏和原始轨迹仍在 `outputs/reproduction/official_benchmark/trial_030_interactive/`。画面是重放可视化，不是新一轮策略运行，评分仍取原试次的 `pelvis.csv`。

在仓库根目录运行可拖动、缩放的交互回放，终端会打印本机网址：

```bash
/home/xense/miniforge3/envs/php/bin/python scripts/php_open_demo.py \
  --trial demos/phase1-onnx-guided016-v2
```

浏览器左键拖动可旋转，滚轮缩放；Space 播放/暂停、R 从头播放、左右箭头跳 5 秒、Home 复位镜头。v2 目录已打包压缩的场景模型、关节状态、原始录屏、轨迹与评分文件，交互回放不依赖被 Git 忽略的 `outputs/`。只使用独立的 `:99` 虚拟显示器和 `127.0.0.1` 本机端口；关闭终端的 Ctrl-C 会清理回放、Xvfb、VNC 和网关进程。Xvfb 上的 MuJoCo 查看器使用软件显示，暂停时仍会占用多个 CPU 核，因此**只在需要交互时运行，结束后关闭**，不会常驻占用办公主机。如果 `/tmp` 被清理，先按本机已记录的依赖方式恢复 `/tmp/php-xvfb`、`/tmp/php-interactive`；视频文件本身无需这些临时组件即可观看。

**本次成绩为严格连续 2/12，质量 `nominal`**：试次 030 总共通过 3 块但第 3 块首次出块横向越界，因此连续计数停在 2；x≈25.683 m 时离开路线。同配置复测 031 为连续 1/12，质量也为 `nominal`。此前 v1 的 025 仍是目前最好的一次质量合格成绩 5/12；画面升级不代表控制性能提高，也未复现官方完整路线。

旧视频中台阶像细线，原因是评测器按住 W 前进时同时触发了 MuJoCo 查看器的线框快捷键。纯粹发送 W、W、S 会让官方离散方向策略切回站立，短测 029 已证实，不能作为显示修复。v2 保留原有 W 输入；只在独立回放里关闭调试视锥、给原碰撞网格上实体颜色，并隐藏侧栏。旧片每秒 8 帧，加上画面被裁切和缩小，造成明显顿挫和难以识别障碍；v2 根据原试次约 37 Hz 状态采样生成 30 fps 视频，采样最大间隔见版本清单。物理循环仍约 500 Hz，策略约 50 Hz；视频帧率不等于仿真速率。

后续每个可交付版本先同时保存原始录屏、`qpos.csv`、`replay_model.mjb`、`pelvis.csv`、评分和质量审计，再运行：

```bash
MUJOCO_GL=egl /home/xense/miniforge3/envs/php/bin/python \
  scripts/php_render_state_video.py --trial "$trial" \
  --output "demos/$version/demo.mp4" --fps 30 --width 1280 --height 720
/home/xense/miniforge3/envs/php/bin/python \
  scripts/php_package_state_demo.py --trial "$trial" --version "$version"
```

`php_render_state_video.py` 使用与交互回放相同的模型和关节状态，`php_package_state_demo.py` 验证 H.264/30 fps、帧数、SHA-256，并生成海报、README 和 manifest。原始窗口录屏仍作为时序证据保留；若只使用旧的 8 fps 窗口录屏剪辑，必须明确标为旧流程，不能声称 30 fps 真实采样。

## 旧版 v1（当前最好成绩）

| 项目 | 内容 |
|---|---|
| 版本 ID | `phase1-onnx-guided016-v1` |
| 对应试验 | `trial_025`，2026-10-14；官方 `depth_backbone.onnx` + `student.onnx`，默认 12 块台阶 OBJ |
| 操作输入 | 官方 `LOW` 速度类，额外 `guided` 左右短按，最大 0.16 秒；`approach_guard` 和 `guided_reversal_guard` 均关闭 |
| 成绩 | 严格连续通过 **5/12**，到 x=27.422 m 停止，第 6 块尚未到达；不代表完整路线成功 |
| 质量 | `nominal`：物理速率中位数 500.4 Hz，策略中位数 50.3 Hz，深度过期 0 次；**有一次孤立的 245.6 Hz 报告**，没有连续低速区间 |
| 视频 | [观看 H.264 成片](demos/phase1-onnx-guided016-v1/demo.mp4)，1280×720、8 fps、49.88 秒，无音频；[预览图](demos/phase1-onnx-guided016-v1/poster.jpg) |
| 原始证据 | [版本清单](demos/phase1-onnx-guided016-v1/manifest.json)、[未经排版的原始录屏](outputs/reproduction/official_benchmark/trial_025/demo_capture.mp4)、[逐块评分](outputs/reproduction/official_benchmark/trial_025/course_score.json)、[运行审计](outputs/reproduction/official_benchmark/trial_025/audit.json)、[原始轨迹](outputs/reproduction/official_benchmark/trial_025/pelvis.csv) |

成片前 2 秒说明版本和来源，中间是同一次 MuJoCo 运行的录屏：只裁切界面侧栏，右侧用**同一次原始轨迹**绘制骨盆位置与横向路线，不补画机器人动作、不拼接其他试验。末尾 3 秒列出实际评分与质量。原始录屏是 359 帧、44.88 秒，补帧 0；成片是 399 帧。`manifest.json` 记录模型、运行脚本、原始录屏、成片的 SHA-256 与关键参数。可观看的成片、预览图与 manifest 放在未忽略的 `demos/版本ID/`；原始试验文件位于被 `.gitignore` 忽略的 `outputs/`，转移到别的机器复核时须一起归档。

## 后续每个版本的固定规则

1. **先定版本，再跑试验。** 模型权重、地形、控制输入规则或关键运行脚本发生变化，就分配新的版本 ID 和全新试验目录；不覆盖旧视频。版本清单必须写明官方模型 SHA-256、地形、输入策略、脚本 SHA-256、录制时间与试验编号。仅改变片头/排版也使用新的版本后缀，保留原录屏、原成片与可追溯关系。
2. **只录制隔离显示器。** 使用 `:99` 上的 MuJoCo 实时画面，运行器拒绝 `:0`/`:1`；办公桌面不参与录制。仿真与录屏都以 `nice -n 15` 运行；GPU 忙碌时推迟试验，运行器在连续两次仿真低于 400 Hz 或深度帧过期时自动停止。即便视频好看，失败或降速试验也照实保留并标记，不能写成有效成功。
3. **同次运行闭环。** 录屏器等待该试验的 `pelvis.csv` 出现才开始，等 `result.json` 落盘才结束。之后用固定评分器生成 `course_score.json`，核对 `audit.json`。成片只从该试验的录屏、轨迹、评分生成；版本清单给出所有路径与哈希。
4. **交付前检查。** 核对视频可解码为 H.264、时长与录制报告相符、开头/中间/结尾三处画面正常；逐块首次离开成绩、质量、模型来源和额外人工方向输入必须在说明中可见。单次示范只说明“这次做到了什么”；稳定性要另做同条件重复试验并报告分布。

## 复做当前配置

在仓库根目录执行，使用已有的 `php` 环境、已下载的官方 ONNX 和独立 Xvfb。`ffmpeg` 需支持 `libx264`；本机本次从 Ubuntu 包解包到 `/tmp/php-ffmpeg/usr/bin/ffmpeg`，没有修改系统安装。若 `/tmp` 被清理，可安装或重新提供支持 H.264 的 FFmpeg，并将路径传给 `php_render_demo.py --ffmpeg`。

```bash
trial=outputs/reproduction/official_benchmark/trial_NEW
version=phase1-onnx-guided016-vNEXT
mkdir -p "$trial"
nice -n 15 /home/xense/miniforge3/envs/php/bin/python scripts/php_record_demo.py \
  --trial "$trial" --display :99 --fps 8 --width 960 >"$trial/record.log" 2>&1 &
recorder_pid=$!
nice -n 15 /home/xense/miniforge3/envs/php/bin/python scripts/php_official_benchmark.py \
  --steer guided --guided-max-pulse 0.16 --target-x 27.4 --max-seconds 60 \
  --demo-view --display :99 --output "$trial" >"$trial/benchmark.log" 2>&1
wait "$recorder_pid"
/home/xense/miniforge3/envs/php/bin/python scripts/php_score_course.py \
  "$trial/pelvis.csv" --output "$trial/course_score.json"
/home/xense/miniforge3/envs/php/bin/python scripts/php_render_demo.py \
  --trial "$trial" --version "$version" \
  --output "demos/$version/demo.mp4"
```

运行前先检查目标试验目录和版本目录为空、GPU 负载适合；若仿真未启动步行或录屏失败，保留日志排错，不执行成片脚本。`php_record_demo.py` 产生原始录屏与帧数报告；`php_render_demo.py` 生成带中文说明的 H.264 成片和 `manifest.json`。原始画面与轨迹仍以 `trial_NEW` 为准。复做不保证每次都达到 5/12；下一步是用**相同配置**重复运行，统计正常质量下的逐块成绩，再决定是否修改控制器。

这套演示是本机 MuJoCo 中运行官方发布模型的 sim2sim 证据，其中 `guided` 是额外的方向指令控制；它不能直接等同于论文中 IsaacSim 或真实机器人的成功率。关于项目概念、环境和已知问题，见 [复现指南](PHP_REPRODUCTION_GUIDE.md)。
