# hermes-alive

拟人生命周期系统插件 —— 让 Agent 拥有**作息、精力、压力、情绪、兴趣、内在驱动力与长期记忆**，像活人一样"有状态"地存在，而不是每次对话都从零开始的无状态程序。

> Agent 会在早上自然醒来、夜里犯困睡去；聊天聊久了会累、被夸了会开心；对感兴趣的话题越聊越热、太久没人理会有点无聊；空闲时偶尔主动找你分享一首歌、提醒你天气变冷——这一切不是写死的剧本，而是由一组互相耦合的生命状态实时驱动。

## 特性总览

| 模块 | 能力 |
|---|---|
| 作息时钟 | 起床/软入睡/硬入睡/晚间收尾（wind-down）时相，跨时区可配 |
| 生命状态 | 精力、压力、无聊感实时衰减与回复；压力分层（基线/休闲判定/硬切休闲） |
| 情绪引擎 | PAD 三维情绪空间 + 离散情绪标签 + 创伤事件记忆 |
| 双向羁绊 | 好感度/信任/亲密随互动自然演化，影响语气与主动性 |
| 兴趣系统 | 对话中捕获兴趣点 → 热度积累 → 淘汰/回升 → 影响主动话题选择 |
| 长期记忆 | DAG 知识库：人物/事件/约定自动沉淀 → 三路检索融合 → 第一人称"回想"注入；容量淘汰 + 每日淡忘 |
| 内在驱动力 | 空闲时主动发起（分享/关怀/回忆），带冷却、日上限与精力门槛 |
| 情感巡查 | 后台低频 LLM 复盘近期对话，把心理记账沉淀为状态变化（独立辅助模型槽，不烧主模型） |
| 发送前自检 | 以"自己"的身份复核即将发出的回复：人格漂移、语境错位、markdown 残留拦截 |
| 人格护栏 | 拟人腔漂移检测（本喵/尾巴…）与动作旁白（*歪头*）归一 |
| 管理面板 | Dashboard 实时查看生命状态、羁绊、兴趣与巡查记录 |

## 架构

```
hermes-alive/
├── __init__.py            # 插件入口：钩子注册、巡查/自检/驱动力全链路
├── engine/                # 生命状态机
│   ├── clock.py           #   作息时钟（时相/睡眠判定）
│   ├── energy.py          #   精力（活动消耗/休息回复/睡眠回复）
│   ├── stress.py          #   压力（工作/休闲模式切换）
│   ├── boredom.py         #   无聊感
│   ├── emotion.py         #   PAD 情绪空间与标签
│   ├── bond.py            #   双向羁绊
│   ├── drive.py           #   内在驱动力（主动发起）
│   ├── self_wake.py       #   自唤醒
│   ├── coordinator.py     #   状态协调器（跨模块联动、注入层）
│   ├── constants.py       #   物理常量
│   └── config.py          #   全量配置 dataclass（clock/energy/stress/…）
├── memory/                # 长期记忆（DAG 知识库）
│   ├── store.py           #   节点/条目/边 + FTS5/FAISS 三路检索与 RRF 融合
│   ├── normalize.py       #   文本归一与 n-gram 去重（守门层）
│   ├── reflect.py         #   反思流：把对话沉淀为经历条目
│   ├── embedding.py       #   向量编码
│   └── faiss_index.py     #   FAISS 索引（可选，缺失自动降级）
├── observer/
│   └── patrol_context.py  # 巡查 prompt 构建/响应解析（情感事件分类、立场回顾）
├── storage/
│   └── db.py              # SQLite 持久层（状态/羁绊/兴趣/巡查上下文/长期记忆）
├── dashboard/
│   ├── plugin_api.py      # 面板 API（FastAPI 路由）
│   ├── manifest.json      # 面板清单
│   └── dist/              # 预构建前端（index.js / style.css）
├── plugin.yaml            # 插件清单（工具/钩子声明）
└── RULE.md                # Agent 自我约束文件（由 Agent 自己维护）
```

## 安装

1. 将本目录放入 Hermes agent 的插件目录：

```
<hermes-data>/plugins/hermes-alive/
```

2. 在 `config.yaml` 的 `plugins.enabled` 中加入 `hermes-alive`。
3. 重启网关（或宿主进程）完成装载。

### 常见安装问题（容器 / bind-mount 场景）

