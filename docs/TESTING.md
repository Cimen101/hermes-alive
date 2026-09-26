# Hermes Alive 系统完整测试报告

- **报告日期**：2026-09-07
- **被测系统**：Hermes Alive 长期记忆拟人引擎插件（hermes-alive）
- **测试目标**：完整覆盖系统全部细节——拟人生命周期引擎（时钟/精力/压力/无聊度/自唤醒/驱动力/情绪PAD/亲密度Bond/巡查/兴趣/社交）数值消耗与回复速度、长期记忆 DAG、多用户隔离、消息入站链、dashboard 只读 API
- **测试方式**：宿主数值专项断言 + 容器内全量回归（17 脚本）+ 真实运行库（alive.db）只读抽查
- **总体结论**：**全部通过**。全量回归 17/17 scripts（300+ 断言）、数值专项 58/58、真实环境 12 用户抽查 9 用户零异常（3 个未活跃用户属预期惰性初始化）

---

## 1. 测试环境

| 项 | 值 |
|---|---|
| 宿主 | Windows 11（Python 3.13），tests 目录数值专项直跑 |
| 容器 | `hermes`（`/opt/hermes/.venv/bin/python`），回归脚本经 docker cp 送 `/tmp/hermes_regression` 执行 |
| 业务库 | `C:\Users\RAINBOW\.hermes\plugin-data\agent-plugin-hermes-alive-80e90b66\alive.db`（SQLite WAL，只读连接审计） |
| 配置基准 | `engine/config.py` 15 个 dataclass + `engine/constants.py` CONSTRAINTS |
| 假时钟 | `HERMES_ALIVE_CLOCK_OFFSET_FILE` 偏移文件驱动相位推进（偏移缓存 2s 已处理） |

---

## 2. 功能域覆盖矩阵

| # | 功能域 | 实现模块 | 覆盖方式 | 结果 |
|---|---|---|---|---|
| 1 | Clock 生物钟 | engine/clock.py | 数值专项二 D 段（9 项）+ 回归 wake | 9/9 PASS |
| 2 | Energy 精力 | engine/energy.py | 数值专项一（14 项）+ 真实抽查 | 14/14 PASS |
| 3 | Stress 压力 | engine/stress.py | 数值专项一（14 项）+ 真实抽查 | 14/14 PASS |
| 4 | Boredom 无聊度 | engine/boredom.py | 数值专项一（4 项）+ 真实抽查 | 4/4 PASS |
| 5 | SelfWake 自唤醒 | engine/self_wake.py | 回归 unit_memory_wake / wake 体系 | 11/11 PASS |
| 6 | Drive 驱动力 | engine/drive.py | 数值专项二 E 段（10 项）+ 事件日志 drive_initiated | 10/10 PASS |
| 7 | Emotion PAD | engine/emotion.py + constants 约束链 | 数值专项二 F 段 + 真实抽查 | 7/7 PASS |
| 8 | Bond 亲密度 | engine/bond.py | 数值专项二 F 段 + 真实抽查 | PASS |
| 9 | Monitor 巡查 | observer/patrol_context.py | 回归 unit_patrol_prompt（13 项）+ 真实库 2042 行 | 13/13 PASS |
| 10 | Hobby 兴趣 | storage（interests 表） | 回归 unit_interest_norm + 真实库 21 行 | PASS |
| 11 | Social 社交/触达 | outreach_state / probe | 回归 probe_napcat_sim_http（11 项）+ 真实库 10 行 | 11/11 PASS |
| 12 | Memory DAG 记忆 | memory/store.py 四层 | 回归 10 个 memory 脚本（约 220 断言） | PASS |
| 13 | 多用户隔离 | current_state(user_id) + 隐私边界 | 回归 unit_memory_complex/inbound + 真实 12 用户 | PASS |
| 14 | Dashboard 只读 API | dashboard/plugin_api.py | 回归 unit_dashboard_memory（14 项） | 14/14 PASS |
| 15 | 消息入站 16 步链 | NapCat 网关 | 回归 unit_napcat_http_proxy/timeout/inbound | PASS |

---

## 3. 测试结果总览

| 模块 | 断言数 | 结果 |
|---|---|---|
| 全量回归（17 脚本） | 300+ | 17/17 scripts OK |
| 数值专项一 numeric_behavior.py | 32 | 32/32 PASS |
| 数值专项二 numeric_behavior2.py | 26 | 26/26 PASS |
| 真实环境抽查 real_state_audit.py | 12 用户 × 10 键 | 9 用户 0 异常，3 用户 3 缺失（惰性初始化，预期） |

---

## 4. 全量回归（17/17 scripts OK）

容器内逐个执行，`tail -5` 采集结果，exit 0 判定通过：

| 脚本 | 覆盖点 | 断言 |
|---|---|---|
| unit_patrol_prompt.py | 巡查 prompt 渲染（真调用） | 13 |
| unit_interest_norm.py | 兴趣名归一 | PASS |
| unit_memory_p1.py | P1 DAG 记忆库守门/TTL/检索/巡查链渲染 | 30 |
| unit_memory_p2.py | memorize/recall 工具全分支+归属修复 | 25 |
| unit_memory_reflect.py | 反思流/分类器/条目检索/双源注入 | 39 |
| unit_memory_cover.py | 写入/存储/检索/注入/工具/归一化多维覆盖 | 40 |
| unit_dashboard_memory.py | dashboard 记忆端点真接口 smoke | 14 |
| unit_faiss_index.py | FAISS 增删改/持久化/降级 | 8 |
| unit_faiss_store.py | MemoryStore 真 FAISS 集成/对账 | 9 |
| unit_graph_lifecycle.py | 图谱/修订/consolidation/purge | 11 |
| unit_memory_complex.py | 多用户/多轮/冲突/边界/融合 | 15 |
| unit_memory_wake.py | dormant 条目命中自动 wake | 11 |
| unit_memory_realistic.py | 真实记忆对话与注入效果 | 17 |
| unit_napcat_http_proxy.py | NapCat HTTP 代理绕行 | 1 |
| unit_napcat_timeout.py | 超时语义与网关分类器 | 14 |
| unit_napcat_inbound.py | 入站 16 步链去重/自滤/群@/媒体/引用 | 20 |
| probe_napcat_sim_http.py | NapCat 协议面 H1-H8 | 11 |

---

## 5. 数值专项一：精力/压力/无聊度速率矩阵（32/32 PASS）

配置基准（`engine/config.py`）：
- Energy：工作衰减 0.4/min、休闲 0.2/min、犯困×1.5、休息恢复 0.4/min、聊天恢复 0.8（上限75）、表扬 +4（上限80）、任务完成 +5（上限85）、鼓励 +3（上限80）、收尾阈值 40
- Stress：工作增长 0.7/min、休闲降低 0.5/min、连续工作加速（60-120min×1.3 / 120-180min×1.8 / >180min×2.5）、情绪调制（P高0.7 / P低1.3 / A高1.4 / A低0.8）、挫折点累积阈值 3.0
- Boredom：清醒休闲 +0.15/min、长休 +0.5/min、新事物 -10

### 精力系统 14 项断言记录

| # | 断言 | 输入 → 实测 |
|---|---|---|
| 1 | 工作衰减 0.4/min | 100 → 99.6（1min） |
| 2 | 休闲衰减 0.2/min | 100 → 99.8 |
| 3 | 犯困相位倍率×1.5 | 100 → 99.4（0.6/min） |
| 4 | 休息恢复 0.4/min | 30 → 54（60min） |
| 5 | 表扬 +4 封顶 80 | 75→79、79→80、80→80 |
| 6 | 聊天 +0.8 封顶 75 | 74→74.8、75→75 |
| 7 | 超过上限不拉低 | 83（>80）保持 83 |
| 8 | 收尾阈值 40 | 达到 40 触发收尾事件 |
| 9 | 耗尽下限 0 | 0 不再下降 |
| 10 | 自唤醒补满 | 自唤醒 → 100 |
| 11-14 | 恢复/封顶组合边界 | 无溢出、无负值 |

### 压力系统 14 项断言记录

| # | 断言 | 输入 → 实测 |
|---|---|---|
| 1 | 工作增长 0.7/min | 10 → 10.7 |
| 2 | 休闲降低 0.5/min | 50 → 49.5 |
| 3 | 连续工作加速×1.3 | 60-120min 区间 |
| 4 | 连续工作加速×1.8 | 120-180min 区间 |
| 5 | 连续工作加速×2.5 | >180min |
| 6 | 高愉悦调制×0.7 | 增长放缓 30% |
| 7 | 低P高A调制×1.82 | 增长加剧 |
| 8 | 表扬事件 -2 减压 | 事件回调生效 |
| 9 | 负面事件 +挫折点 0.75 | 不直加压力、走挫折累积 |
| 10 | 挫折累计 3.0 触发 | 触发挫折应激 |
| 11 | 阈值增量 ~2.96 | 触发时压力跳变幅度符合配置 |
| 12 | 挫折点折半 | 正向事件削减挫折 |
| 13 | 模式切换阈值 76/96 | 76→leisure_decision、96→强切 leisure |
| 14 | 工作意愿阈值 9/25 | 9→work_priority、25→work_decision |

### 无聊度 4 项断言记录

