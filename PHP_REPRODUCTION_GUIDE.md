# PHP Parkour 复现记录与入门

本文面向做过 π0.5 等 VLA 推理复现、尚未接触人形机器人全身控制和强化学习的读者。这里的“复现 demo”是运行项目发布的 **MuJoCo + 深度相机 + ONNX 学生策略**，并不等于重新训练论文中的教师和学生，也不等于验证真机表现。命令均从本仓库根目录执行。

## 本次复现的范围与机器

项目源码：`amazon-far/php_parkour`，PHP 提交 `1710564612e451d3188aaa49857006af97c02acf`，固定的 Holosoma 子模块提交 `4a0bf04cde5930af5ed59da797568d32be972525`。机器为 Ubuntu 24.04、NVIDIA RTX 4090 24 GB、驱动 580.126.09；创建的 mamba 环境名为 `php`，Python 3.11.17。官方发布的学生模型是 `depth_backbone.onnx` 和 `student.onnx`，下载器对压缩包和两个文件做 SHA-256 校验。

本机已运行发布的学生策略，并把测试从首块台阶延伸到官方默认 12 块路线。按严格首次离开判据，当前有两次在正常仿真速率下连续越过 4 块；一次连续越过 5 块的记录伴随仿真持续降速，尚需复验。尚未完成整条路线，也未重新训练或验证真机成功率。证据与问题见文末“实测结果”和[试验流水账](PHASE1_TRIAL_LOG.md)。

## 先建立一张地图

```text
人类动作片段 → 重定向为 G1 动作 → motion matching 拼出长轨迹
                                         ↓
                              每类动作的 RL 教师
                                         ↓
                   DAgger 模仿 + PPO 奖励 → 单个深度视觉学生
                                         ↓
                 深度图 + 本体状态 + 速度指令 → 29 个关节目标
                                         ↓
                         PD 控制器 → MuJoCo 中的 G1
```

第一步是**造参考动作**：动作匹配在数据库里找当前姿态和未来期望轨迹最接近的动作帧，把走路、跑步、跨台阶、攀爬等片段接成较长的运动，并配好障碍物。它在这里是离线生成训练数据的工具，demo 运行时不在每帧搜索动作数据库。

第二步是**让参考动作在物理世界里可执行**。一条关节轨迹只是期望姿态，不能保证脚底不打滑、手碰到障碍物后不失稳。教师在仿真中通过强化学习学会跟踪轨迹，可以看到参考轨迹、骨盆的全局位置/速度和附近地形高度等训练时才有的信息。动作是关节位置目标，由较低层的 PD 控制器算力矩。全身控制指双腿、腰、双臂共同参与平衡、接触和越障；这里的策略是整体控制的一部分，不是单独规划脚步的模块。

第三步是**把多个教师压成一个能看深度图的学生**。学生看到机器人本体状态（关节角和角速度、身体角速度/重力方向等）、速度方向指令和相机深度图；它没有教师的全局状态和参考轨迹。深度骨干网络先把 `58 × 87` 深度图编码成向量，学生网络再输出 29 个关节目标。DAgger 的关键是让学生用自己的动作走到新状态，随后由教师对这些状态给出示范，减轻只模仿固定轨迹时的分布偏移。论文还加入 PPO：模仿误差小并不保证翻过障碍，例如攀爬时少给一点瞬时力矩就可能卡在墙边；按整段动作是否成功给奖励，可以纠正这种局部误差。论文的损失写为 `L = λ_PPO L_PPO + λ_D L_D`，训练中逐步调整权重。

与熟悉的 VLA 作个对照：VLA 常从图像和语言任务输出一段末端执行器/关节动作，重点在语义任务泛化；PHP demo 接收深度图、本体状态和人工给的速度/方向命令，输出短周期关节目标，重点在动态接触、平衡和越障。它没有语言理解，也没有 π0.5 那样的通用物体操作任务。二者都是“观测 → 策略 → 动作”的闭环，但 PHP 的闭环周期、接触约束和失败模式更接近低层运动控制。

如果刚接触强化学习，可以把一次仿真循环理解成：机器人看到观测 `o_t`，策略给出动作 `a_t`，物理引擎推进一个时间步并给出下一帧观测和奖励 `r_t`。反复运行形成一段 rollout，PPO 用这些数据更新策略，让累计奖励提高。在 PHP 的教师阶段，奖励主要约束动作跟踪、关节范围、碰撞和动作变化；在学生阶段，DAgger 提供教师动作标签，PPO 提供越障结果的反馈。这里的“奖励”只在训练时使用；运行已训练好的 ONNX 时不再计算 PPO 更新。

