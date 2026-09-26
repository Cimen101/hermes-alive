"""Long-term bond system (C/D_rel/I/T) with asymmetry and trauma window."""
from __future__ import annotations
from datetime import datetime, timedelta
from .config import BondConfig


class BondManager:
    def __init__(self, cfg: BondConfig, get_state, set_state, db):
        self.cfg = cfg
        self._get = get_state
        self._set = set_state
        self._db = db

    def get_c(self) -> float:
        return self._get("bond_closeness", self.cfg.initial_c)

    def get_d(self) -> float:
        return self._get("bond_dependence", self.cfg.initial_d)

    def get_i(self) -> float:
        return self._get("bond_interest", self.cfg.initial_i)

    def get_t(self) -> float:
        return self._get("bond_trust", self.cfg.initial_t)

    def get_all(self) -> dict:
        return {"c": self.get_c(), "d_rel": self.get_d(), "i": self.get_i(), "t": self.get_t()}

    def _set_val(self, key: str, val: float) -> None:
        self._set(key, max(-1.0, min(1.0, val)))

    def _apply_resistance(self, current: float, delta: float) -> float:
        abs_val = abs(current)
        if delta > 0:
            damping = 1.0 - abs_val ** 2
        else:
            damping = 1.0 - 0.5 * abs_val ** 2
        return delta * damping

    def apply_deltas(self, c: float = 0, d_rel: float = 0, i: float = 0, t: float = 0) -> None:
        """Apply deltas with resistance."""
        self._set_val("bond_closeness", self.get_c() + self._apply_resistance(self.get_c(), c))
        self._set_val("bond_dependence", self.get_d() + self._apply_resistance(self.get_d(), d_rel))
        self._set_val("bond_interest", self.get_i() + self._apply_resistance(self.get_i(), i))
        self._set_val("bond_trust", self.get_t() + self._apply_resistance(self.get_t(), t))

    def tick_decay(self) -> None:
        """Time decay toward initial values."""
        rate = self.cfg.decay_rate
        self._set_val("bond_closeness", self.get_c() + (self.cfg.initial_c - self.get_c()) * rate)
        self._set_val("bond_dependence", self.get_d() + (self.cfg.initial_d - self.get_d()) * rate)
        self._set_val("bond_interest", self.get_i() + (self.cfg.initial_i - self.get_i()) * rate)
        self._set_val("bond_trust", self.get_t() + (self.cfg.initial_t - self.get_t()) * rate)

    def is_trauma_active(self) -> bool:
        row = self._get("trauma_active", 0)
        if not row:
            return False
        started = self._get("trauma_started_at", "")
        if not started:
            return False
        try:
            start_dt = datetime.fromisoformat(started)
            return datetime.now() - start_dt < timedelta(days=self.cfg.trauma_window_days)
        except (ValueError, TypeError):
            return False

    def trigger_trauma(self) -> None:
        self._set("trauma_active", 1)
        self._set("trauma_started_at", datetime.now().isoformat())

    def clear_trauma(self) -> None:
        """解除创伤（全量）。R-H/44：原 fraction 参数为死代码（<1.0 空操作），
        「部分修复清除」从未实现——修复统一走 repair_count 累计（见
        get_repair_count/bump_repair，达 trauma_clear_per_positive_count 即解除）。"""
        if not self.is_trauma_active():
            return
        self._set("trauma_active", 0)
        self._set("trauma_started_at", "")
        self._set("trauma_repair_count", 0)

    def get_repair_count(self) -> int:
        """R-H/44：创伤修复累计——创伤期内每次成功的正向信任修复 +1。"""
        try:
            return int(self._get("trauma_repair_count", 0) or 0)
        except (TypeError, ValueError):
            return 0

    def bump_repair(self) -> int:
        n = self.get_repair_count() + 1
        self._set("trauma_repair_count", n)
        return n

    def get_trauma_multiplier(self) -> float:
        if not self.is_trauma_active():
            return 1.0
        return self.cfg.trauma_positive_penalty

    def get_relationship_maturity_multiplier(self) -> float:
        created = self._get("bond_created_at", "")
        if not created:
            self._set("bond_created_at", datetime.now().isoformat())
            return 1.5
        try:
            days = (datetime.now() - datetime.fromisoformat(created)).days
            if days < 7:
                return 1.5
            if days < self.cfg.relationship_maturity_days:
                return 1.0
            return 0.7
        except (ValueError, TypeError):
            return 1.0

    def get_injection_text(self) -> str:
        c, d, i, t = self.get_c(), self.get_d(), self.get_i(), self.get_t()
        lines = ["情感状态："]

        # R12/D2：原四行复用 get_pad_level("p")——亲密度/依赖度/在意度/信任度
        # 全被贴成"愉悦度"标签。constants 的 BOND_LEVELS/get_bond_level 早已
        # 按 01b 设计定表（D 维键名 d_rel），此处按设计接线。
        from .constants import get_bond_level
        c_lvl, c_lbl = get_bond_level("c", c)
        d_lvl, d_lbl = get_bond_level("d_rel", d)
        i_lvl, i_lbl = get_bond_level("i", i)
        t_lvl, t_lbl = get_bond_level("t", t)

        lines.append(f"C(亲密度): {c:.2f} → 档位{c_lvl}（{c_lbl}）")
        lines.append(f"D(依赖度): {d:.2f} → 档位{d_lvl}（{d_lbl}）")
        lines.append(f"I(在意度): {i:.2f} → 档位{i_lvl}（{i_lbl}）")
        lines.append(f"T(信任度): {t:.2f} → 档位{t_lvl}（{t_lbl}）")

        return "\n".join(lines)
