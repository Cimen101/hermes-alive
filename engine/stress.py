"""Stress system with hysteresis, acceleration, and emotion modulation."""
from __future__ import annotations
import time as _time
from .config import StressConfig


class StressMode:
    WORKING = "working"
    LEISURE = "leisure"


class StressManager:
    def __init__(self, cfg: StressConfig, get_state, set_state):
        self.cfg = cfg
        self._get = get_state
        self._set = set_state
        self._work_start_time: float | None = None  # 连续工作开始时间
        self._last_tick_time: float | None = None    # 上次tick时间

    def get(self) -> float:
        try:
            return float(self._get("stress", self.cfg.initial))
        except (TypeError, ValueError):
            return float(self.cfg.initial)

    def set(self, val: float) -> None:
        self._set("stress", max(0.0, min(self.cfg.max_value, val)))

    def get_mode(self) -> str:
        return self._get("activity_mode", StressMode.WORKING)

    def set_mode(self, mode: str) -> None:
        """切换工作/休闲，统一维护连续工作计时（持久化，重启不丢）。

        R-H/2（红队审查）：_work_start_time 原为内存态，进程重启后
        60/120/180min 加速档永远无法到达；此处落到 __global__ 状态键，
        内存字段仅作兼容回退（测试/热更直写场景）。
        R-H/36（红队）：进入新工作段/离开工作段时同步归零增量分钟计数
        （stress_work_minutes），避免新旧会话累计。
        """
        prev = self.get_mode()
        self._set("activity_mode", mode)
        if mode == StressMode.WORKING:
            # 无起点（含 prev 本就是 working 的首次/重启场景）也要补记：
            # 默认 activity_mode=working，仅判 prev 会永远跳过起点写入
            if prev != StressMode.WORKING or not self._get("stress_work_start_ts", None):
                now = _time.time()
                self._work_start_time = now
                self._set("stress_work_start_ts", now)
                self._commit_work_minutes(0.0)
        elif mode != StressMode.WORKING:
            self._work_start_time = None
            self._set("stress_work_start_ts", 0)
            self._commit_work_minutes(0.0)

    def reset_work_timer(self) -> None:
        """R-H/35（红队）：休息/睡眠开始 = 工作段中断——连续工作计时与
        压力加速倍率归零。原实现计时只在 leisure 切换/工作起点写入，午睡或
        夜间睡眠后 activity_mode 仍为 working，连续工作分钟跨休息段累计
        （睡醒立刻按「连续工作 180min ×2.5」超负荷状态工作，不拟人）。"""
        self._work_start_time = None
        self._set("stress_work_start_ts", 0)
        self._commit_work_minutes(0.0)

    def _commit_work_minutes(self, minutes: float) -> None:
        self._set("stress_work_minutes", float(minutes))

    def anchor_tick(self) -> None:
        """R-H/36（红队）：休息/睡眠分支每 tick 推进计时基准。

        休息/睡眠期间不走 stress.tick，stress_last_tick_ts 会停留在入休时刻；
        恢复后首个工作 tick 把整段休息时长折算进 real_elapsed（cap 60）
        → 压力/计数被灌入（如 2h 午睡后一睁眼先结算 60min 工作）。此处
        逐 tick 推进基准，恢复后按正常 1min 续推。"""
        self._last_tick_time = _time.time()
        self._set("stress_last_tick_ts", self._last_tick_time)

    # ── 挫折累积系统 ──

    def get_frustration(self) -> float:
        """获取当前挫折点"""
        val = self._get("frustration_points", 0.0)
        return float(val) if val is not None else 0.0

    def set_frustration(self, val: float) -> None:
        self._set("frustration_points", max(0.0, min(self.cfg.frustration_max, val)))

    def add_frustration(self, points: float = None) -> None:
        """添加挫折点（单次事件不直接增加压力）"""
        if points is None:
            points = self.cfg.frustration_event_points
        current = self.get_frustration()
        self.set_frustration(current + points)

    def reduce_frustration(self, points: float) -> None:
        """正面事件减少挫折点"""
        current = self.get_frustration()
        self.set_frustration(current - points)

    def decay_frustration(self, minutes: float) -> None:
        """挫折点自然衰减"""
        current = self.get_frustration()
        decay = self.cfg.frustration_decay_rate * minutes
        self.set_frustration(current - decay)

    def check_frustration_threshold(self) -> float:
        """检查挫折点是否达到阈值，返回压力增量（0表示未触发）"""
        frustration = self.get_frustration()
        if frustration < self.cfg.frustration_threshold:
            return 0.0

        # 触发：挫折点转化为压力
        # 增量与当前压力正相关（压力越高，挫折影响越大）
        current_stress = self.get()
        pressure_coefficient = 1.0 + (current_stress / self.cfg.max_value)
        increase = self.cfg.frustration_base_increase * pressure_coefficient

        # 重置挫折点（消耗一半，不是全部清零）
        self.set_frustration(frustration * 0.5)

        return increase

    def _get_continuous_work_minutes(self) -> float:
        """获取连续工作分钟数（旧墙钟折算口径，仅供兼容回退/测试直写）。

        R-H/36（红队）：主口径已改「增量计数」（stress_work_minutes，
        见 tick）；本方法仅在被显式调用/迁移折算时使用，停机等长时间
        空档会按墙钟折算灌入时长，因此迁移折算处统一 cap 60。
        """
        start = self._work_start_time
        if start is None:
            try:
                v = self._get("stress_work_start_ts", None)
                start = float(v) if v else None
            except (TypeError, ValueError):
                start = None
        if start is None:
            return 0.0
        return max(0.0, (_time.time() - float(start)) / 60.0)

    def _get_work_minutes_counter(self) -> float:
        """R-H/36：连续工作分钟增量计数（持久化，重启不丢）。

        每 tick 只累加「本次结算的真实经过分钟」（real_elapsed，cap 60），
        停机/重启产生的墙钟空档**不灌入**——与 R-H/31「停机=压力冻结」
        语义一致，避免 3 天停机后恢复的第一 tick 直接 ×2.5 超负荷爆表。
        旧部署无该键时一次性从 stress_work_start_ts 折算（cap 60 防通胀）。
        """
        v = self._get("stress_work_minutes", None)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                return 0.0
        # 迁移折算：旧键一次性初始化，cap 60（与 R-H/31 单 tick 上限同源）
        return min(60.0, self._get_continuous_work_minutes())

    def _get_work_acceleration_multiplier(self, minutes: float | None = None) -> float:
        """获取连续工作时间加速倍率（设计文档 section 4.3）

        minutes：显式传入增量计数（tick 主路径，R-H/36 增量不灌停机时长）；
        None 时回退旧墙钟折算口径（无参调用，仅测试直写/兼容保留）。"""
        if minutes is None:
            minutes = self._get_continuous_work_minutes()
        thresholds = self.cfg.work_acceleration_thresholds
        multipliers = self.cfg.work_acceleration_multipliers

        for i, threshold in enumerate(thresholds):
            if minutes < threshold:
                return multipliers[i]
        return multipliers[-1]

    def _get_emotion_multiplier(self, emotion_p: float, emotion_a: float) -> float:
        """获取情绪对压力增长的调制倍率（设计文档 section 6）"""
        if not self.cfg.emotion_modulation_enabled:
            return 1.0

        multiplier = 1.0

        # P(愉悦性)调制
        if emotion_p > self.cfg.emotion_p_high_threshold:
            multiplier *= self.cfg.emotion_p_high_multiplier  # 心情好时压力增长慢
        elif emotion_p < self.cfg.emotion_p_low_threshold:
            multiplier *= self.cfg.emotion_p_low_multiplier  # 心情差时压力增长快

        # A(激活度)调制
        if emotion_a > self.cfg.emotion_a_high_threshold:
            multiplier *= self.cfg.emotion_a_high_multiplier  # 焦虑时压力增长更快
        elif emotion_a < self.cfg.emotion_a_low_threshold:
            multiplier *= self.cfg.emotion_a_low_multiplier  # 冷静时压力增长略慢

        return multiplier

    def tick(self, emotion_p: float = 0.0, emotion_a: float = 0.0,
             minutes: float | None = None) -> None:
        """Stress increases during work, decreases during leisure.

        R-H/1（红队审查）：增长/降低量按真实 elapsed 分钟缩放——此前固定
        按 1 分钟结算，tick 间隔拉长（容器 pause/重启/忙碌）时压力增速失真。
        挫折/事件为离散跳变，不缩放。

        minutes：显式指定本次推进的分钟数（测试/批量回放用）；
        为 None 时按内部计时（持久化键优先）推算真实经过时间。
        """
        current = self.get()
        mode = self.get_mode()

        # 计算时间间隔（持久化键优先，内存回退）
        now = _time.time()
        try:
            _p = self._get("stress_last_tick_ts", None)
            persisted_ts = float(_p) if _p else None
        except (TypeError, ValueError):
            persisted_ts = None
        last_ts = persisted_ts if persisted_ts is not None else self._last_tick_time
        # R-H/31（红队）：单 tick 最多结算 60 分钟。长时间停机（容器/Docker 关闭
        # 数天）后恢复时，real_elapsed 会一次推算数千分钟——working 下压力单
        # tick 暴增→瞬间 clamp 100→强切 leisure 连锁；而 energy 无 elapsed 缩放
        # （停机=冻结）。语义对齐：停机期间压力同样"不积累"，恢复后按正常节律续推。
        if minutes is not None:
            real_elapsed = max(0.1, min(60.0, float(minutes)))
        elif last_ts is not None:
            real_elapsed = max(0.1, min(60.0, (now - float(last_ts)) / 60.0))
        else:
            real_elapsed = 1.0
        self._last_tick_time = now
        self._set("stress_last_tick_ts", now)

        # 挫折点自然衰减
        self.decay_frustration(real_elapsed)

        # 检查挫折阈值触发
        frustration_increase = self.check_frustration_threshold()

        if mode == StressMode.WORKING:
            # 追踪连续工作时间（持久化，重启不丢）
            if self._work_start_time is None and not persisted_ts:
                self._work_start_time = now
                self._set("stress_work_start_ts", now)

            # 基础增长 × 时间缩放 × 加速（事件跳变不缩放）
            base = self.cfg.increase_work
            # R-H/36：增量分钟计数——停机空档不灌入墙钟时长
            seg_mins = self._get_work_minutes_counter() + real_elapsed
            self._commit_work_minutes(seg_mins)
            base *= self._get_work_acceleration_multiplier(seg_mins)   # 连续工作加速
            base *= self._get_emotion_multiplier(emotion_p, emotion_a)  # 情绪调制
            increase = base * real_elapsed
            # 加上挫折触发的增量（离散事件量）
            increase += frustration_increase

            new_val = current + increase
        else:
            # 休闲模式：重置连续工作时间（含持久化）
            self.reset_work_timer()

            decrease = self.cfg.decrease_idle * real_elapsed

            # 休闲时压力降低更快（如果有挫折点，也一并消散）
            if frustration_increase > 0:
                decrease += frustration_increase * 0.5  # 休闲时挫折转化为恢复

            new_val = current - decrease

        new_val = max(0.0, min(self.cfg.max_value, new_val))
        self.set(new_val)

    def check_mode_switch(self) -> str | None:
        """Check stress zone and return the current decision state.

        返回事件类型（供提示词注入使用）：
        - 工作模式：
          - "stress:leisure_decision"  → 压力≥75，引导级决策点（LLM判断是否休闲）
          - "stress:leisure_hard"      → 压力≥95，强制级硬限制（必须休闲）
        - 休闲模式：
          - "stress:work_decision"     → 压力≤30，引导级决策点（LLM判断是否工作）
          - "stress:work_priority"     → 压力≤10（含0），引导级优先节点（有任务就去工作）
        """
        current = self.get()
        mode = self.get_mode()

        if mode == StressMode.WORKING:
            # 压力≥95：硬限制，必须收尾去休闲
            if current >= self.cfg.hard_leisure_threshold:
                self.set_mode(StressMode.LEISURE)
                return "stress:leisure_hard"
            # 压力≥75：决策点，LLM判断是否休闲
            if current >= self.cfg.leisure_decision_threshold:
                return "stress:leisure_decision"
            # 压力<75：继续工作
            return None
        else:
            # R13/G3：原"压力=0 保持休闲"分支方向与设计05 §8相反，
            # 且遮蔽 work_priority 使 s=0 永锁休闲——删除，s=0 走 ≤10 优先节点
            # 压力≤10：优先节点，有任务就去工作
            if current <= self.cfg.work_priority_threshold:
                return "stress:work_priority"
            # 压力≤30：决策点，LLM判断是否工作
            if current <= self.cfg.work_decision_threshold:
                return "stress:work_decision"
            # 压力>30：继续休闲
            return None

    def apply_event(self, event_type: str, intensity: str = "mild") -> None:
        """Apply event effect — 负面事件累积挫折点，正面事件减少挫折点+直接减压"""
        current = self.get()

        # ── 负面事件：累积挫折点（不直接增加压力）──
        negative_events = {
            "negative_feedback": 1.5,   # 用户不满
            "trust_violation": 2.0,     # 信任违规
            "user_criticize": 1.5,      # 用户批评
            "user_correct": 0.8,        # 用户纠正
            "tool_failure": 1.0,        # 工具失败
            "task_failure": 1.0,        # 任务失败
        }
        intensity_mult = {"mild": 0.5, "moderate": 1.0, "strong": 1.5}.get(intensity, 1.0)

        if event_type in negative_events:
            points = negative_events[event_type] * intensity_mult
            self.add_frustration(points)
            return  # 不直接增加压力

        # ── 正面事件：减少挫折点 + 直接减压 ──
        positive_events = {
            "positive_feedback": 2.0,    # 用户满意
            "encouragement": 1.5,        # 用户鼓励
            "repair_attempt": 1.0,       # 修复尝试
            "task_success": 1.5,         # 任务成功
            "praise": 2.0,              # 用户表扬
        }
        if event_type in positive_events:
            points = positive_events[event_type] * intensity_mult
            self.reduce_frustration(points)
            # 同时直接减压
            decrease = {"mild": 1.0, "moderate": 2.0, "strong": 3.0}.get(intensity, 1.0)
            self.set(current - decrease)
            return

        # ── 恢复事件：直接减压 ──
        recovery_events = {
            "rest_taken": self.cfg.decrease_rest,
            "interest_enjoyed": self.cfg.decrease_fun,
            "browse": self.cfg.decrease_browse,
            "sleep": self.cfg.decrease_sleep,
            "encourage": self.cfg.decrease_encourage,
        }
        if event_type in recovery_events:
            self.set(current - recovery_events[event_type])

    def get_work_willingness(self, emotion_p: float) -> float:
        """Combined work willingness from stress + emotion P."""
        stress_ratio = 1.0 - (self.get() / self.cfg.max_value)
        p_normalized = (emotion_p + 1.0) / 2.0
        return p_normalized * 0.4 + stress_ratio * 0.6