`29 DoF` 是 G1 的 29 个受控关节自由度，不等于仿真状态向量的总长度。骨盆作为自由浮动的基座还有位置、姿态、线速度和角速度。策略输出的也不是电机力矩本身：位置目标经过关节 PD 控制器，按位置误差和速度误差产生力矩。这样可以把学习问题限制在关节目标层，同时保留高频物理控制。

一个容易混淆的词是 **sim2sim**：这里先在 IsaacSim 相关训练栈中得到学生，再把导出的 ONNX 放到 MuJoCo 运行。两套模拟器的物理和传感器实现不同，所以 MuJoCo demo 能运行，是跨模拟器验证的一步；它仍不足以独立证明论文中的真机成功率。

论文中的相机随机外参、深度噪声、传感延迟和障碍物几何随机化，都服务于从仿真到真机的鲁棒性。这些扰动会让学生在训练时见到“没那么理想”的输入，减少它只适应某一种完美渲染的风险。复现公开 ONNX demo 能验证发布策略的运行链路，无法重做这些训练阶段的消融实验。

## 环境与模型

```bash
git submodule update --init --recursive thirdparty/holosoma
mamba create -n php python=3.11 pip -c conda-forge -y
mamba activate php
uv --no-config pip install --python "$CONDA_PREFIX/bin/python" \
  --default-index https://pypi.org/simple \
  'torch>=2.4,<3' 'mujoco>=3,<4' mujoco-python-viewer \
  -e ./thirdparty/holosoma/src/holosoma \
  -e ./thirdparty/holosoma/src/holosoma_inference
# G1 本地仿真桥接器使用此 SDK；缺它会报 No module named 'unitree_interface'
uv --no-config pip install --python "$CONDA_PREFIX/bin/python" \
  --default-index https://pypi.org/simple 'far-unitree-sdk==0.1.6'
python scripts/download_assets.py student --destination outputs/reproduction/student
python scripts/download_assets.py student --destination outputs/reproduction/student --verify
python -m pip check
```

模型落在 `outputs/reproduction/student/`。训练环境还需 IsaacSim、训练数据、较长时间的多环境 RL 训练；本 demo 只用发布的 ONNX，因而无需 W&B 登录或教师 checkpoint。

仓库现有的 `run_php_sim.sh` 和 `run_php_inference.sh` 会 `source` Holosoma 自己的激活脚本，而这些脚本默认指向 `~/.holosoma_deps/miniconda3` 下的 `hsmujoco` / `hsinference`。因此**只执行 `mamba activate php` 再运行原启动器，并不能保证进程真的使用 `php`**。下方采用直接调用 `php` 环境解释器的命令；安装、实测和若需附加依赖的说明见后面的记录。

## 运行 demo

从仓库根目录，在两个终端分别执行。终端 1 启动仿真，看到 `DepthShmPlugin created 'depth_img_shm' ... shape=(1, 1, 58, 87)` 后再启动终端 2。两个进程需在同一台机器，且图形桌面可用。

```bash
# 终端 1：从仓库根目录执行
PHP_ROOT="$PWD"
cd "$PHP_ROOT/thirdparty/holosoma"
"/home/xense/miniforge3/envs/php/bin/python" src/holosoma/holosoma/run_sim.py \
  robot:g1-29dof \
  sensor.d435i_front_depth:g1-d435i-front-depth \
  plugin.depth:depth-shm-d435i \
  terrain:terrain-load-step \
  --robot.asset.xml-file g1/g1_29dof_halfspherehand.xml \
  --simulator.config.bridge.enabled=True \
  --simulator.config.sim.fps=500 \
  --simulator.config.virtual-gantry.length=0.3
```

```bash
# 终端 2：从仓库根目录执行
PHP_ROOT="$PWD"
cd "$PHP_ROOT/thirdparty/holosoma"
"/home/xense/miniforge3/envs/php/bin/python" \
  src/holosoma_inference/holosoma_inference/run_policy.py \
  inference:g1-wbt-distillation-d435i \
  --task.interface lo \
  --task.model-path "['$PHP_ROOT/outputs/reproduction/student/depth_backbone.onnx','$PHP_ROOT/outputs/reproduction/student/student.onnx']"
```

推理端应报告 `DepthShmSensor attached to 'depth_img_shm' shape=(1, 1, 58, 87)`。在 MuJoCo 窗口逐次按 `8` 放低悬挂机械架，**等脚接触地面、机器人仍直立**再按 `9` 解除；在**推理终端**按 `]` 启动策略，按住 `w/s` 控制前后，`a/d` 控制斜向，`q/e` 控制较大转向，`=` 切换速度；MuJoCo 窗口 `Backspace` 可重置。键盘焦点会影响哪个程序收到按键。本机从初始绳长 0.3 m 按了 9 次 `8`，绳长变为 1.2 m，骨盆从约 1.05 m 降到约 0.785 m，随后解除 gantry 并稳定站立。这里的判断依据是**脚先承重且姿态稳定**，不是机械套用 9 次；过早解除会让机器人从空中落下，绳长放得太长也可能在启动策略之前侧翻。退出时先停推理进程，再停仿真进程；重启仿真前确认旧进程已退出，以免深度共享内存残留。

