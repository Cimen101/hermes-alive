"""Hermes Alive dashboard backend API."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

_DB = None


def _conn_guard():
    """请求级连接兜底：响应结束后 rollback 本进程的 alive.db 连接。

    背景：gateway 主进程与 dashboard 进程共享同一 alive.db（WAL 单写者）。
    若 dashboard 某条路径的写事务未显式 commit，连接会 idle-in-transaction
    长期持有写锁，导致 gateway 的 scheduler 每 60s tick 抛 database is locked。
    请求结束后统一 rollback，保证任何漏 commit 都不会跨进程锁死数据库。"""
    yield
    try:
        if _DB is not None:
            _DB._get_conn().rollback()
    except Exception:
        pass


# 注意：router 必须在 _conn_guard 定义之后创建（Depends 引用前置名称）
router = APIRouter(dependencies=[Depends(_conn_guard)])


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
        # Dashboard 进程对 alive.db 只读：schema 由 gateway 进程负责；
        # ro 模式下任何意外写直接报错，不会形成跨进程写锁竞争。
        _DB = AliveDB(db_path, read_only=True)
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
        # Dashboard 进程只读：状态写一律丢弃（gateway 进程负责真实写入）。
        # 引擎管理器的计算类 _set（如 emotion_label）在此静默落空，读取路径
        # 不受影响；避免 dashboard 形成 WAL 写事务与 gateway 互锁。
        return

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
def get_status(user_id: str = Query("__global__")):
    """Get current alive state for a user."""
    engine = _get_engine()
    engine._current_user_id = user_id
    return engine.get_state_summary()


@router.get("/history")
def get_history(user_id: str = Query("__global__"), limit: int = Query(50)):
    """Get emotion history for a user."""
    db = _get_db()
    rows = db._get_conn().execute(
        "SELECT * FROM emotion_history WHERE user_id=? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/events")
def get_events(user_id: str = Query("__global__"), limit: int = Query(50)):
    """Get event log for a user."""
    db = _get_db()
    rows = db._get_conn().execute(
        "SELECT * FROM event_log WHERE user_id=? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/interests")
def get_interests(category: str = Query(None)):
    """Get interests list."""
    db = _get_db()
    return db.get_interests(category=category, user_id=None)  # 仪表盘全局视图


@router.get("/tasks")
def get_tasks(status: str = Query("pending")):
    """Get tasks."""
    db = _get_db()
    return db.get_tasks(status=status)


@router.get("/config")
def get_config():
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
def get_users():
    """Get list of known user IDs."""
    db = _get_db()
    rows = db._get_conn().execute(
        "SELECT DISTINCT user_id FROM current_state WHERE user_id != '__global__'"
    ).fetchall()
    return [r["user_id"] for r in rows]


@router.post("/action/rest")
def action_rest(user_id: str = Query("__global__")):
    """Trigger a rest action."""
    engine = _get_engine()
    engine._current_user_id = user_id
    current = engine.energy.get()
    recovered = engine.energy.recover(engine.cfg.energy.recovery_rest)
    engine.stress.apply_event("rest_taken", "moderate")
    engine.db.log_event("rest_taken", "web_ui", user_id)
    return {"message": "休息完成", "energy_before": round(current, 1), "energy_after": round(recovered, 1)}


# v2.4 §23 记忆面板：节点 / 条目 / 来源 / 检索（仪表盘接入）
def _get_memory_store():
    import sys
    if str(Path(__file__).parent.parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).parent.parent))
    from memory.store import MemoryStore
    from engine.config import load_config
    db = _get_db()
    cfg = load_config(lambda k, d=None: d)
    mc = cfg.memory
    mem_cfg = {
        "enabled": True,
        "min_confidence": mc.min_confidence,
        "inject_budget_tokens": mc.inject_budget_tokens,
        "embedding_provider": mc.embedding_provider,
        "embedding_model": mc.embedding_model,
        "embedding_api_key": mc.embedding_api_key,
        "embedding_base_url": mc.embedding_base_url,
    }
    if not hasattr(_get_memory_store, "_cache"):
        _get_memory_store._cache = MemoryStore(db, mem_cfg, light=True)
    return _get_memory_store._cache


@router.get("/memory/users")
def memory_users():
    db = _get_db()
    rows = db._get_conn().execute(
        "SELECT user_id, COUNT(*) c FROM mem_nodes "
        "WHERE user_id != '__global__' GROUP BY user_id ORDER BY c DESC"
    ).fetchall()
    return [{"user_id": r["user_id"], "node_count": r["c"]} for r in rows]


@router.get("/memory/nodes")
def memory_nodes(user_id: str = "__global__", limit: str = "50", ntype: str = ""):
    store = _get_memory_store()
    nodes = store.list_nodes(user_id=str(user_id), limit=max(1, min(500, int(limit or 50))))
    if ntype:
        nodes = [n for n in nodes if n.get("type") == ntype]
    out = []
    for n in nodes:
        out.append({
            "id": n.get("id"),
            "type": n.get("type"),
            "atom_type": n.get("atom_type"),
            "title": n.get("title"),
            "content": (n.get("content") or "")[:200],
            "importance": n.get("importance"),
            "salience": n.get("salience"),
            "occurred_at": n.get("occurred_at"),
            "source": n.get("source"),
            "status": n.get("status"),
        })
    return out


@router.get("/memory/entries")
def memory_entries(user_id: str = "__global__", limit: str = "20", status: str = ""):
    store = _get_memory_store()
    entries = store.list_entries(
        user_id=str(user_id), limit=max(1, min(200, int(limit or 20))),
        status=(status or None),
    )
    return [{
        "id": e.get("id"),
        "summary": e.get("summary"),
        "importance": e.get("importance"),
        "sentiment": e.get("sentiment"),
        "status": e.get("status"),
        "source": e.get("source"),
        "created_at": e.get("created_at"),
        "activation_count": e.get("activation_count"),
        "node_ids": [n.get("id") for n in store.get_entry_nodes(e["id"], str(user_id))],
    } for e in entries]


@router.get("/memory/entry")
def memory_entry(entry_id: str = "0", user_id: str = "__global__"):
    store = _get_memory_store()
    entries = [e for e in store.list_entries(str(user_id), limit=200)
               if int(e.get("id") or 0) == int(entry_id or 0)]
    if not entries:
        return JSONResponse(status_code=404, content={"error": "entry_not_found"})
    e = entries[0]
    return {
        "id": e["id"], "user_id": e["user_id"], "session_id": e.get("session_id"),
        "summary": e.get("summary"), "topics": e.get("topics") or [],
        "key_facts": e.get("key_facts") or [], "sentiment": e.get("sentiment"),
        "importance": e.get("importance"), "status": e.get("status"),
        "source": e.get("source"), "created_at": e.get("created_at"),
        "nodes": store.get_entry_nodes(e["id"], str(user_id)),
        "sources": store.get_sources(e["id"], str(user_id)),
    }


@router.get("/memory/sources")
def memory_sources(entry_id: str = "0", user_id: str = ""):
    store = _get_memory_store()
    srcs = store.get_sources(int(entry_id or 0), str(user_id) if user_id else None)
    return [{
        "role": s.get("role"),
        "content": s.get("content"),
        "created_at": s.get("created_at"),
    } for s in srcs]


@router.get("/memory/recall")
def memory_recall(user_id: str = "__global__", q: str = "", top_k: str = "5"):
    if not str(q).strip():
        return {"items": [], "entries": [], "block": "", "fused": []}
    store = _get_memory_store()
    return store.search_fused(str(q), str(user_id), top_k=max(1, min(20, int(top_k or 5))), reinforce=False, allow_wake=False)


# v2.4 §25 图谱与生命周期闭环
@router.get("/graph")
def memory_graph(user_id: str = "__global__", limit_nodes: str = "80", limit_edges: str = "120"):
    store = _get_memory_store()
    return {"enabled": True, "mode": "overview", "user_id": str(user_id),
            "snapshot": store.graph_snapshot(str(user_id), int(limit_nodes or 80), int(limit_edges or 120))}

@router.post("/graph/query")
def memory_graph_query(payload: dict):
    payload = payload or {}
    user_id = str(payload.get("user_id") or "__global__")
    store = _get_memory_store()
    q = str(payload.get("query") or "").strip()
    if q:
        result = store.search_fused(q, user_id, top_k=8, reinforce=False)
        ids = {str(x.get("id")) for x in result.get("fused", []) + result.get("items", [])}
        snap = store.graph_snapshot(user_id, 80, 120)
        snap["nodes"] = [n for n in snap["nodes"] if n.get("id") in ids or any(e.get("from_id") == n.get("id") or e.get("to_id") == n.get("id") for e in snap["edges"])]
        return {"enabled": True, "mode": "query", "query": q, "retrieval": result, "snapshot": snap}
    return {"enabled": True, "mode": "overview", "snapshot": store.graph_snapshot(user_id, 80, 120)}

@router.post("/memory/revise")
def memory_revise(payload: dict):
    # R-H/25：只读进程下写记忆会抛错（readonly database）——如实拒绝
    payload = payload or {}
    store = _get_memory_store()
    try:
        node = store.revise_node(payload.get("node_id"), str(payload.get("user_id") or "__global__"), payload.get("title"), payload.get("content"), payload.get("occurred_at"), payload.get("importance"))
    except Exception as e:
        return {"ok": False, "error": f"只读进程不可修改记忆: {str(e)[:80]}"}
    return {"ok": bool(node), "node": node}

@router.post("/memory/purge")
def memory_purge(payload: dict):
    payload = payload or {}
    store = _get_memory_store()
    try:
        count = store.purge_nodes(str(payload.get("user_id") or "__global__"), payload.get("node_ids"), payload.get("older_than_days"))
    except Exception as e:
        return {"ok": False, "error": f"只读进程不可清除记忆: {str(e)[:80]}"}
    return {"ok": True, "purged": count}

@router.post("/memory/consolidate")
def memory_consolidate(payload: dict):
    payload = payload or {}
    store = _get_memory_store()
    try:
        result = store.consolidate_entries(str(payload.get("user_id") or "__global__"), payload.get("entry_ids"))
    except Exception as e:
        return {"ok": False, "error": f"只读进程不可合并条目: {str(e)[:80]}"}
    return {"ok": bool(result), "result": result}
