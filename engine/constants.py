"""Constants — constraint parameters and emotion prototypes. No fixed event tables."""

from __future__ import annotations
import math

# ── Emotion prototype PAD coordinates (56 prototypes, research-based) ──

EMOTION_PROTOTYPES: list[dict] = [
    # 8 basic emotions × 3 intensities (Plutchik 1980 + Russell & Mehrabian 1977)
    {"name": "joy_mild", "label": "愉悦", "p": 0.45, "a": 0.25, "d": 0.20},
    {"name": "joy_medium", "label": "快乐", "p": 0.80, "a": 0.50, "d": 0.30},
    {"name": "joy_strong", "label": "狂喜", "p": 0.95, "a": 0.70, "d": 0.50},
    {"name": "sadness_mild", "label": "忧郁", "p": -0.40, "a": -0.20, "d": -0.30},
    {"name": "sadness_medium", "label": "悲伤", "p": -0.60, "a": -0.40, "d": -0.50},
    {"name": "sadness_strong", "label": "悲痛", "p": -0.80, "a": -0.50, "d": -0.70},
    {"name": "anger_mild", "label": "烦恼", "p": -0.30, "a": 0.40, "d": 0.30},
    {"name": "anger_medium", "label": "生气", "p": -0.50, "a": 0.60, "d": 0.50},
    {"name": "anger_strong", "label": "暴怒", "p": -0.70, "a": 0.80, "d": 0.70},
    {"name": "fear_mild", "label": "不安", "p": -0.40, "a": 0.30, "d": -0.30},
    {"name": "fear_medium", "label": "恐惧", "p": -0.60, "a": 0.50, "d": -0.50},
    {"name": "fear_strong", "label": "惊恐", "p": -0.80, "a": 0.70, "d": -0.70},
    {"name": "surprise_mild", "label": "好奇", "p": 0.10, "a": 0.40, "d": -0.10},
    {"name": "surprise_medium", "label": "惊讶", "p": 0.20, "a": 0.60, "d": -0.20},
    {"name": "surprise_strong", "label": "震惊", "p": 0.30, "a": 0.80, "d": -0.30},
    {"name": "disgust_mild", "label": "厌烦", "p": -0.35, "a": 0.30, "d": 0.10},
    {"name": "disgust_medium", "label": "厌恶", "p": -0.60, "a": 0.45, "d": 0.10},
    {"name": "disgust_strong", "label": "憎恶", "p": -0.80, "a": 0.55, "d": 0.20},
    {"name": "trust_mild", "label": "接受", "p": 0.30, "a": -0.10, "d": 0.20},
    {"name": "trust_medium", "label": "信任", "p": 0.50, "a": -0.20, "d": 0.30},
    {"name": "trust_strong", "label": "信赖", "p": 0.70, "a": -0.10, "d": 0.40},
    {"name": "anticipation_mild", "label": "关注", "p": 0.20, "a": 0.30, "d": 0.20},
    {"name": "anticipation_medium", "label": "期待", "p": 0.30, "a": 0.50, "d": 0.30},
    {"name": "anticipation_strong", "label": "渴望", "p": 0.40, "a": 0.70, "d": 0.40},
    # Mehrabian 8 PAD combinations (1996)
    {"name": "exuberant", "label": "热情洋溢", "p": 0.60, "a": 0.50, "d": 0.50},
    {"name": "bored", "label": "无聊", "p": -0.30, "a": -0.40, "d": -0.20},
    {"name": "dependent", "label": "依赖", "p": 0.40, "a": 0.30, "d": -0.40},
    {"name": "disdainful", "label": "轻蔑", "p": -0.40, "a": -0.30, "d": 0.40},
    {"name": "relaxed", "label": "放松", "p": 0.50, "a": -0.40, "d": 0.30},
    {"name": "anxious", "label": "焦虑", "p": -0.40, "a": 0.50, "d": -0.40},
    {"name": "docile", "label": "温顺", "p": 0.30, "a": -0.30, "d": -0.30},
    {"name": "hostile", "label": "敌意", "p": -0.50, "a": 0.50, "d": 0.30},
    # Plutchik dyads
    {"name": "love", "label": "爱慕", "p": 0.70, "a": 0.10, "d": 0.20},
    {"name": "optimism", "label": "乐观", "p": 0.50, "a": 0.45, "d": 0.30},
    {"name": "awe", "label": "敬畏", "p": 0.10, "a": 0.65, "d": -0.40},
    {"name": "submission", "label": "顺从", "p": 0.10, "a": -0.30, "d": -0.45},
    {"name": "disapproval", "label": "不满", "p": -0.35, "a": 0.15, "d": -0.10},
    {"name": "remorse", "label": "懊悔", "p": -0.55, "a": -0.20, "d": -0.45},
    {"name": "contempt", "label": "蔑视", "p": -0.40, "a": 0.15, "d": 0.40},
    {"name": "aggressiveness", "label": "咄咄逼人", "p": -0.20, "a": 0.55, "d": 0.55},
    # Complex emotions
    {"name": "shame", "label": "羞耻", "p": -0.50, "a": -0.10, "d": -0.65},
    {"name": "guilt", "label": "内疚", "p": -0.45, "a": 0.15, "d": -0.50},
    {"name": "pride", "label": "自豪", "p": 0.65, "a": 0.35, "d": 0.65},
    {"name": "envy", "label": "嫉妒", "p": -0.35, "a": 0.25, "d": -0.30},
    {"name": "gratitude", "label": "感激", "p": 0.55, "a": 0.10, "d": 0.10},
    {"name": "compassion", "label": "同情", "p": 0.35, "a": 0.10, "d": -0.15},
    {"name": "nostalgia", "label": "怀旧", "p": 0.25, "a": -0.20, "d": -0.10},
    {"name": "amusement", "label": "好笑", "p": 0.65, "a": 0.45, "d": 0.20},
    {"name": "contentment", "label": "满足", "p": 0.55, "a": -0.30, "d": 0.25},
    {"name": "interest", "label": "兴趣", "p": 0.35, "a": 0.35, "d": 0.25},
    {"name": "confusion", "label": "困惑", "p": -0.10, "a": 0.25, "d": -0.40},
    {"name": "boredom", "label": "无聊感", "p": -0.25, "a": -0.45, "d": -0.15},
    {"name": "gentleness", "label": "温柔", "p": 0.40, "a": -0.80, "d": 0.10},
    {"name": "resentment", "label": "怨恨", "p": -0.50, "a": 0.28, "d": 0.15},
    {"name": "impressed", "label": "印象深刻", "p": 0.50, "a": 0.30, "d": -0.20},
    {"name": "determination", "label": "坚定", "p": 0.30, "a": 0.50, "d": 0.60},
]