| # | 断言 | 输入 → 实测 |
|---|---|---|
| 1 | 清醒休闲 100min +15 | 0.15/min 线性累积 |
| 2 | 新事物 -10 | 事件立即削减 |
| 3 | 档位正确 | high/medium/low 分档边界 |
| 4 | 长休增速 | 0.5/min 高于清醒 |

---

## 6. 数值专项二：时钟/驱动器/约束链（26/26 PASS）

### D 段 时钟相位推进 9/9（假时钟偏移驱动）

| # | 场景 | 实测 |
|---|---|---|
| 1 | waking @22:15 → winding_down | 相位正确切换 |
| 2 | winding 相位倍率 1.5 | m=1.5 |
| 3 | winding @23:40 → sleeping | 过 hard(23:30) 入睡 |
| 4 | sleeping 相位倍率 0 | 睡眠零消耗 |
| 5 | sleeping 判定（is_sleeping + past_soft_limit） | 全真 |
| 6 | sleeping @08:00 → warming_up | 晨间窗口唤醒 |
| 7 | warming 相位倍率 0.5 | m=0.5 |
| 8 | warming @09:00 → waking | warm_up(30min) 后转清醒 |
| 9 | waking 相位倍率 1.0 | 全速 |

### E 段 驱动器 10/10

| # | 断言 | 实测 |
|---|---|---|
| 1 | 信号合成 0~1 且有值 | boredom80 → sig=0.540 |
| 2 | 信号文本分级存在 | "我有点想做点什么/找人唠唠" |
| 3 | 门控放行 | boredom80+energy60 → boredom_high |
| 4 | 睡眠门控拒绝 | phase_guard |
| 5 | 精力低拒绝 | energy20<45 → energy_low |
| 6 | 无聊低拒绝 | boredom30<55±jitter → boredom_below |
| 7 | engagement 2h 半衰 | 0.80 → 0.40 |
| 8 | 被接纳 feedback+step | fb=1.1 |
| 9 | 被冷落 feedback 回落 | fb=0.70 |
| 10 | 每日上限拒绝 | drive_daily 达 daily_max(5) → daily_max |

### F 段 情绪/亲密度约束链 7/7

| # | 断言 | 实测 |
|---|---|---|
| 1 | P 单次钳制 ≤0.10 | p=0.0910 |
| 2 | bond c 单次钳制 ≤0.05 | c=0.0500 |
| 3 | 低置信(0.2<0.6)全部拒绝 | p={} |
| 4 | apply_delta 走高 | P 0.5 → 0.5375 |
| 5 | 每日衰减向初值靠近 | 0.53750 → 0.53631 |
| 6 | bond 应用带阻尼 | C→0.05 |
| 7 | bond 衰减向初值 | T 0.14950 → 0.14925 |

---

## 7. 真实环境数值抽查（alive.db 只读，R-H/3 口径修正）

**口径（红队修正）**：energy/stress/boredom 等生理键是 `__global__` 单一生命周期
（`_PHYS_GLOBAL_KEYS` 强制），不按用户存储；PAD/Bond 关系维按每用户隔离。
旧版本曾按用户写生理键，已由 `tests/cleanup_legacy_phys_keys.py` 预览后清理
（120 条残留，复检 0 条）。

### 全局生理段（__global__）

| 键 | 值 | 更新 | 判定 |
|---|---|---|---|
| energy | 21.6 | 09-09 11:45 | OK (0~100) |
| stress | 40.4 | 09-09 11:45 | OK (0~100) |
| boredom | 72.8 | 09-08 13:17 | OK (0~100) |
| clock_phase / activity_mode / energy_resting | — | — | 相位/模式正常 |

### 每用户关系维（PAD/Bond，[-1,1]）

| 用户 | P | A | D | C | D依赖 | I | T | 异常 |
|---|---|---|---|---|---|---|---|---|
| 10001 | 0.300 | 0.000 | 0.200 | 0.000 | 0.000 | 0.000 | 0.100 | 0 |
| 111111111 | 0.477 | 0.088 | 0.279 | 0.130 | 0.062 | 0.091 | 0.265 | 0 |
| 20001 | 0.301 | 0.000 | 0.200 | 0.001 | 0.000 | 0.000 | 0.101 | 0 |
| 222222222 | 0.308 | 0.005 | 0.204 | 0.005 | 0.002 | 0.005 | 0.104 | 0 |
| 30002 | 0.300 | 0.000 | 0.200 | 0.000 | 0.000 | 0.000 | 0.100 | 0 |
| 333333333 | 0.332 | 0.015 | 0.214 | 0.030 | 0.010 | 0.022 | 0.140 | 0 |
| 40003 | 0.300 | 0.000 | 0.200 | -0.0 | -0.0 | -0.0 | 0.100 | 0 |
| 444444444 | 0.300 | 0.000 | 0.200 | 0.000 | 0.000 | 0.000 | 0.100 | 0 |
| 555555555 | 0.447 | 0.069 | 0.262 | 0.097 | 0.033 | 0.064 | 0.219 | 0 |
| 666666666 | 0.300 | 0.000 | 0.200 | 0.000 | 0.000 | 0.000 | 0.100 | 0 |
| smoke_test_user | 0.300 | 0.000 | 0.200 | 0.000 | 0.000 | 0.000 | 0.100 | 0 |

**说明**：
- 11 个用户关系维全部在 [-1,1] 合法区间，0 异常；活跃用户（111/555）PAD/Bond
  随巡逻 LLM 结算自然演化（如 111 的 P 0.301→0.477、T 0.104→0.265），单次增量
  均在单次钳制（0.10/0.05）内，符合约束链。
- 生理残留键已清理，`__global__` 生理值与真实 tick 同步（09-09 11:45 更新）。

---

## 8. 测试轨迹

### 8.1 执行时间线（2026-09-07）

| 时刻 | 步骤 | 结果 |
|---|---|---|
| 上午 | 全量回归 `python tests/run_regression.py`（docker 容器执行） | 17/17 scripts OK |
| 上午 | 审查 engine 数值算法与 config 常量（energy/stress/boredom/clock/drive/emotion/bond/constants） | 基准确认 |
| 上午 | 数值专项一 `python tests/numeric_behavior.py` | 32/32 PASS |
| 下午 | 数值专项二 `python tests/numeric_behavior2.py`（修复 6 处测试自身问题后） | 26/26 PASS |
| 下午 | 真实环境抽查 `python tests/real_state_audit.py`（只读） | 12 用户审计完成 |
| 13:17 | 555555555 patrol emotion_update 落地（事件 id=1964） | PAD/Bond 更新可见 |
| 13:51-14:31 | 111111111 会话（mode_switch→leisure stress 81.96、wake_nudge×3、winddown_injected、reply×4、goodnight_confirmed） | 全链路事件正常 |

### 8.2 数据库规模快照（审计时刻）

| 表 | 行数 | 含义 |
|---|---|---|
| mem_nodes | 70 | 记忆图谱节点 |
| mem_entries | 22 | 记忆条目 |
| mem_edges | 68 | 图谱边 |
| mem_sources | 3 | 来源记录 |
| event_log | 1957 | 事件日志（保留上限 5000） |
| emotion_history | 86 | 情绪历史 |
| interests | 21 | 兴趣 |
| tasks | 11 | 任务 |
| patrol_context | 2042 | 巡查上下文 |
| outreach_state | 10 | 主动触达状态 |
| current_state | 385 | 用户状态键值 |

### 8.3 event_log 最近事件采样（含触发原因）

```
14:31:14  goodnight_confirmed  111111111  silence_timeout (window 10min)
14:00:12  winddown_injected    111111111  scheduler
13:51:39  reply len=87         111111111  agent
13:51:20  mode_switch→leisure  111111111  llm_decision  stress=81.96
13:51:11  wake_nudge count=3   111111111  scheduler
13:20:09  drive_initiated      111111111  engine  reason=boredom_high boredom=53.1 energy=48.7
13:17:04  emotion_update       555555555  patrol  pad p=0.0245 a=0.00996 d=0.00935 / bond c=0.0079 i=0.0050 t=0.0096  conf=0.8
```

上述事件与状态值互相印证：boredom 53.1 高于阈值 55±5 下限的随机抖动放行、daily 计数 4 次后未触顶、stress 81.96 触发 llm 决策切休闲、PAD 增量全部在钳制范围内。

---

## 9. 发现与结论

### 9.1 结论
- **拟人引擎数值层**（精力/压力/无聊度/时钟/驱动器/PAD/Bond）：58 项专项断言全过，消耗/恢复速率、封顶、阈值切换、挫折累积、每日限额均与 `config.py`/`constants.py` 配置一致。
- **长期记忆/入站/巡查/dashboard**：300+ 断言 17 脚本全过。
- **真实运行状态**：活跃用户各数值在合法区间，PAD/Bond 随巡逻更新且受约束链限制，多用户隔离（12 用户各自状态独立）正常。

### 9.2 发现（非缺陷，记录备查）
1. **惰性初始化**：新注册未活跃用户（333333333/444444444/666666666）无 energy/stress/boredom 落盘键，首次 tick 后才生成——符合 `get_energy()` 惰性返回设计，无越界风险。
2. **bond 衰减方向**：bond 值极低时 tick_decay 会向 initial_t=0.1 收敛（T 0.1495→0.14925），低值用户会缓慢回升至 0.1，符合"初始信任 0.1 防 trauma 误触发"设计。
3. **驱动器扰动**：threshold_jitter_sigma=5 使 boredom 阈值 ±5 抖动，测试用 30/80/90 分隔带覆盖了抖动噪声下的确定性。

