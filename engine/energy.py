"""Energy system — time-based decay, rest recovery, user-interaction recovery.

职责边界（设计11）：精力系统只负责控制自唤醒时间和连续工作时间，
不参与工作/休闲决策（那是压力系统的职责）。
"""
from __future__ import annotations
from .config import EnergyConfig


class EnergyManager:
    def __init__(self, cfg: EnergyConfig, get_state, set_state):
        self.cfg = cfg
        self._get = get_state
        self._set = set_state

    def get(self) -> float:
        try:
            return float(self._get("energy", self.cfg.initial))
        except (TypeError, ValueError):
            # 历史脏数据（如 web_ui 写入字符串）不致拖垮整个调度tick
            return float(self.cfg.initial)

    def set(self, val: float) -> None:
        self._set("energy", max(0.0, min(self.cfg.max_value, val)))

    def tick(self, mode: str = "working", phase_multiplier: float = 1.0) -> float:
        """Decay energy each minute based on activity mode and clock phase.

        精力只随时间衰减，不参与决策：
        - working: decay_rate（工作消耗快）
        - leisure: decay_leisure（休闲消耗慢）
        - phase_multiplier: 时钟相位倍率（WINDING_DOWN×1.5 / WARMING_UP×0.5 / SLEEPING×0）
        """
        current = self.get()
        if mode == "leisure":
            drain = self.cfg.decay_leisure
        else:
            drain = self.cfg.decay_rate
        new_val = max(0.0, current - drain * phase_multiplier)
        self.set(new_val)
        return new_val

    def recover_rest(self, minutes: float = 1.0) -> float:
        """休息时精力恢复（每分钟 recovery_rest_rate）。"""
        current = self.get()
        new_val = min(self.cfg.max_value, current + self.cfg.recovery_rest_rate * minutes)
        self.set(new_val)
        return new_val

    def recover(self, amount: float, ceiling: float | None = None) -> float:
        """Recover energy (from user interactions). Ceiling is a cap, not a pull-back.

        R13/G2：原 min(cap, cur+amount) 在 cur>cap 时反而把精力拽低
        （睡饱100→用户来一句话→跌回75）。设计01 §5.2 上限=不再向上恢复。"""
        current = self.get()
        cap = ceiling if ceiling is not None else self.cfg.max_value
        if current >= cap:
            return current
        new_val = min(cap, current + amount)
        self.set(new_val)
        return new_val

    # ── 用户互动恢复（设计01恢复来源表）──

    def recover_chat(self) -> float:
        """聊天互动恢复（每条消息，上限75）。"""
        return self.recover(self.cfg.recovery_chat, self.cfg.recovery_chat_ceiling)

    def recover_praise(self) -> float:
        return self.recover(self.cfg.recovery_praise, self.cfg.recovery_praise_ceiling)

    def recover_task_done(self) -> float:
        return self.recover(self.cfg.recovery_task_done, self.cfg.recovery_task_ceiling)

    def recover_encourage(self) -> float:
        return self.recover(self.cfg.recovery_encourage, self.cfg.recovery_encourage_ceiling)

    def is_depleted(self) -> bool:
        return self.get() <= 0.0

    def should_wrap_up(self) -> bool:
        return self.get() <= self.cfg.wrap_up_threshold

    def can_self_wake(self) -> bool:
        return self.get() >= self.cfg.self_wake_threshold

    def can_continue_working(self) -> bool:
        return self.get() > self.cfg.self_wake_resume

    def get_energy_label(self) -> str:
        e = self.get()
        if e >= 80: return "精力充沛"
        if e >= 60: return "状态良好"
        if e >= 40: return "有些疲惫"
        if e >= 20: return "很累"
        if e > 0: return "极度疲劳"
        return "耗尽"