### 办公机器上的隔离显示器

本次后续测试没有占用正在使用的主桌面。机器原本没有 `Xvfb`，我把与已安装的 `xserver-common` 匹配的 Ubuntu `xvfb` 包**解包到 `/tmp/php-xvfb`**，没有安装系统包；这个目录在本机仍可用。清理 `/tmp` 后可这样恢复（包版本要与本机 `xserver-common` 相匹配；本次是 `2:21.1.12-1ubuntu1.5`）：

```bash
cd /tmp
apt download 'xvfb=2:21.1.12-1ubuntu1.5'
mkdir -p /tmp/php-xvfb
dpkg-deb -x /tmp/xvfb_2%3a21.1.12-1ubuntu1.5_amd64.deb /tmp/php-xvfb
/tmp/php-xvfb/usr/bin/Xvfb :99 -screen 0 1600x1000x24 -nolisten tcp -noreset
```

在这个 Xvfb 命令保持运行时，用上述两个终端的命令启动仿真与推理，但给仿真命令加 `DISPLAY=:99 MUJOCO_GL=egl`，给推理命令加 `DISPLAY=:99`。`MUJOCO_GL=egl` 使 MuJoCo 离屏深度渲染走 EGL；本机不加它时，Xvfb 下的一次行走测试出现了物理循环停滞，加上后完成了两次首块台阶穿越。是否为同一个根因尚未证明，但在这台机器上这是有效配置。两个程序之间仍使用 `--task.interface lo`，不要改成物理网卡。

由于虚拟显示器没有实体窗口，可在仓库根目录用 [隔离窗口按键脚本](scripts/php_virtual_viewer.py) 控制 MuJoCo 并保存完整窗口画面：

```bash
mamba activate php
python scripts/php_virtual_viewer.py tap 8 --count 9   # 分九次放低，确认脚已触地
python scripts/php_virtual_viewer.py tap 9              # 解除 gantry
# 到推理终端按 ]；确认日志出现 Depth distillation policy started
python scripts/php_virtual_viewer.py hold w 8           # 前进约 8 秒
python scripts/php_virtual_viewer.py screenshot outputs/reproduction/current_view.png
```

脚本默认只连接 `:99`，拒绝 `:0`/`:1` 主桌面。在虚拟显示器里按键不会打断日常办公。复位可在推理终端按 `i` 回到站立保护，再执行 `python scripts/php_virtual_viewer.py tap BackSpace`，等站稳后重新按 `]`。

## 代码阅读路线

| 想看什么 | 从哪里开始 |
|---|---|
| 生成动作与地形 | `motion_matching/README.md`，`motion_matching/motion_matching/run.py`，`scenarios/builtin.py` |
| 教师/学生训练入口 | `wbt_training/README.md`，`training_runs/run_terrain_teacher.sh`，`run_terrain_warp_distill.sh` |
| 观测、奖励与动作 | `wbt_training/config_values/terrain.py`，`experiment.py`，`depth_distillation.py` |
| DAgger 与 PPO 的组合 | `wbt_training/utils/student_teacher.py`，`config_values/motion_command.py` |
| MuJoCo 和 ONNX 推理 | 根目录两个 `run_php_*.sh`，`wbt_training/DEPLOY.md`，Holosoma 的 `run_sim.py` / `run_policy.py` |

建议先跑 ONNX demo，沿着“深度图 → 深度编码 → 观测拼接 → 关节目标”看推理代码；然后再读奖励和教师观测，最后尝试运动匹配生成数据。若直接从 PPO 公式或 IsaacSim 训练配置入手，很难把三阶段对应起来。

## 实测结果与问题

此节记录本机实际执行的步骤，不把未运行的论文训练结果写成复现结果。

**结论：发布模型的 MuJoCo 视觉控制链路已跑通，G1 在本机两次通过第一块 0.38 m 台阶，并在下台阶后继续直立。** 尚未验证完整跑酷路线或论文成功率。具体证据如下：

