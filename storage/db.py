"""SQLite storage layer — multi-user isolated, single source of truth."""

import sqlite3
import threading
from pathlib import Path
from typing import Any

_DEFAULT_USER = "__global__"


class AliveDB:
    """Thread-safe SQLite wrapper with per-user state isolation."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._event_keep = 5000      # event_log 保留上限，约束长期增长
        self._event_insert_count = 0
        self._init_schema()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(
                str(self._db_path), check_same_thread=False, timeout=10,
            )
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return self._local.conn

    def _init_schema(self) -> None:
        self._get_conn().executescript(_SCHEMA)
        # 增量迁移：老库补建新表（CREATE IF NOT EXISTS 幂等）
        self._get_conn().executescript(_OUTREACH_MIGRATE)
        # 老库 tasks 表补 user_id 列（todo 镜像按用户轨道隔离）
        try:
            self._get_conn().execute(
                "ALTER TABLE tasks ADD COLUMN user_id TEXT NOT NULL DEFAULT '__global__'")
        except sqlite3.OperationalError:
            pass  # 列已存在
        # #G5a：interests 表补 user_id 列（多用户兴趣隔离）
        try:
            self._get_conn().execute(
                "ALTER TABLE interests ADD COLUMN user_id TEXT NOT NULL DEFAULT '__global__'")
        except sqlite3.OperationalError:
            pass  # 列已存在
        self._get_conn().commit()

    # ── Per-user state ──

    def get_state(self, key: str, user_id: str = _DEFAULT_USER, default: Any = None) -> Any:
        row = self._get_conn().execute(
            "SELECT value FROM current_state WHERE key=? AND user_id=?", (key, user_id)
        ).fetchone()
        return row["value"] if row else default

    def set_state(self, key: str, value: Any, user_id: str = _DEFAULT_USER) -> None:
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO current_state(key,user_id,value,updated_at) "
            "VALUES(?,?,?,datetime('now'))",
            (key, user_id, value),
        )
        conn.commit()

    def get_all_state(self, user_id: str = _DEFAULT_USER) -> dict[str, Any]:
        rows = self._get_conn().execute(
            "SELECT key,value FROM current_state WHERE user_id=?", (user_id,)
        ).fetchall()
        return {r["key"]: r["value"] for r in rows}

    # ── Interests (per-user isolated via user_id) ──

    def get_interests(self, category: str | None = None, active_only: bool = True,
                      user_id: str = _DEFAULT_USER) -> list[dict]:
        # #G5a：不传 user_id 时（dashboard 全局视图）默认 __global__ 口径；
        # 传 None 表示查全部用户（跨用户汇总视图）。
        q = "SELECT * FROM interests"
        conds, params = [], []
        if user_id is not None:
            conds.append("user_id=?")
            params.append(user_id)
        if category:
            conds.append("category=?")
            params.append(category)
        if active_only:
            conds.append("is_eliminated=0")
        if conds:
            q += " WHERE " + " AND ".join(conds)
        return [dict(r) for r in self._get_conn().execute(q + " ORDER BY heat DESC", params).fetchall()]

    def upsert_interest(self, data: dict) -> None:
        # #G5a：确保写入带 user_id（调用方必须提供，否则落到 __global__）
        if "user_id" not in data:
            data = {**data, "user_id": _DEFAULT_USER}
        cols = list(data.keys())
        ph = ",".join(["?"] * len(cols))
        upd = ",".join([f"{c}=excluded.{c}" for c in cols if c != "id"])
        self._get_conn().execute(
            f"INSERT INTO interests({','.join(cols)}) VALUES({ph}) ON CONFLICT(id) DO UPDATE SET {upd}",
            [data[c] for c in cols],
        )
        self._get_conn().commit()

    def eliminate_interest(self, interest_id: str, user_id: str = _DEFAULT_USER) -> None:
        self._get_conn().execute(
            "UPDATE interests SET is_eliminated=1, eliminated_at=datetime('now') "
            "WHERE id=? AND user_id=?",
            (interest_id, user_id),
        )
        self._get_conn().commit()

    # ── Tasks (global) ──

    def get_tasks(self, status: str = "pending") -> list[dict]:
        return [dict(r) for r in self._get_conn().execute(
            "SELECT * FROM tasks WHERE status=? ORDER BY priority DESC", (status,)
        ).fetchall()]

    def upsert_task(self, data: dict) -> None:
        cols = list(data.keys())
        ph = ",".join(["?"] * len(cols))
        upd = ",".join([f"{c}=excluded.{c}" for c in cols if c != "id"])
        self._get_conn().execute(
            f"INSERT INTO tasks({','.join(cols)}) VALUES({ph}) ON CONFLICT(id) DO UPDATE SET {upd}",
            [data[c] for c in cols],
        )
        self._get_conn().commit()

    # ── Todo 镜像（三件套桥接②：宿主 todo 清单 → 插件承诺账本）──

    def upsert_todo_mirror(self, todos: list[dict], user_id: str) -> None:
        """将宿主 todo 工具的活跃清单镜像进 tasks 表。

        幂等对账：以 mirror-<原id> 为键 upsert 全量快照；
        不在本次快照里的旧镜像活跃项视为已完成（从清单消失即了结）。
        todos 元素形如 {"id": str, "content": str, "status": "pending|in_progress|completed"}。
        """
        conn = self._get_conn()
        seen_ids: set[str] = set()
        for item in todos:
            orig_id = str(item.get("id", "")).strip()
            content = (item.get("content") or "").strip()
            if not orig_id or not content:
                continue
            mid = f"mirror-{orig_id}"
            seen_ids.add(mid)
            raw_status = item.get("status", "pending")
            status = "completed" if raw_status == "completed" else (
                "in_progress" if raw_status == "in_progress" else "pending")
            conn.execute(
                "INSERT INTO tasks(id,title,description,source,status,user_id) "
                "VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET title=excluded.title, "
                "status=excluded.status, user_id=excluded.user_id",
                (mid, content[:100], f"宿主todo原id:{orig_id}", "todo_mirror",
                 status, user_id),
            )
        # 对账：快照中已消失的旧镜像活跃项 → completed
        rows = conn.execute(
            "SELECT id FROM tasks WHERE source='todo_mirror' AND user_id=? "
            "AND status IN ('pending','in_progress')", (user_id,)
        ).fetchall()
        for r in rows:
            if r["id"] not in seen_ids:
                conn.execute(
                    "UPDATE tasks SET status='completed', "
                    "completed_at=datetime('now') WHERE id=?", (r["id"],))
        conn.commit()

    def get_active_todos(self, user_id: str) -> list[dict]:
        """读取镜像的活跃 todo（pending/in_progress），用于唤醒轮回灌。"""
        return [dict(r) for r in self._get_conn().execute(
            "SELECT * FROM tasks WHERE source='todo_mirror' AND user_id=? "
            "AND status IN ('pending','in_progress') ORDER BY created_at",
            (user_id,),
        ).fetchall()]

    # ── 活跃用户（scheduler 逐用户 tick 用）──

    def get_active_user_ids(self) -> list[str]:
        """所有在 current_state 有状态记录的**真人**用户ID。

        __global__ 只是生理状态的共享命名空间，不是一个人；混进 tick 列表会让
        关系/情感段给幽灵用户凭空衰减，故排除。"""
        rows = self._get_conn().execute(
            "SELECT DISTINCT user_id FROM current_state"
        ).fetchall()
        return [r["user_id"] for r in rows if r["user_id"] != _DEFAULT_USER]

    # ── Event log (per-user) ──

    def log_event(self, event_type: str, source: str, user_id: str = _DEFAULT_USER,
                  details: str = "", snapshot: str = "") -> None:
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO event_log(timestamp,event_type,user_id,source,details,state_snapshot) "
            "VALUES(datetime('now'),?,?,?,?,?)",
            (event_type, user_id, source, details, snapshot),
        )
        conn.commit()
        # 轻量保留：每 200 条检查一次，超出上限则删除最旧行，约束 event_log 长期增长
        self._event_insert_count += 1
        if self._event_insert_count % 200 == 0:
            try:
                conn.execute(
                    "DELETE FROM event_log WHERE id <= "
                    "(SELECT MAX(id) FROM event_log) - ?",
                    (self._event_keep,),
                )
                conn.commit()
            except Exception:
                pass

    # ── Emotion history (per-user) ──

    def record_emotion(self, user_id: str, pad_p: float, pad_a: float, pad_d: float,
                       label: str, bond_c: float, bond_d: float, bond_i: float,
                       bond_t: float, trigger: str = "") -> None:
        self._get_conn().execute(
            "INSERT INTO emotion_history(timestamp,user_id,pad_p,pad_a,pad_d,emotion_label,"
            "bond_c,bond_d_rel,bond_i,bond_t,trigger_event) "
            "VALUES(datetime('now'),?,?,?,?,?,?,?,?,?,?)",
            (user_id, pad_p, pad_a, pad_d, label, bond_c, bond_d, bond_i, bond_t, trigger),
        )
        self._get_conn().commit()

    # ── Patrol counter (global) ──

    def increment_patrol_counter(self) -> int:
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO current_state(key,user_id,value,updated_at) "
            "VALUES('patrol_step_counter','__global__',0,datetime('now')) "
            "ON CONFLICT(key,user_id) DO UPDATE SET value=value+1, updated_at=datetime('now')"
        )
        conn.commit()
        row = conn.execute(
            "SELECT value FROM current_state WHERE key='patrol_step_counter' AND user_id='__global__'"
        ).fetchone()
        return int(row["value"]) if row else 0

    def reset_patrol_counter(self) -> None:
        conn = self._get_conn()
        conn.execute(
            "UPDATE current_state SET value=0 WHERE key='patrol_step_counter' AND user_id='__global__'"
        )
        conn.commit()

    # ── Daily counters (per-user) ──

    def get_daily_counter(self, dimension: str, direction: str, user_id: str = _DEFAULT_USER) -> float:
        key = f"daily_{dimension}_{direction}"
        row = self._get_conn().execute(
            "SELECT value FROM current_state WHERE key=? AND user_id=?", (key, user_id)
        ).fetchone()
        return float(row["value"]) if row else 0.0

    def add_daily_counter(self, dimension: str, direction: str, amount: float,
                          user_id: str = _DEFAULT_USER) -> None:
        key = f"daily_{dimension}_{direction}"
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO current_state(key,user_id,value,updated_at) VALUES(?,?,?,datetime('now')) "
            "ON CONFLICT(key,user_id) DO UPDATE SET value=value+?, updated_at=datetime('now')",
            (key, user_id, amount, amount),
        )
        conn.commit()

    def reset_daily_counters(self, user_id: str = _DEFAULT_USER) -> None:
        self._get_conn().execute(
            "DELETE FROM current_state WHERE user_id=? AND key LIKE 'daily_%'", (user_id,)
        )
        self._get_conn().commit()

    # ── Message queue (global) ──

    def queue_message(self, sender: str, content: str) -> None:
        self._get_conn().execute(
            "INSERT INTO message_queue(sender,content) VALUES(?,?)", (sender, content)
        )
        self._get_conn().commit()

    def get_queued_messages(self, delivered: bool = False) -> list[dict]:
        return [dict(r) for r in self._get_conn().execute(
            "SELECT * FROM message_queue WHERE delivered=? ORDER BY queued_at",
            (1 if delivered else 0,),
        ).fetchall()]

    def mark_delivered(self, msg_id: int) -> None:
        self._get_conn().execute(
            "UPDATE message_queue SET delivered=1 WHERE id=?", (msg_id,))
        self._get_conn().commit()

    # ── Social outreach state（设计12：结构化社交元数据） ──

    def get_outreach(self, user_id: str) -> dict | None:
        row = self._get_conn().execute(
            "SELECT * FROM outreach_state WHERE user_id=?", (user_id,)).fetchone()
        return dict(row) if row else None

    def get_all_outreach(self) -> list[dict]:
        return [dict(r) for r in self._get_conn().execute(
            "SELECT * FROM outreach_state ORDER BY updated_at DESC").fetchall()]

    def upsert_outreach(self, user_id: str, **fields: Any) -> None:
        """部分字段更新，不存在则创建。fields ⊆ {last_outreach_at,last_reply_at,unanswered_count,cooldown_until}"""
        allowed = {"last_outreach_at", "last_reply_at", "unanswered_count", "cooldown_until"}
        cols = [k for k in fields if k in allowed]
        if not cols:
            return
        existing = self.get_outreach(user_id)
        if existing:
            sets = ", ".join(f"{c}=?" for c in cols)
            self._get_conn().execute(
                f"UPDATE outreach_state SET {sets}, updated_at=datetime('now') WHERE user_id=?",
                [fields[c] for c in cols] + [user_id])
        else:
            base = {c: fields.get(c) for c in allowed}
            self._get_conn().execute(
                "INSERT INTO outreach_state (user_id, last_outreach_at, last_reply_at,"
                " unanswered_count, cooldown_until, updated_at)"
                " VALUES (?,?,?,?,?,datetime('now'))",
                (user_id, base["last_outreach_at"], base["last_reply_at"],
                 base["unanswered_count"] if base["unanswered_count"] is not None else 0,
                 base["cooldown_until"]))
        self._get_conn().commit()

    def close(self) -> None:
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS current_state (
    key TEXT NOT NULL,
    user_id TEXT NOT NULL DEFAULT '__global__',
    value REAL,
    updated_at TEXT,
    PRIMARY KEY(key, user_id)
);

CREATE TABLE IF NOT EXISTS interests (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT '__global__',
    name TEXT,
    category TEXT,
    tags TEXT DEFAULT '[]',
    attitude REAL DEFAULT 0.0,
    interest_level REAL DEFAULT 0.5,
    heat REAL DEFAULT 50.0,
    priority INTEGER DEFAULT 5,
    times_experienced INTEGER DEFAULT 0,
    last_experienced_at TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    source TEXT DEFAULT 'user_influence',
    notes TEXT DEFAULT '',
    is_eliminated INTEGER DEFAULT 0,
    eliminated_at TEXT,
    promoted_to TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    title TEXT,
    description TEXT DEFAULT '',
    source TEXT DEFAULT 'self_planned',
    priority INTEGER DEFAULT 5,
    status TEXT DEFAULT 'pending',
    created_at TEXT DEFAULT (datetime('now')),
    started_at TEXT,
    completed_at TEXT,
    deadline TEXT,
    estimated_minutes INTEGER DEFAULT 30,
    energy_cost REAL DEFAULT 5.0,
    interest_tags TEXT DEFAULT '[]',
    personal_appeal REAL DEFAULT 0.5
);

CREATE TABLE IF NOT EXISTS event_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    event_type TEXT,
    user_id TEXT NOT NULL DEFAULT '__global__',
    source TEXT,
    details TEXT DEFAULT '',
    state_snapshot TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS emotion_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    user_id TEXT NOT NULL,
    pad_p REAL, pad_a REAL, pad_d REAL,
    emotion_label TEXT DEFAULT '',
    bond_c REAL, bond_d_rel REAL, bond_i REAL, bond_t REAL,
    trigger_event TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS message_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    queued_at TEXT DEFAULT (datetime('now')),
    sender TEXT,
    content TEXT,
    delivered INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS trauma_state (
    user_id TEXT NOT NULL,
    active INTEGER DEFAULT 0,
    started_at TEXT,
    PRIMARY KEY(user_id)
);

CREATE TABLE IF NOT EXISTS patrol_context (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    role TEXT,
    content TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS outreach_state (
    user_id TEXT PRIMARY KEY,
    last_outreach_at TEXT,
    last_reply_at TEXT,
    unanswered_count INTEGER DEFAULT 0,
    cooldown_until TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);
"""

# 已有库的增量迁移：老版本建库时没有 outreach_state 表
_OUTREACH_MIGRATE = """
CREATE TABLE IF NOT EXISTS outreach_state (
    user_id TEXT PRIMARY KEY,
    last_outreach_at TEXT,
    last_reply_at TEXT,
    unanswered_count INTEGER DEFAULT 0,
    cooldown_until TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);
"""