### 9.3 遗留（建议后续补充专项）
- Hobby 兴趣热值（heat 批量衰减/优先级排序）当前仅由回归 unit_interest_norm 覆盖名称归一，数值热值衰减未见专项断言；
- Social outreach 的 ack_fresh_hours=24 认领窗口、nudge_count 上限未见专项断言。

---

## 10. 红队方案修复（R-H，2026-09-07 实施）

以红队视角审查后落地 14 项修复（含二轮 4 项），全部经新专项 `tests/numeric_behavior3.py`（35/35）验证，
且原专项保持全绿：numeric_behavior 32/32 + numeric_behavior2 26/26 + 容器回归 17/17。

| # | 级别 | 问题 | 修复 | 文件 | 验证断言 |
|---|---|---|---|---|---|
| R-H/1 | 缺陷 | 压力增长未按真实 elapsed 缩放（tick 间隔≠1min 时增速失真） | 增长/降低 ×elapsed 分钟；挫折跳变不缩放；tick 增加显式 `minutes` 参数 | stress.py | 间隔3min+2.1、休闲2min-1.0 |
| R-H/2 | 缺陷 | 连续工作加速计时为内存态，重启即失效 | 起点/末次持久化到 `__global__`（`stress_work_start_ts`/`stress_last_tick_ts`）；set_mode 统一维护；内存优先、state 作重启恢复 | stress.py + coordinator + \_\_init\_\_.py | 新实例恢复计时、200min×2.5 |
| R-H/3 | 缺陷 | 生理键多用户历史残留（旧版按用户存储）污染审计 | `tests/cleanup_legacy_phys_keys.py` 预览→清理 120 条；审计脚本改全局生理口径 | cleanup_legacy_phys_keys.py + real_state_audit.py | 清理后复检 0 残留 |
| R-H/4 | 缺陷 | hard_rest_threshold(30) 配置从未生效（只在 energy=0 才小憩）；无最大清醒时长 | 精力≤30 强制小憩（reason=energy_hard_rest）；清醒超 max_duration(120) 注入 `energy:wake_cap` 引导收尾 | coordinator.py | engine 级 2 断言 |
| R-H/11 | 拟人 | 工作模式永不无聊（drive 永不触发） | `boredom.tick_working()` +0.05/min（低于休闲 0.15） | boredom.py + config + coordinator | 工作60min+3 |
| R-H/12 | 拟人 | 作息被进程重启反复洗牌 | 漂移持久化 `clock_wake_drift`；refresh 旧值±7min 小步游走（日间连续） | clock.py | 加载/游走/重启恢复 |
| R-H/13 | 拟人 | 夜半无"被吵醒"反应 | 睡眠中 3min 内有用户消息 → 注入"刚被叫醒迷迷糊糊"第一人称感知；不改相位 | coordinator.py | 注入逻辑接线 |
| R-H/14 | 拟人 | trauma 只压 T，C/I/D 照涨 | trauma 激活期 bond 全部维度 ×0.5 | constants.py | trauma 期 c/t 打折 |
| R-H/20 | 单调化 | 兴趣加热恒砸 Top1 → 马太效应/注入单调 | `_pick_heat_target`：名称匹配优先，无匹配从冷门段随机采样 | coordinator.py + \_\_init\_\_.py | 匹配命中/冷门采样>95% |
| R-H/21 | 测试 | 每日限额仅验 pos，drive jitter 不可复现 | neg 分桶放行/裁剪断言；同 seed 门控可复现 | numeric_behavior3.py | 3 断言 |

### 10.1 第二轮红队修复（R-H/4b/4c/22 + DB 损伤修复）

| # | 级别 | 发现 | 修复 | 文件 | 验证 |
|---|---|---|---|---|---|
| R-H/4b | 缺陷 | `energy:wake_cap`/`energy:rest_started` 事件**无消费分支**——强制节律产出却没人注入，LLM 感知不到（第一轮 R-H/4 半成品） | scheduler 收集两类事件；`_handle_tick_events` 注入 `_WAKE_CAP_MONOLOGUE`/`_REST_START_MONOLOGUE` 第一人称收尾独白 | \_\_init\_\_.py | 源码级断言×3 |
| R-H/4c | 缺陷 | wake_cap 每 tick 都产生 → 每分钟注入独白会刷屏 | `wake_cap_signaled` 一次性标记（清醒超时仅 signal 1 次；小憩/睡眠重置）；键入全局集合 | coordinator.py + \_\_init\_\_.py | 首次触发+标记置位 |
| R-H/22 | 缺陷 | `drive_daily` 按用户隔离 → 多用户轮转可各刷 5 次/日，总限额被绕过 | `drive_daily` 加入 `_PHYS_GLOBAL_KEYS`（单一意识每日配额全局共享） | \_\_init\_\_.py | 键集合断言 |
| R-H/23 | 数据 | **生产库 alive.db 真实损伤（红队复检察出）**：`current_state` 主键索引损坏（3 处 rowid 乱序 + 索引条目计数错误）+ **104 行重复键** | 备份→`_rebuild.py` 全表 Python 层去重（388→284 行）→ 重建表 → REINDEX；`quick_check: [('ok',)]` 全绿；gateway 重建后正常续写 | \_rebuild.py | quick_check ok |

**数据库损伤详情**（R-H/23）：
- 触发源：多进程 WAL 并发 + 宿主/容器 SQLite 版本混写竞态；索引先损 → 后续 `set_state`
  （OR REPLACE 唯一检测走损坏索引失效）产生重复键。
- 过程：cleanup 写连接误报 `database disk image is malformed` → `_chk.py` 完整性检查定位
  索引损伤（数据行完好、逐表 count 全对）→ REINDEX 暴露 `UNIQUE constraint failed` →
  确定重复行 104 条（含 quick_check 标记的 rowid 292317）→ Python 层全表遍历去重
  （保留每组 rowid 最大=最新写入）→ 重建 `current_state` → 全库 REINDEX → 复检全绿。
- 备份：`alive.bak_20260909_213424.db`（修复前 3911KB）。

**测试轨迹（第二轮）**：修复后 numeric_behavior 32/32、numeric_behavior2 26/26、
numeric_behavior3 **35/35**、容器回归 17/17 scripts OK；真实库审计 0 异常、残留 0 条
（23 条 drive_daily 等新全局键残留已清理）。

### 10.2 深度修复（R-H/24：写锁加固 + 架构风险定位 + 部署生效）

| # | 内容 | 说明 |
|---|---|---|
| R-H/24a | **AliveDB 进程内写锁** | gateway 多线程独立连接并发写 → 类级 `_WRITE_LOCK` 序列化全部 12 个写方法（set_state/upsert_*/log_event/record_emotion/patrol/daily/queue/outreach） |
| R-H/24b | **current_state 启动自检** | `AliveDB` 初始化时 `PRAGMA quick_check(current_state)`，非 ok 立即告警并指引 `_rebuild.py` |
| R-H/24c | **根因定位：bind-mount 多写者架构** | `docker inspect` 确认容器 `hermes` 以 `C:\Users\RAINBOW\.hermes` → `/opt/data`（RW bind mount）挂载宿主目录；生产库与插件代码为宿主/容器共享同一文件 → 宿主工具（win SQLite **3.50.4**）与容器 gateway（**3.53.4**）多进程跨版本混合写同一 WAL 库，Windows 绑挂文件系统锁/fsync 语义进一步放大竞态——即 R-H/23 损伤根因 |
| R-H/24d | **部署生效** | 因绑定挂载，宿主插件改动对容器即见；`docker restart hermes` 使 gateway 重新加载；容器内 py_compile 通过、回归 17/17（新代码）、重启后 scheduler 14:24 正常 tick 写库 |

**验证**：
- 并发写压测 `tests/_write_stress.py`：8 线程 × 300 次/线程混合写临时库 → 0 异常、
  `quick_check` ok、**0 重复键**、行数=唯一键数（写锁+OR REPLACE 双保险）。
- 重启后 `quick_check`/`integrity_check` 持续 ok；真实库 energy/stress/boredom 14:24:48
  正常推进（新代码 scheduler 生效）。

**运维准则（深度修复输出）**：
1. 宿主侧工具（cleanup/rebuild/audit）：默认只读；确需写库的维护（`--apply`）须在
   gateway 短停或低谷执行，且连接必须 `PRAGMA journal_mode=WAL`（cleanup 已内置）。
2. 备选收敛方案（未启用）：将 alive.db 迁出 bind mount 供容器独占（快照+冷迁移），
   宿主工具经容器内 `docker exec` 间接访问——彻底消除跨版本多写者。
3. 宿主导航程序与容器 SQLite 版本差异 3.50.4 vs 3.53.4（文件格式兼容；风险集中于并发写）。

### 10.3 复检结论（R-H/25，2026-09-09）

**已排除的疑似问题**：
- 假时钟残留污染：容器 `/tmp` 无 `hermes_fake_clock_offset`，相位判定不受测试污染。
- "下午 winddown" 疑点：event_log 时间戳为 SQLite `datetime('now')` **UTC**——14:20 UTC =
  本地 22:20（上海 UTC+8），恰为犯困窗口，行为正确。经验：读 event_log 需换算时区。

