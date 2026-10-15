# phase1-onnx-w-only-v3

[观看 30 fps 实体仿真视频](demo.mp4) · [预览图](poster.jpg) · [核验清单](manifest.json)

官方 ONNX 权重、默认 12 块台阶；仅保持官方前进指令 W，无额外左右修正。本次试验 `trial_032_w_only` 的严格连续成绩 **1/12**，最大前进 x≈14.249 m；总通过块数 1。运行质量 `nominal`，仿真速率中位数 499.8 Hz。视觉颜色和镜头只改变展示，不改变碰撞几何或官方策略。

视频按同一次评测保存的 `qpos.csv` 与 `replay_model.mjb` 在 MuJoCo 中逐帧回放，帧间采用关节与四元数安全插值；原始窗口录屏也保留在试验目录。视频是评测状态的可视化，成绩来自同一次 `pelvis.csv` 的逐块评分。

此目录还包含压缩模型、关节状态、原始窗口录屏与评分依据。在仓库根目录启动可拖动、缩放的回放：

```bash
/home/xense/miniforge3/envs/php/bin/python scripts/php_open_demo.py --trial demos/phase1-onnx-w-only-v3
```

打开终端打印的本机网址。鼠标左键拖动旋转，滚轮缩放；Space 播放/暂停，R 从头播放，左右箭头快进/后退 5 秒，Home 复位镜头。回放只使用独立的 `:99` 虚拟显示器；Xvfb 软件渲染占用多个 CPU 核，请仅在查看时启动，Ctrl-C 随手关闭服务。
