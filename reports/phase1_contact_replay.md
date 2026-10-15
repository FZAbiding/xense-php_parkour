# 032/033 脚与台阶几何接触的离线重建

2026-10-15。用 [重建脚本](../scripts/php_reconstruct_contacts.py)将同次评测保存的 `qpos.csv` 逐帧加载到同次保存的 `replay_model.mjb`，对每帧调用 MuJoCo `mj_forward`，只计脚部碰撞几何与名为 `floor` / `floor_N` 的地形几何之间 `contact.dist ≤ 0` 的接触候选。该回放模型与原模拟使用相同碰撞几何，渲染颜色不同。两份回放模型 SHA-256 相同：`9f1b1e83871af7364fc4008e3c27a80551944c0a3771de67ad963bd23cb6cb64`。逐块统计、首次/末次接触位置、x 检查点和源 `qpos.csv` SHA-256 见 [032 JSON](phase1_contacts_032.json)、[033 JSON](phase1_contacts_033.json)。

| 试次 | 质量 | 第一块脚部接触 | 第二块脚部接触 | 后续接触 | 结果 |
|---|---|---|---|---|---|
| 032，W-only | `nominal` | 47 个采样帧；x≈4.17–5.72 m | **47 个采样帧**；x≈9.30–10.58 m | 无第三块接触 | 第二块之后向负 y 偏出，首次出块 y=−1.342 m |
| 033，`guided` | `nominal` | 43 个采样帧；x≈4.23–5.74 m | **0 个采样帧** | 第三块 225 个采样帧；x≈14.82–15.41 m | 在第二块正 y 侧绕过，第二块未登上 |

在 x≈9.4 和 10 m 的首次状态采样，032 的脚与第二块几何有接触候选；033 的脚只与普通地面 `floor` 接触。两条轨迹都接触并越过第一块，说明更早的分叉需要从第一块出块到第二块入块之间的状态演化查起，而不是把两次失败简单归为同一种“第二块碰撞失败”。这仍**不能证明原因是脚掌接触差异**：接触差异也可能是此前偏航/侧移的结果。033 的额外 `a/d` 首次在 x≈15.29 m 才发送，早期差异已形成。

这里重建的是约 60 Hz 已记录姿态上的**几何接触候选**，没有保存当时的 `qvel`、求解器接触冲量、法向力、策略动作、深度帧或真正逐物理步的接触序列。把未采样到的瞬时接触记为“没有”有漏检风险；表中的 0 只表示记录的帧中没有。第二块是否被判通过仍以 [原始逐块评分](../PHASE1_TRIAL_LOG.md)为准，视频用于核对动作与障碍物相对位置。

离线复核命令：

```bash
/home/xense/miniforge3/envs/php/bin/python scripts/php_reconstruct_contacts.py \
  --trial outputs/reproduction/official_benchmark/trial_032_w_only \
  --output reports/phase1_contacts_032.json
/home/xense/miniforge3/envs/php/bin/python scripts/php_reconstruct_contacts.py \
  --trial outputs/reproduction/official_benchmark/trial_033_guided \
  --output reports/phase1_contacts_033.json
```

下一步补 W-only 有效试次时沿用同一仿真入口和质量门槛；同时另设诊断版本记录少量原始 `qvel`、接触冲量与深度时间戳，以核对是否在第一块后就发生传感器/接触时序差异。新增诊断记录会改变运行脚本哈希，不能直接混入现有固定协议的成绩分布。

034/035 曾在三次短间隔 GPU 预检通过后于行走中降速，所以下次批次运行器默认改为连续 30 秒、每隔 5 秒采样，共 7 次 GPU 利用率均低于 50% 才启动；每条试次前重新预检。此门槛只能降低占用波动风险，仍须保留在线连续低速保护和事后审计。