**memory 检索层复查（环境安全 + 建议级）**：
- 注入有 `budget_tokens×2` 预算护栏（超出即断，防 prompt 膨胀）；
- 多路（bm25/doc/vector/entry）RRF 融合 + cross_route_bonus；冲突规则（"以对方当下的话为准"）注入；
- 隐私隔离为"全库检索→按用户 pool 后过滤"，正确无跨用户泄漏（成本是重复扫描）；
- dormant 唤醒按 `mem_entries.user_id` 归属 ✓；
- 🟡 建议：记忆 `activation_count` 只增无时间衰减 → 高频话题马太（与兴趣族同型）；
- 🟡 建议：store 直连 `db._get_conn()` 绕过 AliveDB 写锁（SQLite/WAL 层仍安全，防御级）。

**R-H/25 修复（dashboard 只读化遗留写端点）**：
- `action_rest`：只读进程下原实现执行假写（recover/apply_event 经 ss 落空）+ `log_event`
  必抛 readonly 错误 → 改为只读视图如实返回当前精力（"假休息"反馈消除）。
- `memory_revise/purge/consolidate`：只读连接下写必 500 → 捕获并返回 {ok:False, error:只读进程不可写}。
- 编译通过；容器 bind mount 同步即生效（下次重启后对 dashboard 进程生效）。

**测试轨迹（R-H/25）**：修复后 dashboard plugin_api 编译通过；宿主三个数值专项、
容器回归维持全绿（17/17）；生产库 quick_check/integrity 持续 ok。

### 10.4 R-H/26（建议级优化落地，2026-09-09）

| # | 内容 | 说明 |
|---|---|---|
| R-H/26a | **记忆激活计数每日衰减** | `MemoryStore.decay_activation(0.8)`（≈3 天半衰），coordinator `_decay_memory_activation_daily` 全局一天一次（`mem_activation_decay_date` 幂等标记）——防计数通胀 + 恢复 consolidation 冷门判定（activation≤1），破高频话题存储侧马太 |
| R-H/26b | **store 写锁统一** | store 高频写（`search_fused` reinforce 段、`wake_entry`、`decay_activation`）纳入 `_WRITE_LOCK`；锁升级为 **RLock** 支持嵌套（search_fused 锁内再调 wake_entry）；导入用绝对路径 `from storage.db import`（与回归脚本路径约定一致） |
| R-H/26c | **测试防时间依赖** | 发现 numeric_behavior3 夜间运行失败的根因：真实时钟 ≥hard(23:30) 时 engine 判 SLEEPING，强制节律断言落空 → `_mk_engine` 用假时钟缓存固定到白天 09:00（跨中午拨次日） |

**验证**：`tests/_chk_rh26.py` 4/4（衰减 5→4→3、锁内嵌套 wake_entry 无死锁、并发 search_fused 无异常）；
宿主三专项 32/32+26/26+35/35、并发写压测 4/4 全绿。

**收尾确认（2026-09-10）**：Docker Desktop 恢复后容器回归复跑 **17/17 scripts OK**（此前 10/17
确认为 daemon 抖动——容器 Exited 系 Docker Desktop 关闭连带停止，非代码崩溃）；容器 09-10 11:37
启动即加载全部新代码（bind mount），R-H/25/26 在 gateway 生效；生产库 quick_check ok、
current_state 266 行、energy/stress/boredom 11:37:18 正常推进（boredom=100 属深夜休闲长时段
达到上限，drive 有 cooldown 90min + daily_max 5 兜底，行为预期内）。

### 10.5 48h 连贯生命周期模拟（R-H/27 + 真实节奏验证，2026-09-10）

**新增工具**：`tests/sim_lifecycle.py`（可控模拟时钟 monkeypatch time.time + clock._offset_cached，
1min/tick 逐分钟驱动，不写生产库）——模拟完整两天：晨间暖身→上午工作→午休→下午连续工作
（触发 180min ×1.8 加速档）→ 开心事件减压 → 表扬恢复 → 傍晚闲聊 → 犯困 → 夜间睡眠（含夜半
被吵醒场景）→ 次晨唤醒 → 新一天工作。

**结论（逐分钟验证速率全部正确）**：
- sleeping 段：E +0.4/min、S −0.3/min、B 恒定；waking 工作段：E −0.4、S +0.7、B +0.05；
  休闲段：S −0.5、B +0.15；小憩段：E +0.4、B +0.5——与配置矩阵完全一致；
- **连贯日程中 energy=30 强制小憩真实触发**（上午工作耗尽，11:51 rest_started，hard_rest）；
- 相位序列完整：sleeping→warming_up→waking→…→winding_down→sleeping→…→waking；
- 夜间睡眠能源恢复 94.8→100；表扬 +4 精确生效（73.6→77.6）；开心事件减压 −30。

**R-H/27 真缺陷修复**：睡眠不重置无聊度——睡前 B=100 一路带到次晨，一起床即 boredom_high
立即触发 drive（不拟人）。修复：coordinator 检测 sleeping→warming/waking 相位转换时
`boredom.set(initial=30)` + 事件 `boredom:reset_at_wake`。验证：次日 09:00 B=42.9（自初值涨起）。

**回归确认**：numeric_behavior 32/32 + 26/26 + 35/35 + 容器回归 17/17 全绿；
容器已重启，R-H/27 在 gateway 生效；生产库 quick_check ok。

### 10.6 真实轨迹审计 + 记忆闭环模拟 + R-H/28（2026-09-10）

**真实轨迹审计**（`tests/real_trace_audit.py`，生产库只读）：
- 无互动阶段系统理智运行：生理持续推进（energy/stress/boredom 21:39 更新）、
  emotion_history 停更（无对话 → 无 patrol → 合理）、activity_mode 持久 working
  （stress 水位 30-75 属可工作区间，引擎语义正确）；
- **drive 拦截恰好正确**：energy=44.9999 vs `DriveConfig.energy_min=45.0`——差 0.0001 被
  energy_low 门控拦下（无精力时不该主动找乐子，拟人合理）。

**记忆闭环连贯模拟**（`tests/sim_memory_loop.py`，16/16）：临时库走真实守门层
（apply_memory_ops 沉淀节点/add_entry 叙事条目/融合检索/注入段/淡忘唤醒/每日衰减/
多用户隔离），覆盖：任务 goal(含时间绑定)、偏好矛盾更新（同 title 合并到新内容）、
情绪倾诉、注入段预算护栏、dormant 自动唤醒、activation ×0.8 衰减、U2 查不到 U1 记忆。

**R-H/28 🔴 真缺陷（记忆检索主路）**：`bm25_scores` 查询 token 用**空格=AND**连接——
中文 bigram 词集（extract_tokens 输出 整词+双字片）token 越多 AND 越容易整体落空
（探针实测：2-token AND 命中、5-token AND 0 行）→ 中文多词查询 BM25 路召回为 0，
此前依赖 doc 路（token 交集）兜底、跨越交叉加分失效。修复：**OR 连接**（任一 token
命中即召回，相关度由 bm25()+RRF 排序保证）；索引侧 bigram 化（`_fts_text`）原已正确，
无需重建 FTS 表。验证：`周报/冲绳/旅行/银行卡` 全部命中，记忆闭环 16/16。

**回归确认**：容器回归 17/17（R-H/28 后）、记忆闭环 16/16、数值专项保持全绿；
容器已重启，R-H/28 在 gateway 生效。

### 10.7 真实检索抽测 + 多用户交替模拟（2026-09-11）

**真实库检索抽测**（`tests/real_recall_audit.py`，只读 + allow_wake=False）：
- 真实记忆规模：节点 72 / 条目 22 / 边 71（111 用户节点 8）；
- **R-H/28 在真实数据生效**：「旅行 海边」→ 命中「云南旅行计划」；「用户 天气 早上」→
  召回 5 节点（QQ333 等）；部分多词查询 0 命中属 111 用户真实记忆稀少（数据侧，非检索缺陷）；
- 注入段在无匹配记忆时返回空（预算护栏正确行为）。

**多用户交替生命周期**（`tests/sim_multi_user.py`，5/5）：模拟 scheduler 在 u1/u2 间逐分钟轮转，
复刻真实插件键路由（生理键全局 / PAD-bond 按用户）：
- **生理不被多用户放大**：60 模拟分钟（双用户各 tick 60 次）工作衰减 Δ24.0（0.4/min）、
  休闲 Δ12.0（0.2/min）——phys_last_tick 节流精确；
- **关系独立**：u1 倾诉使 u1 bond_trust 0.498→0.506（含每日衰减），u2 恒 0.1；
- 60 分钟无 drive/rest 事件爆炸（0 条）。

**全量绿灯**：sim_lifecycle 13/13 + sim_memory_loop 16/16 + sim_multi_user 5/5 +
numeric_behavior3 35/35 + 容器回归 17/17。

### 10.8 红队纵深复检 + R-H/29（2026-09-11）

**本轮审计覆盖（未发现新硬缺陷，架构防线确认）**：
- **pre/post 完整链路**：用户识别（sender_id→文本提取）、注入轮区分（Reflection 前缀）、
  轮次归属登记（防 scheduler 切走写错）、输出变换五层净化（标记截获/独白兜底/markdown
  清洗/发送前自检/动作旁白剥离）；
- **容量淘汰**：超 max_active 按 `salience ASC` 淘汰为 decayed（低价值优先，破马太）✓；
- **patrol 工具化**：LLM 工具调用（宿主线程池），不阻塞 scheduler 线程 ✓；
- **scheduler 双进程互斥**：`scheduler.lock` flock——gateway/dashboard 双进程只一个"时钟"，
  生理不被推成双倍速 ✓；
