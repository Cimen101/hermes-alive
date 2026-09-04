"""Hermes Alive dashboard backend API."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

router = APIRouter()

_DB = None


def _get_db():
    global _DB
    if _DB is None:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from storage.db import AliveDB
        from hermes_constants import get_hermes_home
        # 真实数据目录名带 hash 后缀（agent-plugin-hermes-alive-<hash>），glob 定位
        import glob
        pattern = str(get_hermes_home() / "plugin-data" / "agent-plugin-hermes-alive-*" / "alive.db")
        matches = glob.glob(pattern)
        if matches:
            db_path = Path(matches[0])
        else:
            db_path = get_hermes_home() / "plugin-data" / "hermes-alive" / "alive.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _DB = AliveDB(db_path)
    return _DB


def _get_engine():
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from engine.coordinator import AliveEngine
    from engine.config import load_config

    db = _get_db()

    # 与 __init__.py 的 gs/ss 保持同一调用约定：(key, default, user_id)
    # 引擎管理器以 state_get(key, default) 两参形态调用，第二参必须是 default
    holder: dict = {}

    def gs(key, default=None, user_id=None):
        eng = holder.get("engine")
        uid = user_id or (eng._current_user_id if eng else "__global__")
        val = db.get_state(key, uid)
        return val if val is not None else default

    def ss(key, value, user_id=None):
        eng = holder.get("engine")
        uid = user_id or (eng._current_user_id if eng else "__global__")
        db.set_state(key, value, uid)

    eng = AliveConfigAdapter(gs, ss, db)
    holder["engine"] = eng
    return eng


class AliveConfigAdapter:
    """Minimal adapter for AliveEngine without full plugin context."""
    def __init__(self, gs, ss, db):
        from engine.coordinator import AliveEngine
        from engine.config import load_config
        self._gs = gs
        self._ss = ss
        self.db = db
        self.cfg = load_config(lambda k, d=None: d)
        self.clock = __import__('engine.clock', fromlist=['ClockManager']).ClockManager(self.cfg.clock, gs, ss)
        self.energy = __import__('engine.energy', fromlist=['EnergyManager']).EnergyManager(self.cfg.energy, gs, ss)
        self.stress = __import__('engine.stress', fromlist=['StressManager']).StressManager(self.cfg.stress, gs, ss)
        self.emotion = __import__('engine.emotion', fromlist=['EmotionEngine']).EmotionEngine(self.cfg.emotion, gs, ss)
        self.bond = __import__('engine.bond', fromlist=['BondManager']).BondManager(self.cfg.bond, gs, ss, db)
        self._current_user_id = "__global__"
        self._raw_state_get = gs
        self._raw_state_set = ss
        self._last_tick = 0

    def _state_get(self, key, default=None):
        return self._gs(key, default, self._current_user_id)

    def _state_set(self, key, value):
        self._ss(key, value, self._current_user_id)

    def get_state_summary(self):
        return {
            "clock_phase": self.clock.get_phase(),
            "energy": round(self.energy.get(), 1),
            "energy_label": self.energy.get_energy_label(),
            "stress": round(self.stress.get(), 1),
            "stress_mode": self.stress.get_mode(),
            "boredom": round(self._state_get("boredom", 30.0), 1),
            "pad_p": round(self.emotion.get_p(), 3),
            "pad_a": round(self.emotion.get_a(), 3),
            "pad_d": round(self.emotion.get_d(), 3),
            "emotion_label": self.emotion.get_emotion_label(),
            "bond_c": round(self.bond.get_c(), 3),
            "bond_d": round(self.bond.get_d(), 3),
            "bond_i": round(self.bond.get_i(), 3),
            "bond_t": round(self.bond.get_t(), 3),
            "trauma_active": self.bond.is_trauma_active(),
        }


@router.get("/status")
async def get_status(user_id: str = Query("__global__")):
    """Get current alive state for a user."""
    engine = _get_engine()
    engine._current_user_id = user_id
    return engine.get_state_summary()


@router.get("/history")
async def get_history(user_id: str = Query("__global__"), limit: int = Query(50)):
    """Get emotion history for a user."""
    db = _get_db()
    rows = db._get_conn().execute(
        "SELECT * FROM emotion_history WHERE user_id=? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/events")
async def get_events(user_id: str = Query("__global__"), limit: int = Query(50)):
    """Get event log for a user."""
    db = _get_db()
    rows = db._get_conn().execute(
        "SELECT * FROM event_log WHERE user_id=? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/interests")
async def get_interests(category: str = Query(None)):
    """Get interests list."""
    db = _get_db()
    return db.get_interests(category=category, user_id=None)  # 仪表盘全局视图


@router.get("/tasks")
async def get_tasks(status: str = Query("pending")):
    """Get tasks."""
    db = _get_db()
    return db.get_tasks(status=status)


@router.get("/config")
async def get_config():
    """Get current configuration (real values loaded via load_config, not bare defaults)."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from engine.config import AliveConfig, load_config

    try:
        from hermes_cli.config import load_config_readonly
        root = load_config_readonly() or {}
        entries = root.get("plugins", {}).get("entries", {}) if isinstance(root, dict) else {}
        entry = entries.get("hermes-alive", {}) if isinstance(entries, dict) else {}
        alive = (entry.get("settings", {}) or {}).get("alive", {}) if isinstance(entry, dict) else {}

        def getter(key, d=None):
            node = alive
            for seg in key.split("."):
                if not isinstance(node, dict) or seg not in node:
                    return d
                node = node[seg]
            return node

        cfg = load_config(getter)
    except Exception:
        cfg = AliveConfig()

    return {
        "clock": {
            "wake_time": cfg.clock.wake_time,
            "sleep_soft_time": cfg.clock.sleep_soft_time,
            "sleep_hard_time": cfg.clock.sleep_hard_time,
            "wind_down_start": cfg.clock.wind_down_start,
        },
        "energy": {
            "decay_rate": cfg.energy.decay_rate,
            "self_wake_threshold": cfg.energy.self_wake_threshold,
            "wrap_up_threshold": cfg.energy.wrap_up_threshold,
        },
        "stress": {
            "baseline_threshold": cfg.stress.baseline_threshold,
            "leisure_decision_threshold": cfg.stress.leisure_decision_threshold,
            "hard_leisure_threshold": cfg.stress.hard_leisure_threshold,
        },
        "monitor": {
            "step_interval": cfg.monitor.step_interval,
        },
    }


@router.get("/users")
async def get_users():
    """Get list of known user IDs."""
    db = _get_db()
    rows = db._get_conn().execute(
        "SELECT DISTINCT user_id FROM current_state WHERE user_id != '__global__'"
    ).fetchall()
    return [r["user_id"] for r in rows]


@router.post("/action/rest")
async def action_rest(user_id: str = Query("__global__")):
    """Trigger a rest action."""
    engine = _get_engine()
    engine._current_user_id = user_id
    current = engine.energy.get()
    recovered = engine.energy.recover(engine.cfg.energy.recovery_rest)
    engine.stress.apply_event("rest_taken", "moderate")
    engine.db.log_event("rest_taken", "web_ui", user_id)
    return {"message": "休息完成", "energy_before": round(current, 1), "energy_after": round(recovered, 1)}
