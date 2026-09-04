"""Boredom engine — rises during long rest/leisure, falls on new things.

设计03-兴趣好奇心热度：无聊度驱动好奇心探索倾向。
"""
from __future__ import annotations
from .config import BoredomConfig


class BoredomManager:
    def __init__(self, cfg: BoredomConfig, get_state, set_state):
        self.cfg = cfg
        self._get = get_state
        self._set = set_state

    def get(self) -> float:
        val = self._get("boredom", self.cfg.initial)
        try:
            return float(val) if val is not None else self.cfg.initial
        except (TypeError, ValueError):
            return self.cfg.initial

    def set(self, val: float) -> None:
        self._set("boredom", max(0.0, min(self.cfg.max_value, val)))

    def tick_resting(self, minutes: float = 1.0) -> None:
        """休息/休闲时无聊度缓慢上升。"""
        if minutes <= 0:
            return
        self.set(self.get() + self.cfg.increase_long_rest * minutes)

    def tick_waking(self, minutes: float = 1.0) -> None:
        """R12/D5（设计14 §3.2）：清醒休闲=低挑战代理，无聊度温和上升；
        速率慢于小憩（increase_waking_leisure < increase_long_rest）。"""
        if minutes <= 0:
            return
        self.set(self.get() + self.cfg.increase_waking_leisure * minutes)

    def on_new_thing(self) -> None:
        """遇到新事物/做了喜欢的事，无聊度下降。"""
        self.set(self.get() - self.cfg.decrease_new_thing)

    def get_level(self) -> str:
        b = self.get()
        if b >= self.cfg.high_threshold:
            return "high"
        if b >= self.cfg.medium_threshold:
            return "medium"
        if b >= self.cfg.low_threshold:
            return "low"
        return "minimal"
