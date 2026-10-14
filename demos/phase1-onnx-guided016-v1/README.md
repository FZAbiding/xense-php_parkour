# phase1-onnx-guided016-v1

[播放演示视频](demo.mp4) · [预览图](poster.jpg) · [版本清单及 SHA-256](manifest.json)

这段约 50 秒的 H.264 视频来自 `trial_025` 的**一次真实 MuJoCo 运行**。发布的 `depth_backbone.onnx` 和 `student.onnx` 在默认 12 块台阶路线推理，速度类为 `LOW`；额外方向输入采用 `guided`，短按上限 0.16 秒，没有打开两个新增 guard。视频中展示同次录屏、骨盆轨迹和逐块评分。

严格连续通过 5/12 块，第 6 块尚未到达；运行质量为 `nominal`，仿真中位数 500.4 Hz，但存在一次孤立的 245.6 Hz 报告。它说明本机得到一次有效的五块结果，**尚不代表稳定通过或完整路线复现**。原始录屏、位姿 CSV、评分 JSON、审计和日志保存在 `outputs/reproduction/official_benchmark/trial_025/`。复录规则及评分口径见 [演示视频流程](../../DEMO_VIDEO_WORKFLOW.md)。