# ── Constraint parameters (all configurable via config.yaml) ──

CONSTRAINTS = {
    # Single-change caps
    "pad_max_single": 0.10,
    "bond_max_single": 0.05,
    # Daily limits
    "pad_daily_limit": 0.30,
    "bond_daily_limit": 0.15,
    # Safety floors
    "p_floor": -0.7,
    "p_restore_threshold": -0.3,
    # Resistance
    "negative_damping_factor": 0.5,
    # Trauma
    "trauma_threshold": 0.2,
    "trauma_window_days": 7,
    "trauma_positive_penalty": 0.5,
    # Relationship maturity
    "new_relationship_days": 7,
    "mature_relationship_days": 30,
    "new_rel_multiplier": 1.5,
    "mature_rel_multiplier": 0.7,
    # Confidence
    "min_confidence": 0.6,
    "high_confidence": 0.8,
    # Drift detection
    "drift_check_interval": 100,
    "drift_positive_threshold": 0.8,
    "drift_correction_amount": 0.05,
}


# ── PAD level labels (20 levels per dimension) ──

PAD_LEVELS = {
    "p": [
        (-1.0, -0.9, "极度不悦"), (-0.9, -0.8, "非常不悦"), (-0.8, -0.7, "很不悦"),
        (-0.7, -0.6, "较不悦"), (-0.6, -0.5, "偏不悦"), (-0.5, -0.4, "略不悦"),
        (-0.4, -0.3, "轻微不悦"), (-0.3, -0.2, "接近中性偏下"), (-0.2, -0.1, "略偏不悦"),
        (-0.1, 0.0, "几乎中性偏下"), (0.0, 0.1, "几乎中性偏上"), (0.1, 0.2, "略偏愉悦"),
        (0.2, 0.3, "接近中性偏上"), (0.3, 0.4, "轻微愉悦"), (0.4, 0.5, "略愉悦"),
        (0.5, 0.6, "偏愉悦"), (0.6, 0.7, "较愉悦"), (0.7, 0.8, "很愉悦"),
        (0.8, 0.9, "非常愉悦"), (0.9, 1.0, "极度愉悦"),
    ],
    "a": [
        (-1.0, -0.9, "极度平静"), (-0.9, -0.8, "非常平静"), (-0.8, -0.7, "很平静"),
        (-0.7, -0.6, "较平静"), (-0.6, -0.5, "偏平静"), (-0.5, -0.4, "略平静"),
        (-0.4, -0.3, "轻微平静"), (-0.3, -0.2, "接近中性偏下"), (-0.2, -0.1, "略偏平静"),
        (-0.1, 0.0, "几乎中性偏下"), (0.0, 0.1, "几乎中性偏上"), (0.1, 0.2, "略偏激动"),
        (0.2, 0.3, "接近中性偏上"), (0.3, 0.4, "轻微激动"), (0.4, 0.5, "略激动"),
        (0.5, 0.6, "偏激动"), (0.6, 0.7, "较激动"), (0.7, 0.8, "很激动"),
        (0.8, 0.9, "非常激动"), (0.9, 1.0, "极度激动"),
    ],
    "d": [
        (-1.0, -0.9, "极度被支配"), (-0.9, -0.8, "非常被支配"), (-0.8, -0.7, "很被支配"),
        (-0.7, -0.6, "较被支配"), (-0.6, -0.5, "偏被支配"), (-0.5, -0.4, "略被支配"),
        (-0.4, -0.3, "轻微被支配"), (-0.3, -0.2, "接近中性偏下"), (-0.2, -0.1, "略偏被支配"),
        (-0.1, 0.0, "几乎中性偏下"), (0.0, 0.1, "几乎中性偏上"), (0.1, 0.2, "略偏支配"),
        (0.2, 0.3, "接近中性偏上"), (0.3, 0.4, "轻微支配"), (0.4, 0.5, "略支配"),
        (0.5, 0.6, "偏支配"), (0.6, 0.7, "较支配"), (0.7, 0.8, "很支配"),
        (0.8, 0.9, "非常支配"), (0.9, 1.0, "极度支配"),
    ],
}