| 检查 | 本机结果 |
|---|---|
| 环境 | `mamba` 创建 `php`；Python 3.11.17；`pip check` 输出 `No broken requirements found` |
| 主要运行时 | PyTorch `2.14.1+cu130`，MuJoCo `3.15.0`，ONNX Runtime `1.31.0`，NumPy `1.26.4`，Pinocchio `2.7.0` |
| 模型 | 下载器验证两个文件的 SHA-256；骨干输入 `[1,58,87]`、输出 `[1,32]`；学生输入 `obs=[1,140]` 与 `time_step=[1,1]`，输出 `actions=[1,29]` |
| 仿真 | `DepthShmPlugin` 创建 20,184 字节共享内存，10 Hz 深度渲染；MuJoCo Classic 物理循环约 500 Hz；GUI 窗口出现 G1 和地形 |
| 推理 | `DepthShmSensor` 成功附着；按 `]` 后报告 `Depth distillation policy started`，策略循环约 50 Hz；按住 `w` 时状态从 `stand` 切到 `forward`，松开后回到 `stand` |
| 平地基线 | 解除 gantry 后骨盆高度约 0.784 m，策略前进 4 秒使 x 坐标从约 −0.04 m 到 2.40 m，松键后站稳 |
| 第一块台阶 | 该地形在 x≈4.5–5.5 m、y≈−0.75–0.75 m 的首块障碍顶面高 0.38 m。第一次轨迹中 x≈4.01、5.02、5.99 m 时，骨盆高度分别为 0.794、1.132、0.784 m，横向始终经过台阶范围；第二次 x≈5.00 m 时高度 1.119 m，下台阶后又恢复到约 0.783 m |
| 完整画面 | [首块台阶截图](outputs/reproduction/virtual_on_step.png) 拍到 G1 位于首块台阶上；截图来自 Xvfb 独立显示器，不再被办公窗口遮挡。两次轨迹均有 CSV 留存 |

### 后续：官方模型在默认 12 块台阶路线上的基准测试（2026-10-13）

此前的两次首块台阶演示之后，我把测试延伸到默认地形的后续障碍。`terrain:terrain-load-step` 加载的 `terrain.obj` 包含沿 +X 分布的 **12 块台阶**：第 1、2 块高 0.38 m，第 3、4 块高 0.76 m，之后重复类似组合，最后一块在 x≈60 m。官方发布的两个 ONNX 文件仍是同一对，SHA-256 分别以 `5b22466a` 和 `e426c420` 开头；没有训练或修改模型权重。

新增 [自动运行器](scripts/php_official_benchmark.py) 在独立 `:99` 显示器中启动仿真和推理，按已验证的顺序放低/释放 gantry，从仿真 UDP 位姿消息记录骨盆 `x/y/z` 和朝向，并在跌倒、离开路线、遥测中断或超时时结束。每次试验的 `pelvis.csv`、`result.json`、日志和虚拟显示器截图保存在 `outputs/reproduction/official_benchmark/trial_*/`。例如从仓库根目录运行：

```bash
mamba activate php
python scripts/php_official_benchmark.py --steer none --target-x 17.2 \
  --max-seconds 40 --output outputs/reproduction/official_benchmark/my_trial
python scripts/php_score_course.py \
  outputs/reproduction/official_benchmark/my_trial/pelvis.csv \
  --output outputs/reproduction/official_benchmark/my_trial/course_score.json
```

`--target-x` 只表示到达某个 x 坐标，**不代表越过该处台阶**。新增 [路线评分器](scripts/php_score_course.py) 直接读取 OBJ 中每块台阶的平面四边形：骨盆在台阶投影内、高度至少比台阶顶面高 0.45 m，记为“登上”；此后**首次**前进到台阶最远端 +1.5 m 时，骨盆高度须 ≥0.55 m、横向须 `|y|≤1.0 m`，才记为“越过”。若首次到达时已经偏离、后来又回到路线，则另记 `recovered_later_at_s`，不算严格越过。这里的“登上”是骨盆位姿判定，没有另行核验足底接触，不能证明双脚都落在顶面。这是本次 MuJoCo 测试的可审查操作性判据，不是论文 IsaacSim/真机成功率的复现。画面只能辅助核对，主要结论以位姿轨迹和几何判定为准。

