"""PAD emotion engine with extreme-value resistance and directional damping."""
from __future__ import annotations
import math
from .config import EmotionConfig
from .constants import match_emotion, get_pad_level


class EmotionEngine:
    def __init__(self, cfg: EmotionConfig, get_state, set_state):
        self.cfg = cfg
        self._get = get_state
        self._set = set_state

    def get_p(self) -> float:
        return self._get("pad_p", self.cfg.initial_p)

    def get_a(self) -> float:
        return self._get("pad_a", self.cfg.initial_a)

    def get_d(self) -> float:
        return self._get("pad_d", self.cfg.initial_d)

    def get_all(self) -> tuple[float, float, float]:
        return self.get_p(), self.get_a(), self.get_d()

    def set_all(self, p: float, a: float, d: float) -> None:
        self._set("pad_p", max(-1.0, min(1.0, p)))
        self._set("pad_a", max(-1.0, min(1.0, a)))
        self._set("pad_d", max(-1.0, min(1.0, d)))

    def _apply_resistance(self, current: float, delta: float) -> float:
        """Apply directional damping: harder to go positive, easier to fall negative."""
        abs_val = abs(current)
        if delta > 0:
            damping = 1.0 - abs_val ** 2
        else:
            damping = 1.0 - self.cfg.negative_damping_factor * abs_val ** 2
        return delta * damping

    def _clamp(self, val: float, floor: float = -1.0, ceiling: float = 1.0) -> float:
        return max(floor, min(ceiling, val))

    def apply_delta(self, p_delta: float, a_delta: float, d_delta: float) -> None:
        """Apply deltas with resistance, safety floor, and limits."""
        p, a, d = self.get_all()

        p_delta = self._apply_resistance(p, p_delta)
        a_delta = self._apply_resistance(a, a_delta)
        d_delta = self._apply_resistance(d, d_delta)

        p_delta = max(-self.cfg.max_single_change, min(self.cfg.max_single_change, p_delta))
        a_delta = max(-self.cfg.max_single_change, min(self.cfg.max_single_change, a_delta))
        d_delta = max(-self.cfg.max_single_change, min(self.cfg.max_single_change, d_delta))

        new_p = self._clamp(p + p_delta, floor=self.cfg.p_floor)
        new_a = self._clamp(a + a_delta)
        new_d = self._clamp(d + d_delta)

        self.set_all(new_p, new_a, new_d)

    def tick_decay(self) -> None:
        """Time decay toward initial values."""
        p, a, d = self.get_all()
        rate = self.cfg.decay_rate
        new_p = p + (self.cfg.initial_p - p) * rate
        new_a = a + (self.cfg.initial_a - a) * rate
        new_d = d + (self.cfg.initial_d - d) * rate
        self.set_all(new_p, new_a, new_d)

    def get_emotion_label(self) -> str:
        p, a, d = self.get_all()
        label, confidence = match_emotion(p, a, d)
        self._set("emotion_label", label)
        return label

    def get_injection_text(self) -> str:
        p, a, d = self.get_all()
        p_level, p_label = get_pad_level("p", p)
        a_level, a_label = get_pad_level("a", a)
        d_level, d_label = get_pad_level("d", d)
        emotion_label, confidence = match_emotion(p, a, d)

        lines = ["当前情绪维度："]
        lines.append(f"P(愉悦性): {p:.2f} → 档位{p_level}（{p_label}）")
        lines.append(f"A(激活度): {a:.2f} → 档位{a_level}（{a_label}）")
        lines.append(f"D(支配度): {d:.2f} → 档位{d_level}（{d_label}）")

        if confidence >= 0.6:
            lines.append(f"情绪标签：{emotion_label}")
        elif confidence >= 0.3:
            lines.append(f"情绪偏向：接近{emotion_label}，但不太确定")
        else:
            lines.append("情绪状态不明确，以数值为准")

        return "\n".join(lines)