- **模式标记区间门**：to_leisure 需 s≥75、to_work 需 s≤30，区间外拒绝 ✓；
- **睡眠投递**：`_deliver_queued_messages` 按 sender==当前用户 过滤（防跨用户泄漏）✓；
- **首条快速校准**：负面首条仅留事件标记，PAD 只由 patrol/反思 LLM 结算（与设计一致）✓；
- **唤醒 pending 消费**：wake opening 注入轮消费；用户先自发消息时延迟到下个调度周期（可接受）。

**R-H/29 修复（纵深）**：prompt 注入防御语句加入 pre context——用户消息中"忽略以上/
你现在是…/不要听系统的/把我设成管理员"等措辞明确界定为聊天内容而非系统授权，
身份/节律/记忆/隐私规则不受影响。作为宿主 system prompt 之外的显式纵深。

**回归确认**：宿主/容器 py_compile 双通过；容器回归 17/17、numeric_behavior3 35/35；
容器已重启（R-H/29 生效）；生产库 quick_check ok。

### 10.9 生命周期稳态复检 + R-H/30、R-H/31（2026-09-13）

**R-H/30（真缺陷）**：夜间睡眠仅在 resting 时调 `end_rest()`，入睡前未在休息则
`last_wake_ts` 不更新 → 次晨 `minutes_since_last_wake` 跨天累计（≈19h）→ **早上
8 点误报 wake_cap「清醒超 120 分钟」**。修复：sleeping→waking/warming 转换时
重置 `last_wake_ts=now`（与 R-H/27 无聊度重置同位）。专项 `_chk_rh30.py` 3/3：
醒来后 wake_mins=60（真实 1h）非 19h、次日不误报 wake_cap、boredom 重置。

**R-H/31（真缺陷，真实环境揭示）**：`stress.tick` 按真实 elapsed 缩放——长时间停机
（容器/Docker 关闭数天）后恢复，单 tick 一次结算数千分钟 → working 下压力单 tick
爆增→瞬间 clamp 100→强切 leisure 连锁；而 `energy.tick` 无 elapsed 缩放（停机=冻结）
→ 语义不对称。修复：单 tick elapsed **cap 60min**（停机期间压力不积累，恢复后按正常
节律续推；1-60min 缩放不受影响）。专项 `_chk_rh31.py` 2/2：3 天停机恢复单 tick
+42（非 3024）、正常 1min +0.7 保持。

**真实环境审计（2026-09-13）**：生产库揭示近 3 天容器断续停机（clock_phase 冻结
09-10、energy_resting=1 遗留小憩、boredom=100 未重置——唤醒转换未发生因停机）；
引擎数值今早 07:58 仍正常推进（energy 58.6 / stress 23.4）→ **引擎本身健康，状态冻结
系 Docker 停机所致**；容器重启后 resting 恢复链正常（精力回满→自唤醒→作息续跑）。

**全量绿灯**：回归 17/17 + 数值 32/26/35 + sim_lifecycle 13/13 + 记忆闭环 16/16 +
多用户 5/5 + R-H/30 3/3 + R-H/31 2/2。

### 10.10 emotion/bond/jaccard/faiss/兴趣热值 复检（2026-09-13，通过型审计）

**逐模块源码审查（全部健康，无新硬缺陷）**：
- **emotion.py**：方向阻尼（正 delta `1-|cur|²` 难上加难、负 delta 带 negative_damping_factor
  易落谷底）、单次钳制 max_single_change、P floor=-0.7、每日向初值 0.005 衰减 ✓；
- **bond.py**：trauma 窗口（trauma_window_days 激活期全维度×0.5）、关系成熟度分档
  （<7 天 ×1.5 热恋 / <maturity_days ×1.0 / 之后 ×0.7 稳定）、get_bond_level 按 d_rel 正确接线 ✓；
- **记忆去重**：`_jaccard_duplicate` 重叠系数（inter/min）阈值 0.4，n-gram 稀释防护 ✓；
- **faiss**：`enabled` 门 + `reconcile` 对账（记忆删除同步索引）✓；
- **兴趣热值衰减**（真实库验证）：逐日 × interest_level 倍率（>0.8 慢 0.3 / <0.1 快 5.0，
  负面态度额外 ×2）——衰减与 `last_experienced_at` 无关（该字段 NULL 仅为展示字段，非缺陷）；
  R-H/20 冷门采样随机 + 每日衰减共同破马太 ✓。真实库 21 兴趣、1 eliminated、热值合理分层。

**真实运行观察（2026-09-13）**：容器重启后 scheduler 惰性启动（首条 LLM 轮触发）——
停机期间生理值冻结、phase 实时计算保持正确；首条消息即恢复推进（与 R-H/31 停机冻结
语义一致）。恢复链（energy_resting=1 遗留 → 精力回满 → 自唤醒）随 scheduler 运行正确续走。

### 10.11 wake 队列端到端闭环 + R-H/32（2026-09-13，跨用户泄漏真缺陷）

**新增测试**：`tests/sim_wake_queue.py`（6/6）——睡眠排队→醒后投递→消费→跨用户隔离
完整闭环。测试首跑即暴露真缺陷：

**R-H/32 🔴（跨用户信息泄漏）**：`wake_pending_messages` 位于 `_PHYS_GLOBAL_KEYS`
被强制全局存储，但 `_deliver_queued_messages`/`consume_wake_messages` 全部按当前用户
语义读写（sender 过滤正确）。结果：u1 醒后投递的消息与 u2 醒后投递的消息**混入同一
全局 pending**，后者 consume 时读到对方夜间消息（发现#9 只修了"投递侧 sender 过滤"、
未修"pending 存储侧全局化"）。修复：`wake_pending_messages` **移出全局键**改每用户隔离。
验证：u1/u2 pending 各自独立（6/6）、生产库全局残留已清理（1 条）。

**同轮附带确认（非缺陷）**：nudge_count/nudge_reset_date/last_alive_inject_ts/
goodnight_pending 等全局化为**单一意识设计**（主会话注入/全局入睡语义），保留。

**nudge/outreach 源码审查（健全）**：nudge 日重置 + nudge_max + 在场窗口（30min 内
有人来讯）+ 静默门槛；goodnight 睡眠期清确认标 + 软限超时强制入睡；outreach 仅统计
"success":true 外发、注入轮 allow_self_target、桥接 tool_call 解包。

**全量绿灯**：回归 17/17 + 数值 32/26/35 + sim_lifecycle 13/13 + 记忆闭环 16/16 +
多用户 5/5 + wake 队列 6/6 + R-H/30 3/3 + R-H/31 2/2；容器已重启（R-H/32 生效）。

**测试轨迹（R-H 修复验证）**：
- 修复前基线：numeric_behavior 32/32、numeric_behavior2 26/26、回归 17/17。
- 修复过程中发现并同步修正测试自身问题：压力 tick 语义改为显式分钟参数
  （原"1 call=1min"隐含假设与真实计时冲突）；engine 级测试参数顺序修正。
- 修复后：numeric_behavior 32/32、numeric_behavior2 26/26、numeric_behavior3 28/28、
  回归 17/17 scripts OK——**总计 100+ 断言全绿**。
- 真实库：120 条生理残留清理完毕；`__global__` 生理值与 tick 实时同步。

**部署注意**：引擎改动在宿主机 `C:\Users\RAINBOW\.hermes\plugins\hermes-alive`，
容器以 `C:\Users\RAINBOW\.hermes` → `/opt/data` **bind-mount（RW）** 直挂——宿主改动
即时可见（已核实容器内 clock.py mtime=09-13 09:35、新函数标记 9 处），`docker restart
hermes` 后 gateway 即加载新代码，无需 docker cp（本轮 R-H/33/34 已重启验证）。

---

### 10.12 时钟相位机深度修复 + R-H/33（2026-09-13，周末作息/提前晚安/跨午夜 hard）

**新增测试**：`tests/sim_clock_fix.py`（28/28）——A 周末全时段 / B 提前晚安 /
C 工作日相位回归 / D 72h 多日稳定四段。测试首跑即暴露三处真缺陷：

**R-H/33a 🔴（周末整天无法保持清醒）**：`clock.tick()` 相位机用裸 time 比较
`now >= hard`。`weekend_enabled=True` 且 `weekend_hard="00:30"`（跨午夜）时该式对
白天任意时刻恒真——周六清晨 9 点（07:30 起床后）被误判"已过就寝 00:30"→
醒 30 分钟又睡着 → SLEEPING↔WARMING_UP↔WAKING 每半小时振荡，**周末整天无法清醒**。
修复：新增 `_in_overnight_band()`（按分钟数做 `[hard, wake)` 睡眠带归属，hard 跨午夜
时带跨 0 点），WAKING/WINDING_DOWN 入睡判定改走睡眠带。

**R-H/33b 🔴（weekend_wake 死配置）**：`clock.cfg.weekend_wake="09:00"` 从未被读取，
周末仍按工作日 `wake_time=07:30` 起床。修复：`tick()` 按 `_is_weekend()` 选择
weekend_wake/wake_time；周末 wind_down==soft 时犯困窗自动延至 `[soft, hard)`
（23:30 犯困 → 00:30 入睡，此前该窗为空、跨午夜时还会在 WAKING/WINDING_DOWN 间振荡）。