| 试验 | 方向输入 | 最大 x / 结束状态 | 按上述判据的连续结果 |
|---|---|---|---|
| 001 | 仅按住 `w` | 12.04 m，达到 x 目标 | 第 1 块越过，第 2 块已登上；试验在第 2 块后 1.5 m 判据前结束 |
| 002 | 仅按住 `w` | 17.00 m，达到 x 目标 | 第 1、2 块越过；第 3 块 0.76 m 已登上，但下台阶后 y≈1.87 m，未满足越过判据 |
| 003 | 从首块前按 y 偏差长按 `a/d` | 5.04 m，跌倒 | 首块未越过；这种直接纠偏过于激进 |
| 004 | 第 3 块后短按纠偏 | 22.01 m，达到 x 目标 | 只确认第 1 块越过；后面多处从旁边绕过，不能把 x 当作成功 |
| 005 | 仅按住 `w` | 17.21 m，达到 x 目标 | 第 1、2 块越过；第 3 块再次登上，但下台阶后 y≈2.34 m |
| 006 | 障碍间短按 `a/d` | 19.73 m，第四块附近跌倒 | 连续越过第 1、2 块；第 3 块已登上，但首次离开时 y≈1.72 m，后来回到路线 |
| 007 | 第 3 块下台阶后短按纠偏 | 21.65 m，横向离开路线 | 连续越过第 1、2、3 块；第四块前向 y≈−3.02 m 偏出 |
| 008 | 第 3 块后纠偏配置，但尚未触发 | 5.71 m，首块处跌倒 | 首块已登上、未越过；说明同一开局也有波动 |

[前三至四块的俯视轨迹与骨盆高度图](outputs/reproduction/official_benchmark/course_xy.png) 由 `pelvis.csv` 和 OBJ 顶点生成：米色多边形是真实台阶足迹，三条彩色线是试验 002、006、007。图中第 3 块之后一条轨迹向 y 正方向漂移、另一条向 y 负方向漂移，说明简单“只按前进”或迟到的短按纠偏都不能稳定保证下一块对正；下半图显示试验 006 爬上前三块时骨盆高度的变化。可用 `python scripts/php_plot_course.py` 重绘。

为了区分 0.76 m 台阶本身与长路线中的累积偏航，我还做了**单块台阶诊断**：用 [地形生成脚本](scripts/php_make_single_step.py) 从同一官方 OBJ 中抽出第 3 块，只把它沿 x 平移到中心约 5 m；地面、台阶形状和官方 ONNX 均未改。它是自定义诊断地形，不能并入默认路线成绩。

```bash
python scripts/php_make_single_step.py
python scripts/php_official_benchmark.py \
  --terrain-obj outputs/reproduction/official_benchmark/single_high_076.obj \
  --steer none --target-x 7.3 --max-seconds 25 \
  --output outputs/reproduction/official_benchmark/high_new
python scripts/php_score_course.py \
  outputs/reproduction/official_benchmark/high_new/pelvis.csv \
  --terrain outputs/reproduction/official_benchmark/single_high_076.obj
```

两次纯 `w` 试验都登上了这块 0.76 m 台阶；`high_001` 行至 x≈7.32 m，但 y≈1.49 m，未满足离开台阶后仍在路线内的判据；`high_002` 在 x≈7.31 m 时 y≈0.79 m，**满足登上并继续前进 1.5 m 的越过判据**。第二次的骨盆在台阶中心附近达到约 1.49 m，[隔离显示器截图](outputs/reproduction/official_benchmark/high_002/at_05m.png) 也拍到机器人位于台阶上。这个诊断说明高台阶能力在发布模型中存在，但单次结果对落地横向位置仍有波动。

**截至试验 008，最好的严格连续证据是 `007` 的前三块；当时尚未越过第四块。** `006` 曾被旧评分器记作前三块，但首次离开第 3 块时横向偏出，此后才回到路线，因此严格重算为两块；`007` 到第四块的 x 范围时 y 已在其外侧，属于绕过。未观察到模型权重错误或深度输入缺失；主要瓶颈是登上 0.76 m 台阶之后的偏航和人工方向修正时机。`a/d` 是模型已有的方向类别指令，本文的自动纠偏是额外测试控制器，不能算作论文原始策略的一部分；各试验停止目标也不同，样本数很小，不据此报成功率。成功段的物理仿真约 500 Hz、策略约 50 Hz，日志中没有深度过期保护记录。

### 阶段一继续执行：第四、五、六块（2026-10-13）

下一阶段的任务和验收条件写在 [阶段一任务计划](PHASE1_REPRODUCTION_PLAN.md)。本轮继续使用同一对官方 ONNX、官方默认 12 块 OBJ 路线和独立显示器；没有启动第二阶段重新训练。评分器现另外输出 `consecutive_cleared` 与 `full_course_complete`，只从第 1 块开始连续计数，并采用上文的严格首次离开判据，避免把绕行后变大的 x 坐标当成越障。