# ── Bond level labels (20 levels per dimension, design doc 04 §2.2) ──

BOND_LEVELS = {
    "c": [
        (-1.0, -0.9, "极度疏远"), (-0.9, -0.8, "非常疏远"), (-0.8, -0.7, "很疏远"),
        (-0.7, -0.6, "较疏远"), (-0.6, -0.5, "偏疏远"), (-0.5, -0.4, "略疏远"),
        (-0.4, -0.3, "轻微疏远"), (-0.3, -0.2, "接近中性偏下"), (-0.2, -0.1, "略偏疏远"),
        (-0.1, 0.0, "几乎中性偏下"), (0.0, 0.1, "几乎中性偏上"), (0.1, 0.2, "略偏亲近"),
        (0.2, 0.3, "接近中性偏上"), (0.3, 0.4, "轻微亲近"), (0.4, 0.5, "略亲近"),
        (0.5, 0.6, "偏亲近"), (0.6, 0.7, "较亲近"), (0.7, 0.8, "很亲近"),
        (0.8, 0.9, "非常亲近"), (0.9, 1.0, "极度亲近"),
    ],
    "d_rel": [
        (-1.0, -0.9, "极度独立"), (-0.9, -0.8, "非常独立"), (-0.8, -0.7, "很独立"),
        (-0.7, -0.6, "较独立"), (-0.6, -0.5, "偏独立"), (-0.5, -0.4, "略独立"),
        (-0.4, -0.3, "轻微独立"), (-0.3, -0.2, "接近中性偏下"), (-0.2, -0.1, "略偏独立"),
        (-0.1, 0.0, "几乎中性偏下"), (0.0, 0.1, "几乎中性偏上"), (0.1, 0.2, "略偏依赖"),
        (0.2, 0.3, "接近中性偏上"), (0.3, 0.4, "轻微依赖"), (0.4, 0.5, "略依赖"),
        (0.5, 0.6, "偏依赖"), (0.6, 0.7, "较依赖"), (0.7, 0.8, "很依赖"),
        (0.8, 0.9, "非常依赖"), (0.9, 1.0, "极度依赖"),
    ],
    "i": [
        (-1.0, -0.9, "极度不在意"), (-0.9, -0.8, "非常不在意"), (-0.8, -0.7, "很不在意"),
        (-0.7, -0.6, "较不在意"), (-0.6, -0.5, "偏不在意"), (-0.5, -0.4, "略不在意"),
        (-0.4, -0.3, "轻微不在意"), (-0.3, -0.2, "接近中性偏下"), (-0.2, -0.1, "略偏不在意"),
        (-0.1, 0.0, "几乎中性偏下"), (0.0, 0.1, "几乎中性偏上"), (0.1, 0.2, "略偏在意"),
        (0.2, 0.3, "接近中性偏上"), (0.3, 0.4, "轻微在意"), (0.4, 0.5, "略在意"),
        (0.5, 0.6, "偏在意"), (0.6, 0.7, "较在意"), (0.7, 0.8, "很在意"),
        (0.8, 0.9, "非常在意"), (0.9, 1.0, "极度在意"),
    ],
    "t": [
        (-1.0, -0.9, "极度不信任"), (-0.9, -0.8, "非常不信任"), (-0.8, -0.7, "很不信任"),
        (-0.7, -0.6, "较不信任"), (-0.6, -0.5, "偏不信任"), (-0.5, -0.4, "略不信任"),
        (-0.4, -0.3, "轻微不信任"), (-0.3, -0.2, "接近中性偏下"), (-0.2, -0.1, "略偏不信任"),
        (-0.1, 0.0, "几乎中性偏下"), (0.0, 0.1, "几乎中性偏上"), (0.1, 0.2, "略偏信任"),
        (0.2, 0.3, "接近中性偏上"), (0.3, 0.4, "轻微信任"), (0.4, 0.5, "略信任"),
        (0.5, 0.6, "偏信任"), (0.6, 0.7, "较信任"), (0.7, 0.8, "很信任"),
        (0.8, 0.9, "非常信任"), (0.9, 1.0, "极度信任"),
    ],
}