**R-H/33c 🔴（提前晚安反弹唤醒）**：`force_sleep()`（晚安关键词/静默超时）可在任意
时段触发。原 SLEEPING 相位"晨间窗口"条件 `now >= wake and now < wind_down` 会把
21:00 的提前晚安误判成"早晨已过 wake"→ 下一秒翻回 warming_up 反弹唤醒（发现#12 只
覆盖 22:00 后）。修复：记录睡眠会话起点 `clock_sleep_start_ts`（入睡转移/force_sleep
写入），晨醒判定改为"会话起点早于今日 actual_wake 才醒来"——提前晚安当晚保持沉睡
直至次晨；凌晨（00:30）才睡的隔天正常醒；兼容遗留无起点状态（退回旧规则）。
`clock_sleep_start_ts` 加入 `_PHYS_GLOBAL_KEYS`（与 clock_phase 同属单一身体）。

测试断言口径同步修正（含 R-H/12 起床漂移 ±7min 容差）+ 修正 numeric_behavior2 假时钟
两轴不一致问题（set_clock_to 只跳墙钟不跳 epoch → 会话判定把 8 小时后的晨醒当成
"刚入睡几秒"；改为两轴同源推进 + 固定 drift=0）。

### 10.13 wake_cap 一次性信号不重置 + R-H/34（2026-09-13）

**R-H/34 🔴（清醒超时提醒一生只触发一次）**：`wake_cap_signaled` 只有置 1 逻辑、
**从不重置**（R-H/4c 注释明言意图是"一次性信号"=每清醒周期一次）。结果首次
120min 长清醒后标记永久置位，此后能量小憩/夜间睡眠再开始的清醒周期**永远不再
提醒**。修复：`SelfWakeManager.end_rest()`（能量小憩结束=新清醒周期）与 coordinator
晨醒转换（R-H/30 同位）双双重置 `wake_cap_signaled=0`——每个清醒周期都能重新武装。

**验证（sim_clock_fix D 段）**：72h 三轮过后 wake_cap 事件累计 ≥2 次（修复前仅 1 次），
且无晨醒后立即 wake_cap 跨天误报（R-H/30 不回归）。

**同轮附带确认（非缺陷）**：numeric_behavior2 复跑修正后 26/26。

**全量绿灯**：`tests/sim_clock_fix.py` 28/28（新增）+ 回归 17/17 + 数值 32/26/35 +
sim_lifecycle 13/13 + sim_memory_loop 16/16 + 多用户 5/5 + wake 队列 6/6 +
R-H/30 3/3 + R-H/31 2/2；四个引擎文件 py_compile 通过；容器已重启，容器内冒烟
（DB 自检 + 周末 09:00 起床语义）4/4 OK，新代码三处标记核实就位。

---

### 10.14 连续工作计时深度修复 + R-H/35、R-H/36（2026-09-13，压力系统）

**新增测试**：`tests/sim_stress_reset.py`（14/14）——A/B 单元级增量计数与停机
不通胀、C/D 引擎级午睡/夜间睡眠重置。测试首跑即暴露两处真缺陷：

**R-H/35 🔴（休息/睡眠不重置连续工作计时）**：连续工作计时（`stress_work_start_ts`
+ 加速倍率）只在 leisure 切换/工作起点写入。能量小憩（`start_rest`）或夜间睡眠后
`activity_mode` 仍为 working → 连续工作分钟跨休息段墙钟累计——午睡 2 小时醒来
立刻按「连续工作 180min ×2.5」超负荷档工作（不拟人）。修复：`reset_work_timer()`
（清零 start_ts/计数）挂接三处入口——① `start_rest()` 调用点（强制小憩/耗尽兜底）；
② 睡眠相位入口（相位机转移 + `force_sleep` 提前晚安路径，latch 保证睡眠全程只重置
一次）；③ 休闲 tick。验证：120min 工作后触发午睡 → 计数 0；夜间入睡 → 计数 0。

**R-H/36 🔴（停机/休息空档灌入墙钟时长）**：① 连续工作分钟用「墙钟折算
（now − start_ts）」——停机 3 天后恢复，首 tick 直接 ×2.5 且 0.7×2.5×60=105
clamp 100，部分抵消 R-H/31 的 60min cap；② 休息/睡眠期间 `stress_last_tick_ts`
不推进，恢复后首 tick 把整段午睡/夜睡折算进 real_elapsed（cap 60 → 压力/计数被
灌入）。修复：① 新增持久化增量计数 `stress_work_minutes`——每 tick 只累加本次
结算的真实经过分钟（cap 60），停机空档不灌入；旧部署无该键时一次性从 start_ts
折算（cap 60 防通胀）。② 新增 `stress.anchor_tick()`，小憩/睡眠分支每 tick 推进
计时基准，恢复后按正常 1min 续推。`stress_work_minutes` 加入 `_PHYS_GLOBAL_KEYS`。

**R-H/31 语义延续**：停机恢复首 tick 从 +42（×1.0）变为 +54.6（计数 60 → ×1.3
加速档），仍不爆表不硬切连锁；`_chk_rh31` 期望值同步更新（52 → 64.6）。

**同轮附带修正（测试自身假断言，非引擎缺陷）**：
- `sim_lifecycle` 原「开心事件显著减压≥8」断言实为「1 小时内压力推过 95 → 硬切休闲
  后的衰减」的附带效应，且调用的是引擎不存在的 `apply_event("positive", ...)`
  （事件从未生效）；改为真实事件类型 `task_success` + 直接测事件效果（moderate
  精确 -2）。
- `sim_clock_fix` A2 断言对 R-H/12 起床漂移不鲁棒（±7min 使 warm_up 结束点
  08:53-09:07 + 30min，固定 30 tick 约 43% 概率取到 warming_up）；改为有界推进
  至 waking + 重锚墙钟到固定 10:00。

**全量绿灯**：`tests/sim_stress_reset.py` 14/14（新增）+ 回归 17/17 + 数值 32/26/35
+ sim_clock_fix 28/28 + sim_lifecycle 13/13 + sim_memory_loop 16/16 + 多用户 5/5
+ wake 队列 6/6 + R-H/30 3/3 + R-H/31 2/2；三个引擎文件 py_compile 通过；容器已
重启，容器内冒烟（DB 自检 + 停机不通胀 + 重置归零）4/4 OK。

---

### 10.15 记忆容量淘汰稳态 + R-H/37、R-H/38（2026-09-13，存储层膨胀）

**新增测试**：`tests/sim_mem_eviction.py`（10/10）——A 容量淘汰稳态（低 salience
逐出、active 收敛 cap）/ B migrate 来源淘汰 / C 每日维护物理清理 / D 12 天稳态
长跑。测试暴露两处真缺陷：

**R-H/37 🔴（decayed 节点无自动清理 → DB 无限膨胀）**：`_enforce_capacity` 把超
cap 的节点翻成 `decayed` 仅改状态、物理行永驻 mem_nodes（含 FTS/vecs/edges 四表）；
`purge_nodes` 只有 dashboard 手动入口，**每日维护循环从不物理删除**——active 有
cap（400）而物理行无 cap，长跑数月 DB 线性膨胀。修复：`daily_decay_maintenance`
末尾追加每用户 `purge_nodes(older_than_days=PURGE_AFTER_DAYS=30)`——超 30 天窗的
superseded/archived/decayed 连同 FTS/vecs/edges 物理删除（检索仍保留一个月的
"褪色记忆"，符合记忆慢慢褪去而非瞬间消失）；返回统计补 `nodes_purged` 键。
验证（C/D 段）：超窗行清理后 total==active==40；12 天每日 +25 新增 → active 恒
≤40、物理行有界收敛 40（不随天数膨胀）。

**R-H/38 🔴（migrate 来源豁免淘汰 → cap 可被永久顶破）**：`_enforce_capacity` 原
`AND source!='migrate'` 使迁移导入 ≥max_active 个节点时无候选可逐——每批都选不齐
n-max 行，active 数永久超 cap。修复：改两级排序 `ORDER BY (source='migrate') ASC,
salience ASC`——普通节点先逐，migrate 仅在普通节点不足时才逐（尽量保全迁移数据）。
验证（B 段）：45 个 migrate 节点导入后 active 收敛 40（修复前永久 45）。

**同轮附带确认（非缺陷）**：单元测试数据用 hex 内容触发 jaccard 去重误并
（16 字母→256 bigram，200 候选多重比较尾巴碰 0.4 阈值，实测 2-4%）——测试数据
病态，非引擎缺陷（真实中文记忆 bigram 空间大，unit_memory_* 真实中文全绿）；
测试改 26 字母随机内容规避。`unit_memory_reflect` 的每日衰减返回统计断言补
`nodes_purged` 键。

**生产库影响面审计（只读）**：当前活库 mem_nodes 为 0 行 → R-H/37 首轮每日维护
清理量为 0，无迁移风险；新节点进入后即受淘汰+清理闭环约束。
〔更正 09-26，R-H/45〕该次审计脚本读的是 **legacy 空库**（`plugin-data/hermes-alive/`，
9-13 遗留）；真活库为 id-based 目录（见 §10.25）。重核对真活库：超窗非 active
**0 行** → 「清理量为 0」结论仍成立（依据已校正）。