| 试验 | 输入和终点 | 逐块结果 | 运行质量 |
|---|---|---|---|
| 009 | `predictive`，x≥22.2 m | **连续越过 4 块**，第 4 块为 0.76 m | `nominal`；仿真速率中位数 500.0 Hz，无低于 400 Hz 区间 |
| 010 | 同一方向模式，x≥27.4 m | 连续越过 1 块，此后 y 向负侧漂到约 −3 m | `nominal` |
| 011 | `guided`，x≥27.4 m | **连续越过 5 块** | `sustained_sim_slowdown`；第三块附近有两次连续 400 Hz 以下报告 |
| 012–013 | `guided`，x≥32.3 m | 分别连续越过 2 块、首块即偏出 | `nominal`；012 仍有短时单次降速 |
| 014 | `guided`，x≥32.3 m | 严格连续越过 3 块；第 4、5 块首次离开时偏出，后来回到路线；第 6 块已登上但未越过 | `sustained_sim_slowdown`；曾连续四次低于 400 Hz |
| 015–016 | `guided`，x≥32.3 m | 分别严格连续越过 2 块、2 块；016 第 3 块首次离开时偏出，后来回到路线，还登上第 4 块 | `nominal`；016 有短时单次降速 |
| 017 | 官方 `HIGH` 速度、纯 `w`，x≥22.2 m | 连续越过 1 块，第二块后横向离开 | `sustained_sim_slowdown`；不能据此评价高速模式优劣 |
| 018 | 官方 `LOW` 速度、纯 `w`，第一块后暂停 0.8 秒 | 连续越过 1 块，第二块前跌倒 | `sustained_sim_slowdown`；多数行走区间只有约 200–300 Hz，不能用来评价暂停操作 |
| 019（2026-10-14） | `guided`，计划到 x≥27.4 m | 行走约 7.8 秒仅到 x=1.689 m，尚未接近第一块；自动停止 | `sustained_sim_slowdown`；仿真连续报告 345.1、173.4 Hz，说明当时共享 GPU 负载下不能做有效长程比较 |
| 020（2026-10-14） | `guided`、脉冲上限 0.16 秒，x≥27.4 m | **严格连续越过 4 块**；第 5 块已登上，首次离开时 y=+1.363 m，未越过 | `nominal`；仿真中位数 499.1 Hz、最低 409.8 Hz，策略中位数 50.5 Hz |
| 025（2026-10-14） | `guided`、脉冲上限 0.16 秒，x≥27.4 m；同步录屏 | **严格连续越过 5 块**；第 6 块未到达 | `nominal`；仿真中位数 500.4 Hz，有一次孤立的 245.6 Hz 低速报告；[观看视频](demos/phase1-onnx-guided016-v1/demo.mp4) |

各试验的 `course_score.json`、`audit.json`、`pelvis.csv`、`sim.log`、`inference.log` 在 `outputs/reproduction/official_benchmark/trial_*/`。可复核质量门槛：

```bash
python scripts/php_audit_trial.py outputs/reproduction/official_benchmark/trial_011
python scripts/php_score_course.py outputs/reproduction/official_benchmark/trial_011/pelvis.csv
```

截至 020，**质量合格条件下的最高成绩是严格连续 4/12 块**；严格 5/12 块只在 `011` 观察到一次，但这次伴随持续降速，须复验。后来 025 已取得首次质量合格的五块结果，见下文。[第 4–6 块轨迹对照图](outputs/reproduction/official_benchmark/course_to_sixth.png) 显示，`014` 在第 4 块首次离开时 y≈−1.54 m，在第 5 块首次离开时 y≈+2.54 m；旧评分器允许之后回到路线，曾把它记成 5 块，严格重算只有 3 块。第 6 块上的骨盆升高符合操作性“登上”条件；没有足底接触验证，也没有满足离开后 +1.5 m 的“越过”条件。图可用 `python scripts/php_plot_course.py --trial trial_009 --trial trial_011 --trial trial_014 --max-blocks 6 --output outputs/reproduction/official_benchmark/course_to_sixth.png` 重绘。

`guided` 的短按修正会在部分试验延长路线，但不能消除开局波动或后续偏航；`014` 在第五块后甚至出现约 +60° 到 −50° 的明显转向变化。下一步应在机器负载允许时复验第五块，再逐级推进第 6–8 块。运行器已加入质量保护：行走开始后若连续两次仿真报告低于 400 Hz，或推理日志出现深度帧过期告警，就停止并保留轨迹；离线审计与运行器的 `status` 分开保存。由于此时 GPU 又有其他办公工作负载，新的图形试验暂时停止，避免互相影响。400 Hz 仅是本机质量门槛，并非官方对模型的性能要求。

2026-10-14 的受控追加试验 `019` 证实了这个资源限制：当时 GPU 约 90% 忙碌，行走只持续 7.77 秒，仿真速率连续跌至 345.1、173.4 Hz，运行器按 `sim_fps_low` 自动停止，机器人只到 x=1.689 m。推理仍约 50 Hz，但仿真与策略不再保持预期闭环比例；这轮没有到第一块，不提供越障能力的新证据。输出保存在 `trial_019`，Xvfb、仿真和推理进程均已清理。