def get_bond_level(dimension: str, value: float) -> tuple[int, str]:
    """Return (level_number, label) for a bond dimension value."""
    levels = BOND_LEVELS.get(dimension)
    if not levels:
        return 10, "中性"
    for i, (lo, hi, label) in enumerate(levels):
        if lo <= value < hi or (i == len(levels) - 1 and value == hi):
            return i + 1, label
    return 10, "中性"


def get_pad_level(dimension: str, value: float) -> tuple[int, str]:
    """Return (level_number, label) for a PAD dimension value."""
    levels = PAD_LEVELS.get(dimension, PAD_LEVELS["p"])
    for i, (lo, hi, label) in enumerate(levels):
        if lo <= value < hi or (i == len(levels) - 1 and value == hi):
            return i + 1, label
    return 10, "中性"


def match_emotion(p: float, a: float, d: float) -> tuple[str, float]:
    """Find the nearest emotion prototype. Returns (label, confidence)."""
    best_label = "中性"
    best_dist = float("inf")
    for proto in EMOTION_PROTOTYPES:
        dist = math.sqrt(
            (p - proto["p"]) ** 2 + (a - proto["a"]) ** 2 + (d - proto["d"]) ** 2
        )
        if dist < best_dist:
            best_dist = dist
            best_label = proto["label"]
    confidence = max(0.0, 1.0 - best_dist / 3.464)
    return best_label, confidence


