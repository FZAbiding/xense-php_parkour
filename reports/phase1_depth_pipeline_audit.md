# 发布 ONNX 的 MuJoCo 深度输入链路核对

2026-10-15。对象是 032/033 两条质量合格的同入口试次及仓库固定 Holosoma 提交。此处检查**配置和日志能证明的接口一致性**；历史试次没有保存实际深度像素或逐帧时间戳，不能靠静态代码审查排除视觉时序问题。

| 链路 | 已核对的运行配置/行为 | 证据 |
|---|---|---|
| MuJoCo 相机 | `g1-d435i-front-depth`，固定在 `torso_link`，106×60、垂直视场 58.5953°，深度 | [相机 preset](../thirdparty/holosoma/src/holosoma/holosoma/config_values/wbt/g1/sensor.py)；`php` 环境导入的运行配置一致 |
| 生产者 | `depth-shm-d435i`，先裁掉顶部 2 行与左右各 4 列，再双三次抗锯齿缩放至 87×58，裁剪 0.3–3.0 m 并归一化；独立线程 10 Hz，`latency_frames=0` | [插件 preset](../thirdparty/holosoma/src/holosoma/holosoma/config_values/plugin.py)、[实现](../thirdparty/holosoma/src/holosoma/holosoma/simulator/plugins/depth_shm_plugin.py)；本机运行配置实测这些参数 |
| 传输与消费 | `depth_img_shm`，float32、形状 `(1,1,58,87)`；学生每个策略 tick 拷贝最新帧，深度 backbone 输出 latent 再与本体观测/方向命令拼接 | [消费端](../thirdparty/holosoma/src/holosoma_inference/holosoma_inference/sensors/depth_shm.py)、[策略端](../thirdparty/holosoma/src/holosoma_inference/holosoma_inference/policies/depth_distillation.py) |
| 两次实跑 | 032/033 日志均显示生产者建立 20,184 字节共享内存、10 Hz 渲染线程、消费者按 `(1,1,58,87)` 附着；两次 `audit.json` 的深度过期事件均为 0 | 本机 `outputs/reproduction/official_benchmark/trial_032_w_only/`、`trial_033_guided/` 的 `sim.log`、`inference.log`、`audit.json` |

代码中还有一个 `RsD435iConfig.randomize_placement=True`，属于 [Warp/训练相机配置](../thirdparty/holosoma/src/holosoma/holosoma/sensors/warp/camera_config/d435i_depth_config.py)。这次 MuJoCo 命令使用的是上表的 `CameraSensorConfig` 固定挂载，不能仅凭那个训练配置就说 032/033 的 MuJoCo 相机每次随机移动。两次保存的回放模型哈希相同，也没有发现由不同相机模型文件造成的差异。

当前**没有发现明显的 preset 选错、输入张量尺寸或裁剪范围不匹配**。这并不证明每帧输入正确：深度共享内存只保留最新图，历史像素和实际生产/消费时间未归档；`depth_stale_events=0` 仅表示没有触发过期保护，不能保证所有帧恰好对齐。下一轮主成绩试次继续保持相同代码和质量门槛；另开诊断版本时对第一块出块至第二块入块区间保存少量原始深度帧、生产者序号/时间和策略消费时间，并把诊断负载对仿真 FPS 的影响单独审计。诊断试次的脚本哈希与固定协议不同，不混入同条件成绩表。

已准备 [被动深度录制器](../scripts/php_record_depth_diagnostic.py)：通过生产者每帧发送的 heartbeat 序号，在旁路读取共享内存，保存归一化深度帧、发布端 heartbeat 时间和接收端时间到 `depth_diagnostic.npz`，并写完整性摘要。它不改官方推理进程；[本地假生产者回归测试](../tests/test_php_record_depth_diagnostic.py)通过。**尚未在真实仿真运行**，因为本轮共享 GPU 始终高负载。heartbeat 时间是帧发布后的时间，旁路采集帧也不能保证就是某个策略 tick 读取的同一份像素；要精确对齐策略输入，仍需在策略消费点做单独取证。
