"""Self-wake manager — controls the autonomous wake/rest cycle.

设计11核心原则：
- 单次唤醒总时长 2~3 小时（由精力从满到耗尽的衰减时长决定）
- 唤醒后休息 2~3 小时（精力回满后自唤醒）
- 精力系统只负责唤醒/休息时机，不决定醒来后干什么
"""
from __future__ import annotations
import time as _time
from .config import SelfWakeConfig


class SelfWakeManager:
    def __init__(self, cfg: SelfWakeConfig, get_state, set_state):
        self.cfg = cfg
        self._get = get_state
        self._set = set_state

    # ── 休息态（能量小憩，与夜间睡眠 clock_phase 完全解耦）──

    def is_resting(self) -> bool:
        return bool(self._get("energy_resting", 0))

    def start_rest(self) -> None:
        self._set("energy_resting", 1)
        self._set("rest_started_at", _time.time())

    def end_rest(self) -> None:
        self._set("energy_resting", 0)
        self._set("last_wake_ts", _time.time())
        # R-H/34（红队）：新清醒周期开始，重置一次性 wake_cap 信号——
        # 原只置 1 从不重置，清醒超时提醒一生只触发一次；能量小憩/睡眠后
        # 应重新武装，让每个清醒周期都能再提醒。
        self._set("wake_cap_signaled", 0)

    def rest_duration_minutes(self) -> float:
        started = self._get("rest_started_at", None)
        if not started:
            return 0.0
        try:
            return max(0.0, (_time.time() - float(started)) / 60.0)
        except (TypeError, ValueError):
            return 0.0

    def minutes_since_last_wake(self) -> float | None:
        ts = self._get("last_wake_ts", None)
        if not ts:
            return None
        try:
            return max(0.0, (_time.time() - float(ts)) / 60.0)
        except (TypeError, ValueError):
            return None

    def should_self_wake(self, energy_full: bool) -> bool:
        """精力已回满 + 距上次唤醒超过最小间隔 → 可以自唤醒。"""
        if not self.cfg.enabled:
            return False
        if not energy_full:
            return False
        since = self.minutes_since_last_wake()
        if since is not None and since < self.cfg.min_interval:
            return False
        return True

    def build_wake_monologue(self) -> str:
        """自唤醒时注入的内心独白（第一人称，非指令）。"""
        return (
            "[Alive Reflection]\n"
            "我睡醒了...伸了个懒腰，感觉精力恢复得差不多了。\n"
            "新的一段时间开始了，我想想现在要做点什么...\n"
            "[End Alive Reflection]"
        )