def apply_constraints(pad_changes: dict, bond_changes: dict, current_state: dict) -> tuple[dict, dict]:
    """Apply all safety constraints to LLM-suggested changes. Returns validated changes."""
    c = CONSTRAINTS

    # 1. Confidence check
    confidence = current_state.get("confidence", 1.0)
    if confidence < c["min_confidence"]:
        return {}, {}

    # 2. Clamp single changes
    for key in ("p", "a", "d"):
        val = pad_changes.get(key, 0.0)
        pad_changes[key] = max(-c["pad_max_single"], min(c["pad_max_single"], val))

    for key in ("c", "d_rel", "i", "t"):
        val = bond_changes.get(key, 0.0)
        bond_changes[key] = max(-c["bond_max_single"], min(c["bond_max_single"], val))

    # 3. Directional resistance
    for key in ("p", "a", "d"):
        current = current_state.get(f"pad_{key}", 0.0)
        delta = pad_changes[key]
        abs_val = abs(current)
        if delta > 0:
            damping = 1.0 - abs_val ** 2
        else:
            damping = 1.0 - c["negative_damping_factor"] * abs_val ** 2
        pad_changes[key] = delta * damping

    for key, state_key in [("c", "bond_c"), ("d_rel", "bond_d"), ("i", "bond_i"), ("t", "bond_t")]:
        current = current_state.get(state_key, 0.0)
        delta = bond_changes[key]
        abs_val = abs(current)
        if delta > 0:
            damping = 1.0 - abs_val ** 2
        else:
            damping = 1.0 - c["negative_damping_factor"] * abs_val ** 2
        bond_changes[key] = delta * damping

    # 4. P safety floor
    new_p = current_state.get("pad_p", 0.3) + pad_changes.get("p", 0.0)
    if new_p < c["p_floor"]:
        pad_changes["p"] = c["p_floor"] - current_state.get("pad_p", 0.3)

    # 4.5 Restore force: when P below restore threshold, amplify recovery,
    #     damp further decline (blocks the death spiral, design doc 09)
    if current_state.get("pad_p", 0.3) < c["p_restore_threshold"]:
        p_delta = pad_changes.get("p", 0.0)
        if p_delta > 0:
            pad_changes["p"] = p_delta * 1.5
        elif p_delta < 0:
            pad_changes["p"] = p_delta * 0.5

    # 5. Trauma window (T positive penalty)
    if current_state.get("trauma_active", False):
        bond_changes["t"] = bond_changes.get("t", 0.0) * c["trauma_positive_penalty"]

    # 6. Relationship maturity multiplier
    maturity = current_state.get("relationship_maturity", 1.0)
    for key in bond_changes:
        bond_changes[key] *= maturity

    # 7. Re-clamp after all modifications
    for key in ("p", "a", "d"):
        pad_changes[key] = max(-c["pad_max_single"], min(c["pad_max_single"], pad_changes[key]))
    for key in ("c", "d_rel", "i", "t"):
        bond_changes[key] = max(-c["bond_max_single"], min(c["bond_max_single"], bond_changes[key]))

    return pad_changes, bond_changes