从宿主直接拷入插件目录时，文件属主常为 `root` 且权限过窄，容器内的 Hermes 服务
用户可能读不到，表现为启动日志出现 `⚠ Could not load config.yaml` 或
`PermissionError: .../logs/agent.log`。在容器内修正一次即可：

```sh
docker exec -u 0 <容器> chmod -R a+rX /opt/data/plugins/hermes-alive
docker exec -u 0 <容器> chown -R <服务用户> /opt/data/plugin-data
```

Dashboard 绑定 `0.0.0.0` 前需要先配置认证（`dashboard.basic_auth` 或 OAuth），
否则宿主会拒绝监听非回环地址。

## 配置

完整配置在 `config.yaml` 的 `plugins.entries.hermes-alive.settings.alive` 下，未配置的键均取合理默认值：

```yaml
plugins:
  enabled:
    - hermes-alive
  entries:
    hermes-alive:
      allow_gateway_injection: true
      settings:
        alive:
          clock:
            timezone: Asia/Shanghai   # Agent 生活的时区
            wake_time: '07:30'        # 起床
            sleep_soft_time: '22:30'  # 软入睡（开始犯困）
            sleep_hard_time: '23:30'  # 硬入睡
            wind_down_start: '22:00'  # 晚间收尾
          monitor:
            step_interval: 4          # 每 N 步触发一次情感巡查（PAD 情绪由 LLM 结算，4 步保证及时）
            max_stall_seconds: 3600   # 低频对话下巡查最迟兑现间隔（秒）
```

### 辅助模型槽（省成本）

巡查与发送前自检是高频后台链路，注册为独立 auxiliary 任务，可在 `config.yaml` 顶层为其指定便宜模型，主模型升档不带动这两条链路烧钱：

```yaml
auxiliary:
  alive_patrol:            # 情感巡查分析（事件分类 + 立场回顾）
    provider: openai
    model: gpt-4o-mini
  alive_presend:           # 发送前自检（人格/语境复核）
    provider: openai
    model: gpt-4o-mini
```

不配置时使用宿主默认辅助路由（provider=auto）。

## 提供的工具

| 工具 | 说明 |
|---|---|
| `memory_memorize` | 把重要的事记进长期记忆（人物/约定/事件/喜好） |
| `memory_recall` | 按话题检索长期记忆（支持时间过滤） |
| `alive_social_status` | 查询主动联系记录与关系值（C 亲密 / D 依赖 / I 在意 / T 信任） |

另提供 `/alive`（状态查看）与 `/alive-rest`（进入能量小憩）两个命令。

## 钩子

`pre_llm_call` / `post_llm_call`（状态注入与回收）、`on_session_start` / `on_session_end`（会话生命周期记账）、`post_tool_call`（cron 护栏等）、`transform_llm_output`（发送前自检与人格归一）。

## 数据

全部状态持久化于 SQLite（`alive.db`），随插件数据目录存放；删除即重置 Agent 的"人生"。
长期记忆（节点/条目/关联边/向量）同库共存，全文（FTS5）与向量（FAISS）双索引；
容量淘汰 + 每日淡忘 + 超窗物理清理，记忆会褪色但不会无限膨胀。

## 设计说明

完整设计文档（理念、状态机细节、机制取舍）见 [DESIGN.md](DESIGN.md)。

- **状态先于剧情**：所有拟人行为都从生命状态推导（精力低→懒散敷衍，压力大→语气紧绷，无聊→主动找话题），而不是随机模板。
- **护栏分层**：模型自由发挥在外，人格护栏与发送前自检在内——越界的表达在出口处被归一，而不是压制模型的个性。
- **后台账本**：情感巡查把对话里发生的心理事件（被夸、被忽略、共同回忆）在低频后台链路里结算成状态增量，对话线程保持干净。
- **记忆有分寸**：记忆是"回想"而不是"事实命令"——注入时以第一人称经历呈现，与对方当下的话冲突时以当下为准；记什么、记多久由守门与淘汰机制约束。

## 测试与质量

持续红队审计累计修复 45 项（时间语义、数值矩阵、多用户隔离、记忆检索、调度架构），
端到端 / 数值 / 长跑共 21 套测试常绿。审计记录见 [docs/TESTING.md](docs/TESTING.md)。
另已在**全新 Hermes agent（干净容器）**完成纯净安装验证：插件装载、工具注册、
数据目录/数据库自建、面板路由挂载与冷启动默认态全部通过。

## License

[MIT](LICENSE)