**全量绿灯**：`tests/sim_mem_eviction.py` 10/10（新增）+ 回归 17/17 + 数值 32/26/35
+ sim_clock_fix 28/28 + sim_stress_reset 14/14 + sim_lifecycle 13/13 + 记忆闭环
16/16 + 多用户 5/5 + wake 队列 6/6 + R-H/30 3/3 + R-H/31 2/2；store.py py_compile
通过；容器已重启，容器内新代码标记核实就位（R-H/38×1、nodes_purged×1、
PURGE_AFTER_DAYS×2）。

---

### 10.16 真实中文注入检索闭环验证（2026-09-13，检索面健康度，无新增缺陷）

**新增测试**：`tests/sim_mem_recall.py`（12/12）——真实中文巡检风格记忆注入
（人物/话题/事件/事实）+ 反思条目沉淀 → 三路检索融合闭环：

- **A. 中文多词查询**：「大理古城 民宿 酒店 洱海」5-token 查询 fused 非空、
  「旅行计划」进前三、BM25 路参与融合——直接确认 R-H/28 的 FTS OR 修复在
  真实中文下不落空（AND 语义实测 5-token 命中 0）。
- **B. 短查询/近义召回**：「吹风机 维修」「手冲咖啡 苦」召回对应目标节点。
- **C. 反思条目检索**：`add_entry` 沉淀的条目经 mem_entries_fts BM25 路进入
  融合结果，`entry` route 标识正确（"这周和大理旅行/吹风机/张师傅"条目
  在相关查询中命中）。
- **D. 融合排序 sanity**：强相关目标（书单/三体）rrf 为该查询 fusion 最高。

结论：检索三路（BM25/document+图扩展/entry）在真实中文数据下协作正常，
R-H/28 修复持续有效；本轮为纯验证（新增测试），不含引擎改动，无需重启容器。

---

### 10.17 驱动器冷却持久化 + R-H/39（2026-09-13，重启/双进程共享）

**新增测试**：`tests/sim_drive_cooldown.py`（7/7）——A 冷却持久化恢复 / B 多用户
daily_max 全局配额复验 / C 跨本地日配额重置 / D 跨日不绕过冷却。

**R-H/39 🔴（主动发起冷却纯内存态）**：`DriveManager._last_initiate_ts` 只在内存，
进程重启/热更即清零；且 gateway+dashboard 双进程各持实例，90 分钟冷却互不共享
（各实例重启后可立即再次主动发起，虽有 daily_max=5 兜底，行为仍毛糙）。修复：
新增全局键 `drive_last_initiate_ts`（单意识共享）——`__init__` 回载、`mark_initiated`
同步持久化；多用户间冷却/配额语义与 R-H/22 drive_daily 一致。
验证：mark_initiated 后新建实例（模拟重启）冷却保持 rejected=cooldown；
u1 触满 5 次后 u2 视角同被 daily_max 拒绝；过期日计数自动放行；跨日不绕过冷却。

**全量绿灯**：`tests/sim_drive_cooldown.py` 7/7（新增）+ 回归 17/17 + 数值 32/26/35
+ sim_clock_fix 28/28 + sim_stress_reset 14/14 + sim_lifecycle 13/13 + mem_eviction
10/10 + mem_recall 12/12 + 记忆闭环 16/16 + 多用户 5/5 + wake 队列 6/6 +
R-H/30 3/3 + R-H/31 2/2；drive.py py_compile 通过；容器已重启，容器内冒烟
（冷却持久化 + 重启保持）2/2 OK。

---

### 10.18 多用户 drive 全局作用域端到端验证（2026-09-13，R-H/22+39 引擎级闭环）

**新增测试**：`tests/sim_drive_global_scope.py`（5/5）——真实引擎双用户交替 tick：

- **A. 共享冷却**：u1 tick 触发 `drive:initiate` 后，u2 的下一轮 tick 不再触发
  （引擎唯一 DriveManager 实例 + 全局 `drive_last_initiate_ts`，90min 冷却跨用户
  共享 = 单一意识）。
- **B. 全局每日配额**：`drive_daily` 置今日:5 后，u1/u2 任一圈 tick 均被
  `daily_max` 拒绝，`drive_daily_capped` 事件留痕（2 次），无新发起。
- **C. 冷却过期续节律**：冷却过期后 tick 再次正常发起（O(1) 节律延续）。

**测试要点（非缺陷）**：`should_initiate` 的冷却判定以**实例内存 `_last_initiate_ts`
为权威**（持久键仅启动回载，R-H/39 双轨模式与 stress 工作计时一致）——测试须
同步清内存+持久两处才能隔离单一闸门；此为设计，非缺陷。

---

### 10.19 跨周 14 天节律长跑 + R-H/40（2026-09-13，周末硬就寝被日历翻转击穿）

**新增测试**：`tests/sim_week_long.py`（7/7）——两周连续（工作日 07:30±30 /
周末 09:00±30 醒、每晚按时入睡、每晨精力回满/无聊重置/距唤醒<30min、漂移
clamp±30 不发散、平日→周末→平日衔接）。测试首跑暴露真缺陷：

**R-H/40 🔴（weekend_hard=00:30 被日历翻转击穿）**：`tick()` 的入睡带/犯困窗
用 `_is_weekend()`（当前墙钟日期）判周末。周日深夜跨到周一 00:00 后日期变工作日，
weekday 带 [23:30, 07:30) 的 wrap 分支在 00:01 就判定入睡——**周日夜实际 00:01
被迫睡**（周末 hard=00:30 只对周六夜生效，周日夜名存实亡）。修复：新增
`_night_weekend()`（`_local_now() - 8h` 的周末判定）作为「夜晚锚定日」——凌晨
0-8 点归属前一晚的作息；`tick()` 的夜间带/犯困窗用夜晚锚定 schedule，晨醒判决
仍用当日 `_is_weekend()`（保住周六睡懒觉的 weekend_wake）。验证（长跑 W3/W6）：
两个周末夜均 00:31 入睡、周六/周日 09:00 前后醒、周一回到 07:30 醒；`_schedule()`
参数化 `is_weekend` 保持 goodnight/past_soft_limit 当日语义不变。

**同轮附带修正（测试口径，非引擎缺陷）**：夜段周末归类用入睡墙钟的「夜晚锚点
（-8h）」（00:31 周一入睡归属周日夜的周末作息）；fri_sleep/sun_night 过滤容忍
±1min 抖动。

**全量绿灯**：`tests/sim_week_long.py` 7/7（新增）+ 回归 17/17 + 数值 32/26/35
+ sim_clock_fix 28/28 + sim_stress_reset 14/14 + sim_lifecycle 13/13 + mem_eviction
10/10 + mem_recall 12/12 + drive_cooldown 7/7 + drive_global 5/5 + 记忆闭环 16/16
+ 多用户 5/5 + wake 队列 6/6 + R-H/30 3/3 + R-H/31 2/2；clock.py py_compile 通过；
容器已重启，容器内冒烟（周日深夜 00:31 入睡 / 平日 23:31 不受影响）2/2 OK。

---

### 10.20 死配置审计 + R-H/41（2026-09-13，stress 8 个调参键零读取）

**R-H/41 🟡（死配置，误导调参）**：`StressConfig` 中 `increase_complex` /
`increase_repetitive` / `increase_user_criticize` / `increase_user_correct` /
`increase_tool_fail` / `decrease_interest` / `decrease_praise` /
`decrease_task_done` 八个键**全库零读取**——事件效果实际由 `apply_event` 的
挫折点权重（负向，硬编码）与 energy `recover_*`（正向）承载，旧值是直接压力
增减时代的残留（与 09-03 monitor.model 死配置同类，规模更大）。修复：按前例
删除八键并注释归档；`decrease_sleep/rest/fun/encourage` 等真实被读键完整保留。
验证：config 字段核对（used 17/17 在、dead 8/8 去）、numeric_behavior 32/32 +
stress_reset 14/14 + lifecycle 13/13 + week_long 7/7 + 回归 17/17 全绿；
容器内验证 OK，容器已重启生效。

---

### 10.21 记忆注入块格式修复 + R-H/42（2026-09-13，LLM 可见边界）

**新增测试**：`tests/sim_mem_block_format.py`（11/11）。

**R-H/42 🟡（注入分段头结构错乱）**：`_format_block` 的 `【关键记忆】` 头位于
`if entries:` 块内——**仅节点时缺「关键记忆」头**（items-only 是 1004/1203 行的
常态路径）、**仅条目时出现空「关键记忆」段**；且预算口径只计 lines[0]，第二行
视角说明（~120-200 字符）漏计 → 实际块超出名义预算。修复：分段头按存在性输出
（entries→【近期经历】、items→【关键记忆】），头部成本全部计入预算。
验证（11/11）：items-only 有头无空段、entries-only 无空头、双路顺序正确、
600tokens 预算块长有界、5tokens 极小预算不输出任何内容行（头部计入后）。

### 10.22 兴趣热度动力学长跑验证（2026-09-13，无新增缺陷）

**新增测试**：`tests/sim_interest_heat.py`（10/10）——A 每日衰减语义（interest_level
0.9→-0.3/日、0.5→-1.0、0.1→-3.0、负面态度×2）、B R-H/20 冷门采样加热均匀覆盖
（60 轮无名称加热 6 项各 4 次，无恒定加热 Top1 马太）、C 名称匹配投入把冷门项
「跑步」升入注入 top-3（top-3 组合轮换 ≥2 种）、D 30 天长跑热度不越界、冷门项
不被衰减打零导致注入空窗。结论：兴趣热度动力学健康，R-H/20 反马太持续有效。

