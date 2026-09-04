"""Default configuration values. All values overridable via config.yaml or Web UI."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ClockConfig:
    wake_time: str = "07:30"
    sleep_soft_time: str = "22:30"
    sleep_hard_time: str = "23:30"
    wind_down_start: str = "22:00"
    warm_up_minutes: int = 30
    # R2（09-01）：作息相位锚定时区（如 "Asia/Shanghai"）；空=跟随进程时区。
    # 只动作息域；cron/调度/日志保持进程时区不变。
    timezone: str = "" 
    drift_range: int = 30
    goodnight_keywords: list[str] = field(default_factory=lambda: [
        "晚安", "good night", "去睡", "休息了", "明天见",
    ])
    goodnight_window: int = 10
    weekend_enabled: bool = False
    weekend_wake: str = "09:00"
    weekend_soft: str = "23:30"
    weekend_hard: str = "00:30"


@dataclass
class EnergyConfig:
    max_value: float = 100.0
    initial: float = 80.0
    # 唤醒期间衰减（工作/休闲）
    decay_rate: float = 0.4          # 工作时精力衰减/分钟
    decay_leisure: float = 0.2       # 休闲时精力衰减/分钟（比工作慢）
    decay_winding_down: float = 1.5  # 犯困阶段衰减倍率
    # 休息恢复（每分钟）
    recovery_rest_rate: float = 0.4  # 休息时精力恢复/分钟（40→100约150分钟）
    # 自唤醒
    self_wake_threshold: float = 100.0  # 自唤醒所需精力（必须回满）
    self_wake_resume: float = 70.0      # 唤醒后继续工作的精力门槛
    wrap_up_threshold: float = 40.0     # 精力40：引导级收尾（决策点）
    hard_rest_threshold: float = 30.0   # 精力30：强制级硬限制
    rest_suggest: float = 30.0
    sleep_refresh: bool = True
    # 一次性恢复（用户交互）
    recovery_rest: float = 8.0
    recovery_short_rest: float = 18.0
    recovery_praise: float = 4.0
    recovery_task_done: float = 5.0
    recovery_chat: float = 0.8
    recovery_chat_ceiling: float = 75.0
    recovery_interest: float = 0.6
    recovery_interest_ceiling: float = 70.0
    recovery_encourage: float = 3.0
    recovery_encourage_ceiling: float = 80.0
    recovery_praise_ceiling: float = 80.0
    recovery_task_ceiling: float = 85.0
    fatigue_thresholds: list[int] = field(default_factory=lambda: [30, 60, 120])
    fatigue_multipliers: list[float] = field(default_factory=lambda: [1.0, 1.2, 1.5, 2.0])


@dataclass
class StressConfig:
    max_value: float = 100.0
    initial: float = 10.0
    # 切换节点（用户设计）
    baseline_threshold: float = 50.0      # 初始分界线：50以下干活，50以上压力上升
    leisure_decision_threshold: float = 75.0  # 工作→休闲决策点（引导级）
    hard_leisure_threshold: float = 95.0      # 工作→休闲硬限制（强制级）
    work_decision_threshold: float = 30.0     # 休闲→工作决策点（引导级）
    work_priority_threshold: float = 10.0     # 休闲→工作优先节点（引导级）
    # 速率
    increase_work: float = 0.7           # 工作时压力增长/分钟
    increase_complex: float = 0.25
    increase_repetitive: float = 0.30
    increase_tool_fail: float = 2.0
    increase_user_criticize: float = 5.0
    increase_user_correct: float = 1.5
    decrease_idle: float = 0.5           # 休闲时压力降低/分钟
    decrease_browse: float = 0.10
    decrease_interest: float = 0.15
    decrease_sleep: float = 0.30
    decrease_praise: float = 5.0
    decrease_task_done: float = 3.0
    decrease_encourage: float = 4.0
    decrease_rest: float = 8.0
    decrease_fun: float = 6.0
    # 连续工作时间加速（设计文档 section 4.3）
    work_acceleration_thresholds: list[int] = field(default_factory=lambda: [60, 120, 180])
    work_acceleration_multipliers: list[float] = field(default_factory=lambda: [1.0, 1.3, 1.8, 2.5])
    # 情绪对压力的调制（设计文档 section 6）
    emotion_modulation_enabled: bool = True
    emotion_p_high_threshold: float = 0.3
    emotion_p_low_threshold: float = -0.3
    emotion_a_high_threshold: float = 0.3
    emotion_a_low_threshold: float = -0.3
    emotion_p_high_multiplier: float = 0.7
    emotion_p_low_multiplier: float = 1.3
    emotion_a_high_multiplier: float = 1.4
    emotion_a_low_multiplier: float = 0.8
    # 挫折累积系统
    frustration_decay_rate: float = 0.5      # 每分钟自然衰减
    frustration_threshold: float = 3.0       # 触发压力增长的阈值
    frustration_max: float = 10.0            # 挫折点上限
    frustration_base_increase: float = 2.0   # 触发时的基础压力增量
    frustration_event_points: float = 1.0    # 单次挫折事件的挫折点


@dataclass
class BoredomConfig:
    max_value: float = 100.0
    initial: float = 30.0
    high_threshold: float = 60.0
    medium_threshold: float = 40.0
    low_threshold: float = 20.0
    increase_long_rest: float = 0.5
    decrease_new_thing: float = 10.0
    # R12/D5（设计14 §3.2 实装形态）：清醒+休闲模式下无聊度温和上升速率/分钟
    increase_waking_leisure: float = 0.15


@dataclass
class SelfWakeConfig:
    enabled: bool = True
    min_interval: int = 30
    max_duration: int = 120
    stress_threshold_leisure: float = 70.0


@dataclass
class HobbyConfig:
    hobbies_max: int = 10
    hobbies_hot: int = 3
    doing_max: int = 15
    doing_hot: int = 4
    things_max: int = 20
    things_hot: int = 5
    curiosity_base: float = 50.0
    curiosity_decay: float = 0.5
    curiosity_explore_threshold: float = 60.0
    curiosity_cooldown_hours: int = 4
    heat_initial: float = 90.0
    heat_daily_decay: float = 1.0
    heat_usage_boost: float = 15.0
    heat_enjoyment_bonus: float = 10.0


@dataclass
class EmotionConfig:
    initial_p: float = 0.3
    initial_a: float = 0.0
    initial_d: float = 0.2
    decay_rate: float = 0.005
    max_single_change: float = 0.10
    daily_limit: float = 0.30
    p_floor: float = -0.7
    p_restore_threshold: float = -0.3
    negative_damping_factor: float = 0.5


@dataclass
class BondConfig:
    initial_c: float = 0.0
    initial_d: float = 0.0
    initial_i: float = 0.0
    initial_t: float = 0.1  # 初始信任度设为0.1，避免立即触发trauma
    decay_rate: float = 0.005
    max_single_c: float = 0.03
    max_single_d: float = 0.05
    max_single_i: float = 0.03
    max_single_t: float = 0.05
    daily_limit_c: float = 0.08
    daily_limit_d: float = 0.12
    daily_limit_i: float = 0.10
    daily_limit_t: float = 0.15
    trauma_threshold: float = 0.1  # 降低阈值到0.1，只有严重背叛才触发
    trauma_window_days: int = 7
    trauma_positive_penalty: float = 0.5
    trauma_clear_per_repair: float = 0.5
    trauma_clear_per_positive_count: int = 5
    relationship_maturity_days: int = 30


@dataclass
class MonitorConfig:
    enabled: bool = True
    # 巡查模型由宿主 auxiliary.alive_patrol/alive_presend 槽决定（R13/G5），
    # 此处不设 model——历史上该键是死配置，只会误导调参（09-03 死配置审计）。
    step_interval: int = 10
    # R1（09-01）：距上次巡查超过该秒数且本轮≥2步即兜底触发（0=禁用）。
    # 低频对话下轮数门要等几天，心理记账（表扬回血/无聊度回落）会饿死。
    max_stall_seconds: int = 14400
    max_context_messages: int = 20
    confidence_threshold: float = 0.6
    high_confidence: float = 0.8
    quick_calibration_p_floor: float = -0.3


@dataclass
class DriveConfig:
    """设计14 内在驱动力配置。"""
    enabled: bool = True
    energy_min: float = 45.0
    boredom_threshold: float = 55.0
    threshold_jitter_sigma: float = 5.0
    # R13/G6（§八护栏+成本定标）：主动发起最快 90 分钟一次，每本地日封顶 daily_max 轮
    cooldown_seconds: int = 5400
    daily_max: int = 5
    noise_sigma: float = 0.3
    feedback_min: float = 0.3
    # R12b（§3.6）：主动触达被"回应"后隔多久之内仍值得认领为接纳（小时，0=禁用认领）
    ack_fresh_hours: int = 24
    feedback_max: float = 2.0
    feedback_step: float = 0.1


@dataclass
class SocialConfig:
    """自主期社交行为（设计12）：全部可配置，禁止硬编码散落。"""
    reply_wait_minutes: int = 5        # 主动消息等待回应时长（分钟）
    max_unanswered: int = 2            # 连续无回应放弃阈值
    cooldown_hours: int = 2            # 放弃后的冷却时长（小时）
    nudge_interval_minutes: int = 30   # 唤醒期静默再推间隔
    nudge_max: int = 3                 # 每个唤醒期最多再推次数
    profile_dir: str = ""              # 画像目录，缺省 {HERMES_HOME}/memories/users
    # —— 设计13 §4：personality 配置组（纯注入文案参数，零代码分支，按档位选预置文案变体）——
    self_priority: float = 0.5         # 自我优先度 0-1：天平默认倾向。高→更常“先忙自己的”；低→随叫随到
    candor: float = 0.6                # 直率度：高→熟人生人都直说；低→惯用台阶话术
    indulgence: float = 0.7            # 宠溺度：高→对高bond用户几乎不拒
    night_owl: bool = False            # 作息弹性人设：影响 wind_down 后的配合度
    # —— 设计13 §6.2 H3：借口频率计数器 ——
    excuse_daily_threshold: int = 3    # 同一 uid 单日婉拒特征计数上限（超过→置自省槽位，只记不拦）
    # —— 单一意识（设计10）：主用户/意识流锚点。生命周期注入与镜像恒定归属该会话 ——
    main_user_id: str = "111111111"


@dataclass
class AliveConfig:
    clock: ClockConfig = field(default_factory=ClockConfig)
    energy: EnergyConfig = field(default_factory=EnergyConfig)
    stress: StressConfig = field(default_factory=StressConfig)
    boredom: BoredomConfig = field(default_factory=BoredomConfig)
    self_wake: SelfWakeConfig = field(default_factory=SelfWakeConfig)
    hobby: HobbyConfig = field(default_factory=HobbyConfig)
    emotion: EmotionConfig = field(default_factory=EmotionConfig)
    bond: BondConfig = field(default_factory=BondConfig)
    monitor: MonitorConfig = field(default_factory=MonitorConfig)
    social: SocialConfig = field(default_factory=SocialConfig)
    drive: DriveConfig = field(default_factory=DriveConfig)


def _coerce(val, target_type):
    """配置值类型转换（config.yaml / Web UI 传入的数值与布尔常是字符串）。"""
    if val is None:
        return None
    try:
        if target_type is bool:
            if isinstance(val, bool):
                return val
            return str(val).strip().lower() in ("1", "true", "yes", "on")
        if target_type is int:
            return int(float(str(val).strip()))
        if target_type is float:
            return float(str(val).strip())
        if target_type is list and not isinstance(val, list):
            import json as _json
            return _json.loads(val)
    except (ValueError, TypeError, AttributeError):
        return val  # 转换失败保留原值，交由上层报错
    return val


def load_config(get_config_fn) -> AliveConfig:
    """Load config from Hermes plugin settings, falling back to defaults."""
    cfg = AliveConfig()
    prefix = "alive"
    for section_name in ["clock", "energy", "stress", "boredom", "self_wake", "hobby", "emotion", "bond", "monitor", "social", "drive"]:
        section = getattr(cfg, section_name)
        for field_name in section.__dataclass_fields__:
            key = f"{prefix}.{section_name}.{field_name}"
            val = get_config_fn(key, None)
            if val is not None:
                default = getattr(section, field_name)
                setattr(section, field_name, _coerce(val, type(default)))
    return cfg