轨迹对比给出一个待检验方向：`009` 到 x≈22 m 时 y≈−0.47 m、世界系横向速度约 −0.52 m/s、偏航约 −21°，需要在第五块之前抵消负侧漂移；`011` 在同处 y≈−0.16 m、横向速度接近零，并在第四块后记录两次短按 `a`。为复验已把 `--guided-max-pulse` 加到运行器，并在 `020` 使用 `--steer guided --guided-max-pulse 0.16 --target-x 27.4 --max-seconds 60`。单次试验还不足以判断短脉冲是否整体更稳。

上述 0.16 秒配置随后在 `020` 完成了一次质量合格的实跑：连续四块，且登上第五块，但首次离开第五块时向正侧超出判据 0.363 m。这让正常速率的连续四块从一次增加为两次，没有达到第五块成功。对比 `011` 的第五块通过轨迹，`020` 在 x≈23.1 m 时横向速度已开始回正，控制器仍追加一次 `a`；第五块上偏航约 +37°、横向速度约 +0.6 m/s，出块时无法及时回到中线。运行器现提供可选 `--guided-reversal-guard`，在这种“已经回正、偏航较小”的状态下跳过重复修正。021、022 已带此开关实测，但 021 起始朝向异常、022 在第二块就偏出，均未走到能判断第五块效果的状态。

`021` 曾按 [试验流水账](PHASE1_TRIAL_LOG.md) 中的命令两次进入资源预检，都没有连续空闲窗口；原始采样在 `trial_021/preflight.json` 和 `preflight_75.json`。随后 GPU 空闲，恢复因 `/tmp` 清理而缺失的隔离 Xvfb 后，021 实际运行：物理速率中位数 499.9 Hz，但起始偏航 +5.7°，严格越过 3 块。审计将其标记为 `start_heading_outlier`，不与原始约 0° 开局直接比较。022 加入起始朝向稳定门槛后正常开局、正常速率，却在第二块首次离开时 y=−1.039 m，严格只越过 1 块。023 取消新回正保护仍在第二块首次离开时 y=−1.227 m，严格只越过 1 块。024 针对第二块前的负侧运动新增可选 `--approach-guard`；在 x=8.97 和 10.75 m 两次触发 0.16 秒 `a`，但第二块首次离开仍为 y=−1.096 m，严格只越过 1 块，质量 `nominal`。这些结果说明长路线表现波动尚未解决，不能断言第五块回正保护有效或无效。下一步先在第二块前做固定输入对照和重复样本，找到能稳定走到第四块的条件，再测试第五块。已有的[第五块轨迹对照图](outputs/reproduction/official_benchmark/course_fifth_comparison.png) 用 009、011、020 的原始 CSV 绘制；图中的高度变化和横向偏移展示了“登上”和“首次离开位置”为什么必须分开判断。

025 恢复 `guided`、0.16 秒、无附加 guard，针对用户提出的“每个版本都要有视频”要求，在独立 `:99` 显示器录制新的完整试验。它首次以质量 `nominal` 严格连续通过 **5/12** 块；五块首次出块 y 分别为 +0.458、−0.481、+0.315、−0.466、+0.495 m。仿真中位数 500.4 Hz，策略中位数 50.3 Hz，深度过期 0 次；有一次孤立的 245.6 Hz 低速报告，未形成连续低速。第 6 块尚未到达，完整路线仍未复现。[观看当前版本成片](demos/phase1-onnx-guided016-v1/demo.mp4)；版本、原始录屏、哈希和以后每次复录的流程见 [演示视频流程](DEMO_VIDEO_WORKFLOW.md)。这个单次有效五块结果还需要同条件复验，不能据此宣称稳定成功。

测试期间 GPU 上还有本机其他任务；运行器以 `nice -n 10` 启动，未调用桌面 `:0`/`:1`。一次截图代码曾让 Pillow 使用了默认桌面，产生了一张错误截图；它已被删除，截图函数现显式传入 `xdisplay=:99`，并用 320×240 的独立 Xvfb 黑屏验证。该截图错误**没有影响**同时记录的仿真 UDP 轨迹。后续要想声称“复现官方完整路线”，需在同一地形上连续通过 12 块，逐块保存位姿和有效截图，并重复多次；当前证据不足以这么声称。

诊断文件在 `outputs/reproduction/`：`php-freeze.txt` 是该环境的完整包版本；`sim_virtual_egl.log` 和 `inference_virtual_egl.log` 是成功运行的日志；`step_egl_trace.csv` 和 `step_second_trace.csv` 是两次首块台阶穿越时的骨盆位置轨迹；`virtual_on_step.png` 是第二次走上台阶时的完整窗口截图；`depth_preview.png` 是共享内存深度帧的灰度预览。早期失败运行的日志和截图也在同目录。`outputs/` 被仓库 `.gitignore` 忽略，所以这些文件保留在本机，但不会进入 Git 提交。