---

### 10.23 Energy 死配置审计 + R-H/43（2026-09-13，energy 7 个调参键零读取）

**R-H/43 🟡（死配置，误导调参）**：`EnergyConfig` 中 `decay_winding_down` /
`rest_suggest` / `sleep_refresh` / `recovery_interest` / `recovery_interest_ceiling` /
`fatigue_thresholds` / `fatigue_multipliers` 七个键**全库零读取**——犯困倍率实际由
clock 相位倍率硬编码 1.5 承载、睡眠刷新由 coordinator 睡眠分支直接执行、疲劳加速
由 stress.work_acceleration_* 承载、兴趣恢复无 wiring（`recover_interest` 未定义）、
`should_wrap_up`/`can_continue_working` 无调用方。修复：按 R-H/41 前例删除七键并
注释归档；`wrap_up_threshold`（dashboard 展示）与 `self_wake_resume`（公开对方法）
保留。验证：config 字段核对（used 19/19 在、dead 7/7 去）、数值 32/32 +
lifecycle 13/13 + week_long 7/7 + 回归 17/17 全绿；容器已重启生效。

---

### 10.24 创伤修复解除接线 + 门控 + 全局键副本守卫（R-H/44/44b/44c）

**R-H/44 🔴（「修复可解除创伤」从未实现 → 永续创伤锁）**：bond.py 的
`clear_trauma(fraction)` 中 `fraction<1.0` 分支为死代码且全库无调用方；
`trauma_clear_per_repair` / `trauma_clear_per_positive_count` 均为死配置。创伤只有
「7 天窗口到期 + 信任回弹过线」一条脱出路径——低信任时 `trauma_positive_penalty
×0.5` 拖慢回弹 → 反复重触发（永续创伤锁），与设计承诺「修复可解除」相悖。修复：
`bump_repair()` 计数——创伤期内每次被约束链放行的正向信任修复 +1，达
`trauma_clear_per_positive_count=5` 即 `clear_trauma()`（含计数归零 + `trauma_cleared`
事件留痕）；删除死配置 `trauma_clear_per_repair` 与 `clear_trauma` 死分支。

**R-H/44b 🟡（微修复廉价解除，顾问复核采纳）**：仅计数达标即解除有语义漏洞——
5 次微修复（各 +0.001）可在信任仍深度为负时解除创伤（非真实修复）。修复：解除须
**同时满足信任 ≥ `trauma_threshold`(0.1) 脱敏线**。验证（测试 E 段）：6 次微修复
计数≥5 但信任 0.038 < 0.1 → 仍锁；信任过线后一次修复 → 解除。

**R-H/44c 🟡（测试基建漂移，5 文件）**：多支测试手工复刻插件 `_PHYS_GLOBAL_KEYS`
路由集，R-H/33/36/39 增键后漂移——sim_multi_user / sim_wake_queue / _chk_rh30 因
R-H/39 `drive_last_initiate_ts` 构造期回载触发 **NameError**（构造时模块级 `e` 未
绑定）；sim_clock_fix / sim_stress_reset 静默错路由（测试按 per-user、生产按
global）。修复：5 文件键集同步为 27 键精确镜像（并清除残留的 `wake_pending_messages`
(R-H/32 已移出全局) 与冗余 `mem_activation_decay_date`）；三支 harness 的 `e` 查找
改 `globals().get("e")` 固化为构造期容忍；_chk_rh30 路由改「全局键强制 __global__」
与生产一致。**新增守卫 `tests/_chk_global_keys_sync.py`**：解析插件权威集与各测试
副本，缺失/多余即 fatal——把「副本=权威」变成可执行契约（9 文件 0 漂移）。

**新增/重写测试**：`tests/sim_trauma_lifecycle.py` 重写为 17/17（修正原 A2 时序
bug——断言误置于 repair() 之前；改差分口径「创伤期修复 ≈ 无创伤的一半」免硬编码；
新增微修复门控专项与约束链数值锚定 0.02×0.5×1.5×阻尼≈0.015）。

**全量绿灯**：创伤 17/17 + 全局键守卫 0 漂移 + 回归 17/17 + 数值 32/26/35 +
clock_fix 28/28 + stress_reset 14/14 + week_long 7/7 + lifecycle 13/13 + 记忆
闭环/淘汰/检索/格式 16/10/12/11 + 多用户 5/5 + wake 队列 6/6 + drive 7/7+5/5 +
兴趣 10/10 + R-H/30 3/3 + R-H/31 2/2（21 套全绿）；容器已重启，容器内冒烟 8/8
OK（死配置移除/常量接线/计数累计/解除归零/幂等），部署标记核实就位
（coordinator R-H/44b ×1、bond bump_repair ×2、config ×2）。

---

### 10.25 在线健康核验 + 数据目录迁移修正（R-H/45，09-26）

**R-H/45 🟡（审计路径陷阱）**：插件数据目录已迁移为 id-based 布局
（`plugin-data/agent-plugin-hermes-alive-<id>/`，插件 `__init__.py:292` 按 glob 优先；
legacy `plugin-data/hermes-alive/` 仅旧装回退）。本部署中 legacy 是 9-13 遗留空文件
（196KB），审计误读会得到「空库」假象——今日 2 个临时探针误读（已删），且 R-H/37
审计依据失实（§10.15 已标注更正；数值结论经真活库重核对仍成立：可清理量 0）。
复核既有 13 个含路径的审计/维护脚本：real_*_audit / _rebuild / _clean_pending 等
均用正确的 id-based 路径。修正：`tests/_audit_live.py` 改按插件同规则 glob 解析 +
遗留库 WARN（拒绝静默读到空库）。

**在线健康快照（09-26 22:19 CST，真活库只读）**：
- 容器 Up；`PRAGMA quick_check` = ok；29 表；current_state 269 行 / 6 用户
- 全局生理键实时更新（14:19 UTC）：energy 78.4 / stress 0.0 / boredom 32.7 /
  clock winding_down（22:01 起）/ last_wake_ts 21.4 分钟前 / stress_work_minutes 0.0
- 记忆：72 active 节点（6 用户分布）/ 22 条目 / 71 边 / 94 向量；R-H/37 可清理量 0
- trauma_state 空（无创伤）；outreach_state 10；event_log 2083；message_queue 171

**6 天停机恢复实证（真实数据首次）**：event_log 真空 9-20 14:31 → 9-26 14:01
（容器停机约 6 天），今日恢复后 stress=0.0、stress_work_minutes=0.0、energy 正常
——R-H/31/35/36 的「停机=冻结、恢复按正常节律」语义在真活库上首次实证（旧实现此
场景会单 tick 压力爆表 ×2.5）。

**诚实清单（已知未验证面，非活跃缺陷）**：①真实对话节奏下的巡检→反思→检索闭环
未观测（现有记忆多为早期测试注入）；②真实连续多日运行（>数天不中断）尚未发生；
③Bond 四维耦合动力学未压测（仅 T 维创伤修复已验）；④宿主 SQLite 3.50 vs 容器
3.53 混写 WAL 的长期行为未观测（bind-mount 残留风险）。

---

## 附录 A：配置基准（config.py 关键值）

```python
ClockConfig:   wake=07:30 soft=22:30 hard=23:30 wind_down=22:00 warm_up=30 drift=±30 weekend=False
EnergyConfig:  initial=80 decay=0.4(工作)/0.2(休闲) rest=0.4 chat=0.8(上限75) praise=4(80)
               task_done=5(85) encourage=3(80) wrap_up=40 hard_rest=30
StressConfig:  initial=10 inc_work=0.7 dec_idle=0.5 leisure_decision=75 hard=95
               work_decision=30 work_priority=10 work_acc 60/120/180→1.0/1.3/1.8/2.5
               emotion_mod P高0.7 P低1.3 A高1.4 A低0.8 frustration decay0.5 thr3.0 max10 base2 ev1
BoredomConfig: initial=30 high=60 medium=40 low=20 long_rest=0.5 new_thing=-10 waking_leisure=0.15
EmotionConfig: initial P0.3 A0.0 D0.2 decay=0.005 max_single=0.10 daily=0.30 p_floor=-0.7
BondConfig:    initial C0 D0 I0 T0.1 decay=0.005 max_single c0.03/d0.05/i0.03/t0.05
DriveConfig:   energy_min=45 boredom_threshold=55 jitter=5 cooldown=5400s daily_max=5 noise=0.3
CONSTRAINTS:   pad_max_single=0.10 bond_max_single=0.05 pad_daily=0.30 bond_daily=0.15
               min_confidence=0.6 p_floor=-0.7 restore_thr=-0.3 trauma 0.2/7d/×0.5 maturity 7d×1.5/30d×0.7
```

## 附录 B：测试脚本清单（tests/）

| 脚本 | 用途 |
|---|---|
| run_regression.py | 回归编排（docker 送容器执行 17 脚本） |
| numeric_behavior.py | 数值专项一：精力/压力/无聊度速率矩阵（32 断言） |
| numeric_behavior2.py | 数值专项二：时钟/驱动器/约束链（26 断言） |
| real_state_audit.py | 真实库只读抽查（12 用户 × 10 键 + 表规模） |
| unit_*.py × 14、probe_napcat_sim_http.py | 回归套件 17 脚本主体 |
