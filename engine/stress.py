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
        self._set("activity_mode", mode)

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
        """获取连续工作时间（分钟）"""
        if self._work_start_time is None:
            return 0.0
        return (_time.time() - self._work_start_time) / 60.0

    def _get_work_acceleration_multiplier(self) -> float:
        """获取连续工作时间加速倍率（设计文档 section 4.3）"""
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

    def tick(self, emotion_p: float = 0.0, emotion_a: float = 0.0) -> None:
        """Stress increases during work, decreases during leisure."""
        current = self.get()
        mode = self.get_mode()

        # 计算时间间隔
        now = _time.time()
        elapsed_minutes = 1.0  # 默认1分钟
        if self._last_tick_time is not None:
            elapsed_minutes = max(0.1, (now - self._last_tick_time) / 60.0)
        self._last_tick_time = now

        # 挫折点自然衰减
        self.decay_frustration(elapsed_minutes)

        # 检查挫折阈值触发
        frustration_increase = self.check_frustration_threshold()

        if mode == StressMode.WORKING:
            # 追踪连续工作时间
            if self._work_start_time is None:
                self._work_start_time = _time.time()

            # 基础增长
            increase = self.cfg.increase_work

            # 连续工作时间加速（设计文档 section 4.3）
            acceleration = self._get_work_acceleration_multiplier()
            increase *= acceleration

            # 情绪调制（设计文档 section 6）
            emotion_mult = self._get_emotion_multiplier(emotion_p, emotion_a)
            increase *= emotion_mult

            # 加上挫折触发的增量
            increase += frustration_increase

            new_val = current + increase
        else:
            # 休闲模式：重置连续工作时间
            self._work_start_time = None

            decrease = self.cfg.decrease_idle

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
