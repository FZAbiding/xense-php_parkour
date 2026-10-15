# PHP 下一阶段复现路线与执行记录

更新时间：2026-10-15。目标是把“发布模型是否能在本机复现”与“按公开配方重新训练能达到什么水平”分开验证。每次改变权重、控制输入或仿真接口都分配版本号，至少交付一段**同次评测状态生成的视频**、可交互回放、逐块评分和运行质量审计；不以挑选最好片段代替成绩分布。

## 当前证据与判断

| 事实 | 证据 | 含义 |
|---|---|---|
| 发布学生 ONNX 已在 MuJoCo 跑通 | [v1](demos/phase1-onnx-guided016-v1/README.md)、[v2](demos/phase1-onnx-guided016-v2/README.md) | 环境/接口跑通，但没有完成默认 12 块路线 |
| `guided` 人工方向修正最好一次严格连续 5/12 | 025，质量 `nominal`；030、031 分别 2/12、1/12 | 5/12 不是稳定成绩；025 与 030/031 使用的脚本/显示路径不同，也不构成严格同条件对照 |
| 无额外左右修正的 W-only 基线按现行证据流程完成 | [v3 视频与清单](demos/phase1-onnx-w-only-v3/README.md)：032，1/12，质量 `nominal`；第二块首次出块 y=−1.342 m | 这只是一条基线，说明早期横向漂移值得优先分析；不能据此估计成功率或断言 `guided` 的因果收益 |
| 五份公开 motion/terrain 数据可用 | [官方训练说明](https://github.com/amazon-far/php_parkour/blob/main/wbt_training/README.md)、[官方发布页](https://github.com/amazon-far/php_parkour/releases/tag/training-motion-examples-v1)；本机逐文件 SHA-256 验证通过 | 共 296 组配对动作/地形，可直接作为五个单技能教师的训练输入 |
| 官方发布物没有原始教师训练 checkpoint | [学生发布页](https://github.com/amazon-far/php_parkour/releases/tag/student-assets-v1)、[训练说明](https://github.com/amazon-far/php_parkour/blob/main/wbt_training/README.md) | 当前不能执行“从官方教师 `.pt` 接着训练”；公开 ONNX 学生也不是可恢复 PPO/critic/优化器状态的训练 checkpoint |

截至本记录，本机是 RTX 4090 24 GB、内存 125 GiB、`/home` 可用约 78 GB；`php` 环境有 PyTorch、ONNX Runtime、MuJoCo，但**没有 IsaacSim**。以上是一次快照，不承诺长训练期间始终有同样空闲资源。训练与评估均要照顾共享办公主机；重负载任务只在资源门槛通过时运行，用独立环境，不占用办公桌面。

## 优先级 1：把发布 ONNX 的成绩测准

**问题**：现在最大的证据缺口不是“再调一个方向短按参数”，而是早期 1–3 块表现波动很大，且旧最好试次与新交互试次的运行脚本 SHA、显示路径、目标距离有差异。先冻结同一版代码、同一官方 OBJ、同一模型 SHA、同一速度类和输入规则，才有资格比较 W-only 与 `guided`。

1. **固定协议**：使用当前 `php_official_benchmark.py` 的同一提交和 `--interactive-demo`，默认 12 块台阶，官方双 ONNX，`speed_mode=low`，`target_x=27.4`、`max_seconds=60`；对照组只保持 W，实验组额外 `--steer guided --guided-max-pulse 0.16`。两组其余参数一致。先不同时加入新的 guard、改相机、改关节增益或换地形。`target_x=27.4` 只观察前五块，**不能验证第六块或完整路线**。
2. **控制初值和共享负载**：每次记录起始骨盆位置、偏航、速度、关节状态、深度首帧时间、脚本/模型/地形 SHA。当前只把偏航绝对值 ≤2° 且质量 `nominal` 的试次纳入主表；被排除的试次仍保留日志。GPU 忙碌时延后运行，仿真连续两次低于 400 Hz 或深度过期则停止并记作运行质量问题。`nice` 和 `:99` 独立显示继续沿用。若底层仿真存在不可控初始随机性，采用交错运行顺序降低时间/负载偏差，**不把它称为严格配对随机种子试验**。
3. **先做小样本，再扩大**：两组各至少 3 条合格轨迹，按交错顺序执行；记录每块首次出块的 y/z、连续通过数、是否站稳、首次偏航/横向速度分叉点。若趋势仍不清晰，再补到各 10 条并报告每个结果的计数分布及不确定性；样本太少时不写“成功率提高”。避免按成绩挑视频：每个版本保留全部原始试次，代表视频预先规定取合格试次中连续通过数的中位档，并公开清单。v3 的 032 已是 W-only 第一条，不能拿它直接与不同运行路径的 025 宣称改进或退化。
4. **先诊断，再改控制**：如果两组都在第 2 块附近偏航/侧移，先核对深度预处理、相机外参、指令映射、执行器顺序/缩放、初始释放和地形接触；如果只在 `guided` 后恶化，分析方向事件的触发时刻和响应。只有找到可重复的差异，才修改一个因素并分配新版本号。
5. **按关卡推进**：同条件多次能稳定通过前 3 块后，目标改到第 6–8 块；随后才用 x≈65 m 的完整路线设置测 12 块。完整复现的验收是默认路线连续通过 12 块、末块后继续行进并站稳，再多次重复，而不是 `max_x` 到达某个数。当前骨盆几何评分仍要辅以视频/接触检查，不能直接等同于论文在 IsaacSim 或真机上的指标。

**每个版本的固定交付**：30 fps 实体障碍视频、可旋转/缩放的状态回放、原始录屏、`qpos.csv`、`pelvis.csv`、`course_score.json`、`audit.json`、模型/地形/脚本 SHA 与所有试次成绩表。沿用 [演示视频流程](DEMO_VIDEO_WORKFLOW.md)；画面只来自同次评测保存的状态，不插补虚构动作。

## 优先级 2：验证从头训练的可行性，不把可运行当成复现

公开资料的准确名称是**单技能 privileged teacher**（有参考动作和仿真地形等特权观测的 RL 教师），再把多位教师蒸馏到统一深度学生。现在发布的是学生推理 ONNX 与五份训练数据，未见可恢复训练的公开教师 `.pt`。如果日后拿到教师 checkpoint，可增加“从 checkpoint 评估/继续训练”的分支；目前主路线应是按公开配方**从零训练教师**，然后训练学生。拿 ONNX 作为动作标注做模仿可以研究，但不是官方教师后训练，也缺少 critic/优化器状态，不能叫严格复现。

已完成的数据准备：下载 `motions-locomotion`、`motions-low-step`、`motions-high-step`、`motions-low-climb-76`、`motions-high-climb-76` 到被 Git 忽略的 `outputs/training_assets/`。分别含 100、56、60、40、40 对 motion NPZ / terrain NPY，合计 296 对、解压约 587 MiB；官方 `release-assets.json` 的逐文件校验全部通过。下载 low-climb 时出现过一次网络读取超时，原下载器未留下半成品，重试后验证成功。样本 NPZ 有 `joint_pos`、`joint_vel`、刚体位姿/速度、29 个关节名和 15 维命令；这证明格式能读取，不证明物理教师已学会跟踪。

下一道门槛按以下顺序执行：

| 门槛 | 工作 | 通过条件与不通过时的决策 |
|---|---|---|
| T0：隔离环境 | 在新环境安装仓库固定 Holosoma + IsaacSim 5.1，不破坏推理用 `php`；记录版本、依赖冲突、磁盘增量 | 能导入 IsaacSim、加载 G1/地形、通过最小仿真。若空间/驱动或依赖不满足，先修环境，不启动长训练 |
| T1：单技能短跑 | 用 `motions-low-step` 和官方 `g1-wbt-terrain-ref-noscale` 做几十个环境、少量迭代的 smoke；监控显存、CPU、磁盘、秒/迭代与办公负载 | 可以完成采样、PPO 更新、存盘和从 checkpoint 恢复。缩小环境数只作工程验证，**不当成官方规模成绩** |
| T2：教师能力 | 在资源允许的机器上按代码配方训练一个完整 low-step 教师，随后独立评估，再扩展到其余四个技能 | 每个技能都有完整配置/数据哈希、训练曲线、失败案例、IsaacSim 评估和视频；只有足够的教师能力才进入学生蒸馏 |
| T3：深度学生 | 固定五位教师及数据顺序，先用短跑验证纯 DAgger 的标签链路，再按默认 `FINETUNE=1` 做 DAgger + PPO；导出双 ONNX | IsaacSim 评估、ONNX 接口检查、MuJoCo sim2sim 的逐块成绩与版本视频三者齐备，且与发布 ONNX 在相同测试条件下比较 |

代码当前默认教师 `4096` 并行环境、`20,000` 迭代；学生 DAgger + PPO preset 是 `2048` 环境、`30,000` 迭代，纯 DAgger 变体为 `10,000` 迭代。[配置](wbt_training/config_values/experiment.py)、[训练入口](wbt_training/README.md)。这些是**配方目标**，不是对这张 24 GB 4090 的可运行承诺。T1 必须实测显存峰值和秒/迭代，之后才能估算 5 位教师 + 学生所需时长；若默认并行数无法容纳，降低并行数得到的是“资源受限变体”，要单独标注。[论文](https://arxiv.org/html/2602.15827v2)表中的学生 20,000 迭代与本仓库当前 30,000 preset 不完全相同，之后应同时保存论文与代码两个配置快照。

## 近期执行队列与不做的捷径

当前已完成：官方资产状态核验、五份数据下载及完整 SHA-256 检查、W-only 032 试次的 `nominal` 审计、[v3 演示](demos/phase1-onnx-w-only-v3/README.md)。接下来优先执行同脚本 W-only / `guided` 交错复测与首个偏离点分析；并在不占用办公环境的独立训练环境里完成 T0/T1 可行性验证。T1 数据已准备好，无需先做 motion matching；不能在没有教师 checkpoint 的情况下把公开学生 ONNX 直接称作可“后训练”的官方模型。完整五教师训练和学生训练要等 T1 的资源测量、训练输出可恢复、单技能教师确实学到技能之后才排期。

可复核命令：

```bash
/home/xense/miniforge3/envs/php/bin/python scripts/download_assets.py motions-low-step \
  --destination outputs/training_assets/motions-low-step --verify
/home/xense/miniforge3/envs/php/bin/python scripts/php_score_course.py \
  demos/phase1-onnx-w-only-v3/pelvis.csv --output /tmp/php-v3-score-check.json
/home/xense/miniforge3/envs/php/bin/python scripts/php_open_demo.py \
  --trial demos/phase1-onnx-w-only-v3
```
