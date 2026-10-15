# 教师训练环境 T0：安装路径与主机影响审计

2026-10-15。此记录只检查安装脚本并准备隔离安装入口；**尚未安装 IsaacSim，也未启动教师训练**。当前 `php` 环境用于已验证的 ONNX/MuJoCo 推理，不能被训练依赖原地覆盖。

仓库固定的 Holosoma 是 `4a0bf04cde5930af5ed59da797568d32be972525`。检查 [PHP 安装入口](../wbt_training/training_runs/setup_env.sh) 和 [Holosoma 安装脚本](../thirdparty/holosoma/scripts/setup_isaacsim.sh) 后发现：

| 项目 | 代码行为 | 本机判断 |
|---|---|---|
| 默认环境名 | `ENV_NAME` 未设置时使用 `php` | 必须显式选 `php-train`，保留推理环境 |
| 安装目录 | Holosoma `source_common.sh` 无条件设为 `$HOME/.holosoma_deps`，会覆盖上层 `CONDA_ROOT` | 仅设置上层 `CONDA_ROOT` 不足以实现工作区隔离 |
| 系统包 | 安装脚本调用 `sudo apt install -y cmake build-essential` | 本机 `cmake`、`make`、`g++`、`build-essential` 已有；没有理由为 T0 再改系统包 |
| 大型依赖 | 新建 Conda/Python 3.11 环境，安装 PyTorch CUDA 12.8、IsaacSim 5.1、IsaacLab v2.3.0 和 Holosoma | 下载/磁盘/编译成本尚未测量；当前 `/home` 可用约 76 GB，开始前必须留足余量 |
| 日志 | 训练启动脚本默认 `LOGGER=wandb` | T1 工程短跑可显式 `LOGGER=disabled` 本地记录；正式对照需固定日志方式和有效配置 |

已用 [准备脚本](../scripts/php_prepare_training_overlay.py)在被 Git 忽略的 `outputs/training_setup/holosoma_overlay/` 生成安装脚本的小型副本，`src` 指向原始固定提交。相对于上游只做两项安装层修改：让 `source_common.sh` 从 `PHP_TRAIN_WORKSPACE` 取工作区路径；把直接的 `sudo apt install` 改为检查 `cmake`/`make`/`g++` 是否存在。原始与副本 SHA-256 记录在 `outputs/training_setup/overlay_manifest.json`。这**不改变训练算法或机器人代码**，也没有运行复制出来的安装脚本。`bash -n` 检查通过。未来若上游提交或安装脚本变化，准备脚本会拒绝静默套用旧补丁。

进一步核对了 [IsaacLab v2.3.0 的 `isaaclab.sh`](https://raw.githubusercontent.com/isaac-sim/IsaacLab/v2.3.0/isaaclab.sh)：`--install` 会调用 `install_system_deps`，其中只有找不到 `cmake` 时才走 `sudo apt-get update/install` 分支。本机 `cmake` 存在，因此按当前主机状态不会进入这个已知的系统包分支。这是对安装脚本的静态审查，**不是完整安装已成功或绝无其他副作用的保证**。

执行 T0 前必须显式设置 `ENV_NAME=php-train`、`PHP_TRAIN_WORKSPACE=$PWD/outputs/training_setup/workspace`、`CONDA_ROOT=$PHP_TRAIN_WORKSPACE/miniconda3`、`HSSIM_PYTHON=$CONDA_ROOT/envs/php-train/bin/python` 和 `HOLOSOMA_LOCAL_DIR=$PWD/outputs/training_setup/holosoma_overlay`。这些变量须指向同一工作区，不能直接照抄上游默认安装命令。下一个实际动作是确认下载体量和磁盘余量，在办公负载较低时用隔离环境执行安装。安装完成后记录 `python`、PyTorch、IsaacSim、IsaacLab、Holosoma 版本，以及导入 G1/地形和最小物理步的结果；`php` 推理环境应继续通过现有 ONNX 验证。只有 T0 通过，才能运行 [计划](../NEXT_STAGE_PLAN.md)中的低环境数 T1 短跑。