本次碰到的具体问题：

1. **官方启动器会切换环境。** `run_php_sim.sh` / `run_php_inference.sh` 默认寻找 Holosoma 自己的 `hsmujoco` / `hsinference`，直接运行它们不会沿用 `mamba activate php`。因此本次用 `php/bin/python` 直接执行同样的 Holosoma 入口。`motion_matching` 另行钉住 NumPy 2.2.6，而 Holosoma 要求 NumPy `<2`；将来复现动作匹配和训练时应按各自官方指南建独立环境，不要在已经跑通 demo 的 `php` 里强装所有阶段。
2. **缺少 Unitree SDK。** 第一次仿真启动在 bridge 初始化时报 `ModuleNotFoundError: No module named 'unitree_interface'`。补装 Holosoma 声明的 `far-unitree-sdk==0.1.6` 后，`Robot bridge initialized successfully`。即使只跑本机 MuJoCo，也要这个 SDK，因为仿真与推理之间使用 Unitree 消息桥。
3. **DDS 有一次短暂初始化失败。** 第一次在已启动仿真后运行推理端，Cyclone DDS 报 `Failed to create domain explicitly`；停止并重新启动推理端后，两端都在本机 `lo` 接口上成功创建域、连接深度共享内存并运行。它是这次观察到的启动故障；目前没有足够证据把根因归为固定的端口冲突或软件缺陷。若复现时遇到同样错误，先退出旧的 PHP 仿真和推理进程，确认没有残留，再按终端 1、终端 2 的顺序重试，保持 `--task.interface lo`。
4. **深度帧可短时变旧。** 有窗口运行期间，策略一次检测到深度帧 0.52 秒未更新，自动进入 stiff hold。之后心跳序号再次递增，按 `]` 可恢复。这个保护避免在失去新深度帧时继续执行动作；日志中的 MuJoCo 500 Hz 仅代表物理循环正常，不能代替检查深度帧心跳。复位和拍图等图形交互可能增加负载，但现有记录不足以证明是它们造成了那次停更。
5. **初期未成功越障，后来定位出不可靠的释放时序。** 早期尝试将 gantry 绳长直接设为 2.0 m，机器人在启动推理前已经侧翻，骨盆只有约 0.14 m 高；另一次在 0.3 m 绳长下直接松开，脚尚未承重，机器人落地失稳。随后改为先启动推理端的站立保护、逐次放低绳长直到骨盆约 0.785 m、确认直立，再解除 gantry 和启动策略，完成了两次首块台阶穿越。早期跟踪相机里“机器人掉到地形下方”的截图不能作为发布模型无法越障的结论。
6. **主桌面截图被其他窗口遮挡。** 用户需要继续办公，因此后续测试转到独立 Xvfb 显示器。Xvfb 的普通软件 GL 路径上有一次物理循环停滞；改用 `MUJOCO_GL=egl` 后，两次短程穿越均保持约 500 Hz 物理循环和约 50 Hz 推理循环，且成功运行的日志没有深度帧过期保护记录。这只说明本机这两次短程测试稳定，不能保证长期运行没有卡顿。

另一个尚未解决的问题是退出稳定性：几次有窗口的仿真在按 Ctrl+C 停止时以 139 结束，早期另一次为 137；一次软件 GL 的 Xvfb 仿真停滞后需要用 SIGTERM 结束。它们发生在测试退出或失败尝试中，不影响上述两次短程越障事实，但不能据此认为长时间运行已经稳定。若需长时间录制，应继续观察 `sim_virtual_egl.log`、深度帧心跳和系统资源。

## 资料

当前演示分两份：旧版 [v1 视频](demos/phase1-onnx-guided016-v1/demo.mp4)记录了最好的一次正常质量严格连续 5/12；新版 [v2 视频与交互回放说明](demos/phase1-onnx-guided016-v2/README.md)用同次评测状态显示实体台阶并提供旋转、缩放，成绩为 2/12。两者都没有复现官方完整路线。具体录制、打包和质量核验步骤见 [演示视频流程](DEMO_VIDEO_WORKFLOW.md)；试次逐项比较见 [试验流水账](PHASE1_TRIAL_LOG.md)。

- [论文：Perceptive Humanoid Parkour](https://arxiv.org/html/2602.15827v1)
- [项目主页](https://php-parkour.github.io/)
- [源码 README](README.md)
- [官方 MuJoCo 部署指南](wbt_training/DEPLOY.md)
