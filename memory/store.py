# -*- coding: utf-8 -*-
"""memory.store — DAG 知识库守门层、生命周期与检索（升级方案 §6/§8/§10）。

设计要点：
- 守门层：长期价值判据 / 归一去重（title 精确 + 内容 Jaccard）/ DAG 环校验 /
  置信门 / 作用域 / 容量 / 事务（批内多语句单 commit，隐式事务回滚）
- 生命周期：类型化 TTL 衰减（读取时现算纯函数，零调度器）；goal 按 occurred_at
  阶跃（约定在事件发生前不衰减）；强化延长寿命
- 检索：种子 token 匹配 → 图扩展（1 跳全量/2 跳强边）→ 加权求和 × 衰减乘数 →
  近期保留槽 → MMR 多样性选择 → 强化反馈
"""
import json
import math
import uuid
from datetime import datetime
from pathlib import Path

# 绝对导入：内存/宿主/容器加载一律把 hermes-alive 根挂 sys.path（相对导入超顶）
from storage.db import _WRITE_LOCK  # R-H/26：与 AliveDB 共享同一写锁
from .normalize import extract_tokens, jaccard, normalize_title, overlap

try:  # Python 3.9+ 兼容
    from datetime import timezone
except ImportError:  # pragma: no cover
    timezone = None

NODE_TYPES = ("person", "fact", "event", "topic", "emotion", "goal", "artifact")
EDGE_TYPES = ("causes", "relates", "supports", "contradicts", "part_of",
              "follows", "mentions")
# 参与环校验的边（有向传递语义）；relates/supports/contradicts/mentions 不参与
ACYCLIC_EDGE_TYPES = ("causes", "part_of", "follows")

# ── v2.4 §22（1:1 复刻 livingmemory 原子层）：认知五类 + 类型化 TTL ──
# 对齐 memory_atom.py：五类原子（episodic 经历/factual 事实/relational 关系
# 身份/preference 偏好/planned 计划），base_ttl（天）与衰减曲线逐一对应：
#   episodic 7 exp / factual 180 exp / relational 90 linear / preference 60 exp
#   / planned 2 step（事件时间驱动，事件前不衰减）
ATOM_TYPES = ("episodic", "factual", "relational", "preference", "planned")
ATOM_TTL = {
    "episodic": (7, "exp"),
    "factual": (180, "exp"),
    "relational": (90, "linear"),
    "preference": (60, "exp"),
    "planned": (2, "step"),
}
# 业务七类 → 认知五类（工具/巡查层词汇兼容；atom_type 为存储层第一公民）
NODE_TO_ATOM = {
    "event": "episodic",
    "emotion": "episodic",
    "fact": "factual",
    "topic": "factual",
    "artifact": "factual",
    "person": "relational",   # 身份/关系；偏好语义由调用方显式传 preference
    "goal": "planned",
}
PROTECTED_IMPORTANCE = 0.8   # protected 豁免阈值（衰减/淡忘不免除）
# R-H/37（红队）：淘汰/修订/归档节点物理清理窗（天）——decayed 仅状态翻转、
# 行永驻 DB；active 有 cap 而物理行无 cap，长跑会无限膨胀。超窗即物理删除
# （检索被动但保留一个月仍可达，符合"记忆慢慢褪去而非瞬间消失"）。
PURGE_AFTER_DAYS = 30

# 类型化 TTL 表：(base_ttl_days, 曲线) —— 升级方案 §8
_TTL_TABLE = {
    "event": (14, "exp"),
    "goal": (14, "step"),      # occurred_at 驱动：事件前不衰减，事件后 base_ttl
    "fact": (180, "exp"),
    "topic": (90, "linear"),
    "person": (365, "linear"),
    "emotion": (60, "exp"),
    "artifact": (90, "exp"),
}

RECENT_SLOT = 2                # 近期记忆保留槽（72h 窗，top-k 强制保留）
RECENT_WINDOW_H = 72
SCORE_ALPHA = 0.4              # 检索相关性
SCORE_BETA = 0.3               # 显著度
SCORE_GAMMA = 0.15             # 新鲜度（最近被提及度）
SCORE_DELTA = 0.15             # 边权聚合
MMR_LAMBDA = 0.7
RRF_K = 60                    # RRF 融合常数（1:1 对齐 rrf_fusion.py）
CROSS_ROUTE_BONUS = 0.08      # 多路同时命中加分（1:1 对齐）
# v2.4 §22：路由权重（1:1 对齐 document_route_weight/graph_route_weight）
DOCUMENT_ROUTE_WEIGHT = 0.65
GRAPH_ROUTE_WEIGHT = 0.35


def _fts_text(text: str) -> str:
    """FTS5 预分词文本（unicode61 按空格分词，中文需预切——对齐 livingmemory）。"""
    return " ".join(sorted(extract_tokens(text)))


def bm25_scores(conn, fts_table: str, id_col: str, query_tokens,
                limit: int = 20) -> dict:
    """BM25 路（FTS5 bm25() 排序，语义 1:1 对齐 atom_store.search_bm25）。

    返回 {id: 归一化分数}（bm25 值越小越相关 → max-score/score_range）。
    R-H/28（红队）：查询 token 用 OR 连接——此前空格=AND，中文 bigram 词集
    （含整词+双字片）越多的查询越容易整体落空（实测 5-token AND 命中 0 行、
    2-token 可命中），导致中文多词检索 BM25 路召回为 0；OR 下任一 token
    命中即召回，相关度由 bm25() 与后续 RRF/融合排序保证。
    """
    toks = sorted(set(query_tokens))
    if not toks:
        return {}
    qs = " OR ".join(toks)
    try:
        rows = conn.execute(
            f"SELECT {id_col} AS _id, bm25({fts_table}) AS s "
            f"FROM {fts_table} WHERE {fts_table} MATCH ? ORDER BY s LIMIT ?",
            (qs, limit)).fetchall()
    except Exception:
        return {}
    if not rows:
        return {}
    vals = [float(r["s"]) for r in rows]
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1.0
    return {str(r["_id"]): (hi - float(r["s"])) / rng for r in rows}


def rrf_fuse(rank_lists, k: int = RRF_K) -> list:
    """多路排名 RRF 融合（1:1 对齐 livingmemory rrf_fusion：score=Σ 1/(k+rank)）。

    rank_lists：每路已排序 items（需含 id）；同项多路命中按 CROSS_ROUTE_BONUS
    加分（对应 cross_route_bonus）。返回按融合分降序，每项带 rrf/routes。
    """
    fused = {}
    for ranks in rank_lists:
        for rank, item in enumerate(ranks):
            key = str(item.get("id") or "")
            if not key:
                continue
            rec = fused.setdefault(key, {"item": item, "score": 0.0,
                                         "routes": []})
            rec["score"] += 1.0 / (k + rank + 1)
            route = str(item.get("route") or "?")
            if route not in rec["routes"]:
                rec["routes"].append(route)
    out = []
    for rec in fused.values():
        it = dict(rec["item"])
        score = rec["score"]
        if len(rec["routes"]) >= 2:
            score += CROSS_ROUTE_BONUS
        it["rrf"] = round(score, 6)
        it["routes"] = rec["routes"]
        out.append(it)
    out.sort(key=lambda x: -x["rrf"])
    return out


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _ts(s: str):
    """ISO/日期字符串 → epoch 秒；解析失败返回 None。"""
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).strip()).timestamp()
    except Exception:
        pass
    try:
        return datetime.strptime(str(s).strip()[:10], "%Y-%m-%d").timestamp()
    except Exception:
        return None


def decay_factor(node: dict, now_ts: float = None) -> float:
    """类型化 TTL 衰减乘数（纯函数，读取时现算）。返回 0..1。

    v2.4 §22：atom_type（认知五类）优先——1:1 对齐 livingmemory 原子 TTL
    参数（episodic 7 exp / factual 180 exp / relational 90 linear /
    preference 60 exp / planned 2 step）；无 atom_type 的存量节点退回
    业务七类表。
    """
    now_ts = now_ts or datetime.now().timestamp()
    atom = str(node.get("atom_type") or "").strip()
    if atom in ATOM_TTL:
        base_ttl, curve = ATOM_TTL[atom]
        ntype = atom
    else:
        ntype = str(node.get("type") or "fact")
        base_ttl, curve = _TTL_TABLE.get(ntype, (30, "exp"))
    # TTL 扩展因子：importance 与强化次数延长寿命
    importance = float(node.get("importance") or 0.5)
    rc = int(node.get("reinforcement_count") or 0)
    ttl = base_ttl * (0.5 + max(0.0, min(1.0, importance))) * (1 + min(0.5, rc * 0.1))

    def _days_since(iso_str, default_days=0.0):
        ts = _ts(iso_str)
        if ts is None:
            return default_days * 86400.0
        return max(0.0, now_ts - ts) / 86400.0

    if ntype in ("goal", "planned"):
        # occurred_at 阶跃：事件发生前不衰减；事件后 ttl 内=1，过期即 0.05
        occ = _ts(node.get("occurred_at"))
        if occ is None:
            # 无发生时间的计划退化为指数衰减
            days = _days_since(node.get("last_activated_at"), 0)
            return math.exp(-math.log(2) * days / max(0.5, ttl / 2))
        days_to = (occ - now_ts) / 86400.0
        if days_to >= 0:
            return 1.0
        return 1.0 if -days_to <= ttl else 0.05

    days = _days_since(node.get("last_activated_at"),
                       default_days=0.0 if _ts(node.get("last_activated_at")) else 30.0)
    if curve == "linear":
        return max(0.0, 1.0 - days / max(1.0, ttl))
    if curve == "step":
        return 1.0 if days <= ttl else 0.05
    return math.exp(-math.log(2) * days / max(0.5, ttl / 2))


class MemoryStore:
    """DAG 记忆库。db 为 storage.db.AliveDB 实例（复用其连接与事务）。"""

    def __init__(self, db, cfg=None, light=False):
        self.db = db
        self.cfg = cfg or {}
        self.enabled = bool(self.cfg.get("enabled", True))
        self.min_confidence = float(self.cfg.get("min_confidence", 0.4))
        self.max_active = int(self.cfg.get("max_active_nodes", 400))
        self.jaccard_dedup = float(self.cfg.get("jaccard_dedup_threshold", 0.4))
        self.top_k = int(self.cfg.get("top_k", 8))
        self.expand_depth = int(self.cfg.get("expand_depth", 1))
        self.second_hop_weight = float(self.cfg.get("second_hop_weight", 0.4))
        self.budget_tokens = int(self.cfg.get("inject_budget_tokens", 600))
        from .embedding import EmbeddingClient
        self.emb = EmbeddingClient(self.cfg)
        from .faiss_index import FaissIndex
        db_path = getattr(self.db, "_db_path", None)
        default_index = (Path(db_path).parent / "livingmemory.index"
                         if db_path else Path("livingmemory.index"))
        self.faiss = FaissIndex(self.cfg.get("faiss_index_path", default_index),
                                self.cfg.get("embedding_dim", 0))
        # light 模式（dashboard 等只读消费进程）：跳过启动期批量 backfill /
        # reconcile。这些写事务与 gateway 主进程互斥（WAL 单写者），且可能在
        # async 事件循环里同步执行，阻塞整个 dashboard 并撞锁 scheduler。
        if light:
            return
        self._fts_backfill()
        self._vec_backfill()
        if self.faiss.enabled:
            valid_ids = [r[0] for r in self._conn().execute(
                "SELECT item_id FROM mem_vecs").fetchall()]
            self.faiss.reconcile(valid_ids)
        try:
            self.backfill_cooccurrence_edges()
            self.backfill_entry_node_links()
        except Exception:
            pass

    def backfill_entry_node_links(self, user_id: str = None) -> int:
        """为历史经历补建条目到提炼节点的显式关联。"""
        conn = self._conn()
        users = ([str(user_id)] if user_id else [
            r["user_id"] for r in conn.execute(
                "SELECT DISTINCT user_id FROM mem_entries").fetchall()])
        added = 0
        for uid in users:
            nodes = self.list_nodes(user_id=uid, status="active", limit=300)
            if not nodes:
                continue
            for e in conn.execute(
                "SELECT id, summary, key_facts FROM mem_entries WHERE user_id=?",
                (uid,)).fetchall():
                text = str(e["summary"] or "")
                try:
                    text += " " + " ".join(json.loads(e["key_facts"] or "[]"))
                except Exception:
                    pass
                toks = extract_tokens(text)
                ids = [n["id"] for n in nodes
                       if set(extract_tokens(n["title"])).intersection(toks)]
                added += self.link_entry_nodes(e["id"], uid, ids)
        return added

    # ── 拓扑补边（对齐 livingmemory GraphExtractor 关系提取思想，规则版） ──

    def backfill_cooccurrence_edges(self, user_id: str = None,
                                    per_entry_limit: int = 6,
                                    entry_id: int = None) -> int:
        """从经历条目回填节点间关系边（幂等，UNIQUE(from,to,type) 兜底）。

        同一条目的 summary+key_facts 中 token 命中 ≥2 个节点标题 → 链式
        relates 边（链式而非全连接，避免子团爆炸；环检测/降级照走）。
        entry_id 指定时只处理该条目（反思流实时补边）。
        """
        conn = self._conn()
        users = ([user_id] if user_id else [
            r["user_id"] for r in conn.execute(
                "SELECT DISTINCT user_id FROM mem_entries").fetchall()])
        added = 0
        for uid in users:
            nodes = self.list_nodes(user_id=uid, status="active", limit=300)
            if len(nodes) < 2:
                continue
            toks_of = {n["id"]: {t for t in extract_tokens(n["title"])
                                 if len(t) >= 2} for n in nodes}
            if entry_id is not None:
                entries = conn.execute(
                    "SELECT id, summary, key_facts FROM mem_entries "
                    "WHERE user_id=? AND id=?", (uid, int(entry_id))).fetchall()
            else:
                entries = conn.execute(
                    "SELECT id, summary, key_facts FROM mem_entries "
                    "WHERE user_id=?", (uid,)).fetchall()
            for e in entries:
                text = str(e["summary"] or "")
                try:
                    for kf in json.loads(e["key_facts"] or "[]"):
                        text += " " + str(kf)
                except Exception:
                    pass
                text_toks = extract_tokens(text)
                hit_ids = []
                for n in nodes:
                    nt = toks_of[n["id"]]
                    if nt and not nt.isdisjoint(text_toks):
                        hit_ids.append(n["id"])
                hit_ids = list(dict.fromkeys(hit_ids))
                if len(hit_ids) < 2:
                    continue
                ops = [{"op": "link", "from": hit_ids[i],
                        "to": hit_ids[i + 1], "rel": "relates",
                        "weight": 0.4}
                       for i in range(min(len(hit_ids) - 1,
                                          per_entry_limit))]
                try:
                    st = self.apply_memory_ops(ops, uid,
                                               source="backfill")
                    added += int(st.get("linked") or 0)
                except Exception:
                    continue
        return added

    def _vec_upsert(self, item_id: str, kind: str, user_id: str, text: str):
        """向量 upsert（embedding 未启用/失败静默跳过，不阻塞写入路径）。"""
        try:
            if not self.emb.enabled:
                return
            vec = self.emb.embed([text])[0]
            if self.faiss.enabled:
                self.faiss.upsert(item_id, vec)
            conn = self._conn()
            conn.execute(
                "INSERT OR REPLACE INTO mem_vecs(item_id,kind,user_id,dim,vec) "
                "VALUES(?,?,?,?,?)",
                (item_id, kind, user_id, len(vec), json.dumps(vec)))
            conn.commit()
        except Exception:
            pass

    def _emb_safe(self, text: str):
        """事务外安全取向量：embedding HTTP 必须在开启写事务之前完成，
        否则长持写锁会与 scheduler 线程互斥，触发 database is locked。"""
        try:
            if not self.emb.enabled:
                return None
            return self.emb.embed([text])[0]
        except Exception:
            return None

    def _vec_backfill(self):
        """向量懒回填（幂等批量：缺向量的节点/条目一次 API 补齐）。"""
        try:
            if not self.emb.enabled:
                return
            conn = self._conn()
            have = {r[0] for r in conn.execute("SELECT item_id FROM mem_vecs")}
            todo_n = [r for r in conn.execute(
                "SELECT id,title,content,user_id FROM mem_nodes")
                if r["id"] not in have]
            todo_e = [r for r in conn.execute(
                "SELECT id,summary,user_id FROM mem_entries")
                if f"e_{r['id']}" not in have]
            if todo_n:
                vecs = self.emb.embed([f"{r['title']} {r['content'] or ''}"
                                       for r in todo_n])
                for r, v in zip(todo_n, vecs):
                    if self.faiss.enabled:
                        self.faiss.upsert(r["id"], v)
                    conn.execute(
                        "INSERT OR REPLACE INTO mem_vecs(item_id,kind,user_id,dim,vec) "
                        "VALUES(?,?,?,?,?)",
                        (r["id"], "node", r["user_id"], len(v), json.dumps(v)))
            if todo_e:
                vecs = self.emb.embed([r["summary"] or "" for r in todo_e])
                for r, v in zip(todo_e, vecs):
                    if self.faiss.enabled:
                        self.faiss.upsert(f"e_{r['id']}", v)
                    conn.execute(
                        "INSERT OR REPLACE INTO mem_vecs(item_id,kind,user_id,dim,vec) "
                        "VALUES(?,?,?,?,?)",
                        (f"e_{r['id']}", "entry", r["user_id"], len(v),
                         json.dumps(v)))
            conn.commit()
        except Exception:
            pass

    def _vec_search(self, query: str, user_id: str, top_k: int = 8) -> list:
        """向量最近邻（余弦；FAISS Flat 等价的精确检索）。"""
        if not self.emb.enabled:
            return []
        from .embedding import cosine
        try:
            qv = self.emb.embed([query])[0]
            conn = self._conn()
            allowed = {str(r["item_id"]): str(r["kind"]) for r in conn.execute(
                "SELECT item_id,kind FROM mem_vecs "
                "WHERE user_id IN (?,'__global__')", (user_id,)).fetchall()}
            if self.faiss.enabled:
                return [(item_id, allowed[item_id], score)
                        for item_id, score in self.faiss.search(
                            qv, max(self.faiss.index.ntotal, top_k))
                        if item_id in allowed][:max(5, top_k)]
            scored = []
            for r in conn.execute(
                    "SELECT item_id,kind,vec FROM mem_vecs "
                    "WHERE user_id IN (?,'__global__')", (user_id,)).fetchall():
                c = cosine(qv, json.loads(r["vec"]))
                if c > 0.15:
                    scored.append((str(r["item_id"]), str(r["kind"]), c))
            scored.sort(key=lambda x: -x[2])
            return scored[:max(5, top_k)]
        except Exception:
            return []

    def _fts_backfill(self):
        """存量数据 FTS 回填（幂等：行数不一致时重建全部索引行）。"""
        try:
            conn = self._conn()
            n_nodes = conn.execute("SELECT COUNT(*) c FROM mem_nodes").fetchone()["c"]
            n_fts = conn.execute("SELECT COUNT(*) c FROM mem_nodes_fts").fetchone()["c"]
            if n_nodes != n_fts:
                for r in conn.execute("SELECT id,title,content FROM mem_nodes").fetchall():
                    conn.execute("DELETE FROM mem_nodes_fts WHERE node_id=?", (r["id"],))
                    conn.execute("INSERT INTO mem_nodes_fts(content,node_id) VALUES(?,?)",
                                 (_fts_text(f"{r['title']} {r['content'] or ''}"), r["id"]))
            n_ent = conn.execute("SELECT COUNT(*) c FROM mem_entries").fetchone()["c"]
            n_efts = conn.execute("SELECT COUNT(*) c FROM mem_entries_fts").fetchone()["c"]
            if n_ent != n_efts:
                for r in conn.execute("SELECT id,summary FROM mem_entries").fetchall():
                    conn.execute("DELETE FROM mem_entries_fts WHERE entry_id=?", (r["id"],))
                    conn.execute("INSERT INTO mem_entries_fts(content,entry_id) VALUES(?,?)",
                                 (_fts_text(r["summary"] or ""), r["id"]))
            conn.commit()
        except Exception:
            pass

    # ────────────────────────── 基础存取 ──────────────────────────

    def _conn(self):
        return self.db._get_conn()

    def _row_to_node(self, r) -> dict:
        d = dict(r)
        try:
            d["aliases"] = json.loads(d.get("aliases") or "[]")
        except Exception:
            d["aliases"] = []
        return d

    def get_node(self, node_id: str):
        r = self._conn().execute(
            "SELECT * FROM mem_nodes WHERE id=?", (node_id,)).fetchone()
        return self._row_to_node(r) if r else None

    def find_by_title(self, title: str, user_id: str, type_: str = None):
        """归一标题精确匹配（同域 + __global__），active 优先。"""
        conn = self._conn()
        sql = ("SELECT * FROM mem_nodes WHERE user_id IN (?, '__global__') "
               "AND title=?")
        params = [user_id, title]
        if type_:
            sql += " AND type=?"
            params.append(type_)
        rows = conn.execute(sql + " ORDER BY CASE WHEN user_id=? THEN 0 ELSE 1 END, "
                            "CASE WHEN status='active' THEN 0 ELSE 1 END",
                            params + [user_id]).fetchall()
        return self._row_to_node(rows[0]) if rows else None

    def list_nodes(self, user_id: str = None, status: str = None,
                   type_: str = None, limit: int = 200) -> list:
        conn = self._conn()
        sql, conds, params = "SELECT * FROM mem_nodes", [], []
        if user_id:
            conds.append("user_id IN (?, '__global__')")
            params += [user_id]
        if status:
            conds.append("status=?")
            params.append(status)
        if type_:
            conds.append("type=?")
            params.append(type_)
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY salience DESC LIMIT ?"
        params.append(limit)
        return [self._row_to_node(r) for r in conn.execute(sql, params).fetchall()]

    def graph_snapshot(self, user_id="__global__", limit_nodes=80, limit_edges=120):
        conn = self._conn()
        nodes = self.list_nodes(user_id=user_id, limit=max(1, min(500, int(limit_nodes))))
        ids = {n["id"] for n in nodes}
        scoped_edges = conn.execute(
            "SELECT * FROM mem_edges WHERE user_id IN (?, '__global__') "
            "ORDER BY rowid DESC LIMIT ?",
            (user_id, max(1, min(5000, int(limit_edges) * 10))),
        ).fetchall()
        edges = [dict(r) for r in scoped_edges
                 if r["from_id"] in ids and r["to_id"] in ids][:max(1, min(1000, int(limit_edges)))]
        return {"nodes": nodes, "edges": edges, "entries": self.list_entries(user_id, limit=80)}

    def revise_node(self, node_id, user_id, title=None, content=None, occurred_at=None, importance=None):
        conn = self._conn()
        old = conn.execute("SELECT * FROM mem_nodes WHERE id=? AND user_id=?", (str(node_id), str(user_id))).fetchone()
        if not old:
            return None
        old = self._row_to_node(old)
        new_id = f"n_{uuid.uuid4().hex[:8]}"
        now = _now_iso()
        new_title = normalize_title(title or old["title"])
        new_content = str(content if content is not None else old.get("content") or "")
        new_occ = str(occurred_at if occurred_at is not None else old.get("occurred_at") or "")
        imp = float(importance if importance is not None else old.get("importance") or 0.5)
        conn.execute("UPDATE mem_nodes SET status='superseded', superseded_by=?, updated_at=? WHERE id=?", (new_id, now, old["id"]))
        conn.execute("INSERT INTO mem_nodes(id,type,title,aliases,content,attrs,occurred_at,user_id,salience,importance,confidence,source,source_ref,atom_type,status,created_at,updated_at,last_activated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (new_id, old["type"], new_title, json.dumps(old.get("aliases") or [], ensure_ascii=False), new_content, json.dumps(old.get("attrs") or {}, ensure_ascii=False), new_occ, user_id, old.get("salience") or 0.5, max(0.0, min(1.0, imp)), old.get("confidence") or 0.7, old.get("source") or "revision", old.get("source_ref") or "", old.get("atom_type") or "factual", "active", now, now, now))
        conn.execute("INSERT INTO mem_nodes_fts(content,node_id) VALUES(?,?)", (_fts_text(f"{new_title} {new_content}"), new_id))
        conn.commit()
        self._vec_upsert(new_id, "node", user_id, f"{new_title} {new_content}")
        return self.get_node(new_id)

    def purge_nodes(self, user_id, node_ids=None, older_than_days=None):
        conn = self._conn()
        cond = ["user_id=?", "status IN ('superseded','archived','decayed')"]
        args = [user_id]
        if node_ids:
            marks = ",".join("?" for _ in node_ids)
            cond.append(f"id IN ({marks})")
            args.extend(str(x) for x in node_ids)
        if older_than_days is not None:
            cond.append("created_at < datetime('now', ?)")
            args.append(f"-{max(0, int(older_than_days))} days")
        rows = conn.execute("SELECT id FROM mem_nodes WHERE " + " AND ".join(cond), args).fetchall()
        ids = [str(r["id"]) for r in rows]
        if not ids:
            return 0
        marks = ",".join("?" for _ in ids)
        conn.execute(f"DELETE FROM mem_nodes_fts WHERE node_id IN ({marks})", ids)
        conn.execute(f"DELETE FROM mem_vecs WHERE item_id IN ({marks})", ids)
        conn.execute(f"DELETE FROM mem_edges WHERE from_id IN ({marks}) OR to_id IN ({marks})", ids + ids)
        conn.execute(f"DELETE FROM mem_nodes WHERE id IN ({marks})", ids)
        conn.commit()
        if getattr(self, "faiss", None) and self.faiss.enabled:
            for nid in ids:
                self.faiss.remove(nid)
        return len(ids)

    def consolidate_entries(self, user_id, entry_ids=None):
        entries = self.list_entries(user_id, limit=200)
        if entry_ids:
            wanted = {int(x) for x in entry_ids}
            entries = [e for e in entries if int(e["id"]) in wanted]
        if len(entries) < 2:
            return None
        entries = list(reversed(entries))
        summary = "；".join(str(e.get("summary") or "") for e in entries)
        topics = sorted({x for e in entries for x in (e.get("topics") or [])})
        facts = sorted({x for e in entries for x in (e.get("key_facts") or [])})
        new_id = self.add_entry(user_id, entries[-1].get("session_id") or "", summary, topics, facts, "neutral", max(float(e.get("importance") or 0.5) for e in entries), "consolidation")
        ids = [int(e["id"]) for e in entries]
        marks = ",".join("?" for _ in ids)
        self._conn().execute(f"UPDATE mem_entries SET status='archived', updated_at=? WHERE id IN ({marks})", [_now_iso()] + ids)
        self._conn().commit()
        return {"id": new_id, "consolidated_from": ids}

    # ────────────────────────── 守门层（§10） ──────────────────────────

    def _jaccard_duplicate(self, content: str, user_id: str, exclude_id: str = ""):
        """二级去重：归一 title 未命中但内容重叠系数高的既有节点。

        重叠系数（inter/min）阈值 0.4——n-gram 字级切片下短文本的 Jaccard
        被长度差稀释，重叠系数对"轻微改写"更稳（同内容换序 0.7+，补充新
        信息 0.3- 不触发）。
        """
        if not content:
            return None
        ctoks = extract_tokens(content)
        if not ctoks:
            return None
        for n in self.list_nodes(user_id=user_id, status="active", limit=400):
            if n["id"] == exclude_id:
                continue
            if overlap(ctoks, extract_tokens((n.get("title") or "") + " " +
                                             (n.get("content") or ""))) >= self.jaccard_dedup:
                return n
        return None

    def _creates_cycle(self, from_id: str, to_id: str) -> bool:
        """DFS：to 是否已有路径回到 from（有向环检测）。"""
        conn = self._conn()
        seen = set()
        stack = [to_id]
        while stack:
            cur = stack.pop()
            if cur == from_id:
                return True
            if cur in seen:
                continue
            seen.add(cur)
            for r in conn.execute(
                "SELECT to_id FROM mem_edges WHERE from_id=? AND type IN (?,?,?)",
                (cur, *ACYCLIC_EDGE_TYPES),
            ):
                stack.append(r["to_id"])
        return False

    def _enforce_capacity(self, user_id: str, conn) -> None:
        n = conn.execute(
            "SELECT COUNT(*) c FROM mem_nodes WHERE user_id=? AND status='active'",
            (user_id,)).fetchone()["c"]
        if n <= self.max_active:
            return
        # R-H/38（红队）：migrate 来源不再「完全豁免」淘汰——原 AND source!='migrate'
        # 使迁移导入 ≥max_active 个节点时无候选可逐，active 数永久顶破 cap
        # （每批 _enforce 都选不齐 n-max 行）。改两级排序：普通节点先逐，
        # migrate 节点仅在普通节点不足时才被逐（仍尽量保全迁移数据）。
        rows = conn.execute(
            "SELECT id FROM mem_nodes WHERE user_id=? AND status='active' "
            "ORDER BY (source='migrate') ASC, salience ASC LIMIT ?",
            (user_id, n - self.max_active)).fetchall()
        for r in rows:
            conn.execute("UPDATE mem_nodes SET status='decayed', updated_at=? "
                         "WHERE id=?", (_now_iso(), r["id"]))

    def apply_memory_ops(self, ops, user_id: str, source: str = "patrol",
                         source_ref: str = "") -> dict:
        """巡查/工具产出的 memory_ops 批处理（守门+事务）。返回统计。"""
        stats = {"added": 0, "updated": 0, "linked": 0, "rejected": 0,
                 "rejected_time": 0, "dedup_reinforced": 0}
        if not isinstance(ops, list):
            return stats
        conn = self._conn()
        try:
            for op in ops[:6]:  # 单批限数（§7 防挤占）
                try:
                    self._apply_one(op, user_id, source, source_ref, stats, conn)
                except Exception as e:
                    stats["rejected"] += 1
                    import logging
                    logging.getLogger(__name__).debug(
                        "[Memory] op rejected: %s", e)
            self._enforce_capacity(user_id, conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return stats

    def _apply_one(self, op: dict, user_id: str, source: str,
                   source_ref: str, stats: dict, conn) -> None:
        if not isinstance(op, dict):
            stats["rejected"] += 1
            return
        kind = str(op.get("op") or "").strip().lower()
        if kind in ("add_node", "add", "memorize"):
            self._op_add(op, user_id, source, source_ref, stats, conn)
        elif kind == "link":
            self._op_link(op, user_id, stats, conn)
        elif kind in ("update", "revise"):
            self._op_update(op, user_id, stats, conn)
        elif kind in ("archive", "forget"):
            title = normalize_title(op.get("title"))
            n = self.find_by_title(title, user_id)
            if n:
                conn.execute("UPDATE mem_nodes SET status='archived', updated_at=? "
                             "WHERE id=?", (_now_iso(), n["id"]))
        else:
            stats["rejected"] += 1

    def _op_add(self, op, user_id, source, source_ref, stats, conn):
        ntype = str(op.get("type") or "fact").strip().lower()
        if ntype not in NODE_TYPES:
            stats["rejected"] += 1
            return
        title = normalize_title(op.get("title"))
        content = str(op.get("content") or "").strip()
        if not title or (not content and ntype in ("event", "goal")):
            stats["rejected"] += 1
            return
        confidence = max(0.0, min(1.0, float(op.get("confidence") or 0.7)))
        if confidence < self.min_confidence:
            stats["rejected"] += 1
            return
        occurred_at = str(op.get("occurred_at") or "").strip()
        # ★ 时间绑定强制：event/goal 必须带发生时间（§7）
        if ntype in ("event", "goal") and not occurred_at:
            stats["rejected_time"] += 1
            return
        if occurred_at and _ts(occurred_at) is None:
            occurred_at = ""  # 无法解析的时间不落库
        # 情感里程碑判据：瞬时情绪波动不收（emotion_history 承担快照）
        if ntype == "emotion" and confidence < 0.6:
            stats["rejected"] += 1
            return

        aliases = [normalize_title(a) for a in (op.get("aliases") or [])
                   if normalize_title(a)]
        importance = max(0.0, min(1.0, float(op.get("importance") or 0.5)))

        existing = self.find_by_title(title, user_id, ntype)
        if existing is None:
            # 二级去重：内容 Jaccard 高相似 → 强化既有而非新建
            dup = self._jaccard_duplicate(f"{title} {content}", user_id)
            if dup is not None:
                self._reinforce_conn(conn, dup["id"])
                stats["dedup_reinforced"] += 1
                return
        if existing is not None:
            self._merge_into(existing, title, content, occurred_at, aliases,
                              confidence, conn)
            stats["updated"] += 1
            return

        nid = f"n_{uuid.uuid4().hex[:8]}"
        now = _now_iso()
        # v2.4 §22（1:1 复刻）：认知五类原子——显式传入优先，否则按七类映射；
        # 偏好语义（person 型"喜欢X"）由调用方传 atom_type=preference
        atom = str(op.get("atom_type") or "").strip().lower()
        if atom not in ATOM_TYPES:
            atom = NODE_TO_ATOM.get(ntype, "factual")
        # 修复：embedding HTTP 在写事务外预取（避免长持写锁 → scheduler locked）
        pre_vec = self._emb_safe(f"{title} {content}")
        conn.execute(
            "INSERT INTO mem_nodes(id,type,title,aliases,content,occurred_at,"
            "user_id,salience,importance,confidence,source,source_ref,atom_type,"
            "created_at,updated_at,last_activated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (nid, ntype, title, json.dumps(aliases, ensure_ascii=False), content,
              occurred_at, user_id, 0.5 + 0.1 * importance, importance,
              confidence, source, source_ref or str(op.get("source_ref") or ""),
              atom, now, now, now))
        conn.execute("INSERT INTO mem_nodes_fts(content, node_id) VALUES(?,?)",
                     (_fts_text(f"{title} {content}"), nid))
        if pre_vec is not None:
            try:
                if self.faiss.enabled:
                    self.faiss.upsert(nid, pre_vec)
                conn.execute(
                    "INSERT OR REPLACE INTO mem_vecs(item_id,kind,user_id,dim,vec) "
                    "VALUES(?,?,?,?,?)",
                    (nid, "node", user_id, len(pre_vec),
                     json.dumps(pre_vec)))
            except Exception:
                pass
        stats["added"] += 1
        # 顺带落 link（同一 op 内）
        for lk in (op.get("links") or []):
            if isinstance(lk, dict):
                self._op_link({**lk, "from_title": title}, user_id, stats, conn)

    def _op_link(self, op, user_id, stats, conn):
        etype = str(op.get("rel") or op.get("type") or "relates").strip().lower()
        if etype not in EDGE_TYPES:
            etype = "relates"
        weight = max(0.0, min(1.0, float(op.get("weight") or 0.5)))

        def _resolve(key, to_type_default="fact"):
            v = op.get(key)
            if not v:
                return None
            if str(v).startswith("n_"):
                return self.get_node(str(v))
            return self.find_by_title(normalize_title(v), user_id)

        a = _resolve("from") or _resolve("from_title", )
        b = _resolve("to") or _resolve("to_title")
        if a is None and op.get("from_title"):
            a = self._ensure_node(normalize_title(op.get("from_title")),
                                  "person", user_id, conn)
        if b is None and op.get("to_title"):
            b = self._ensure_node(normalize_title(op.get("to_title")),
                                  str(op.get("to_type") or "topic"), user_id, conn)
        if not a or not b or a["id"] == b["id"]:
            stats["rejected"] += 1
            return
        # 作用域：跨用户域边拒绝（__global__ 例外）
        if a["user_id"] != b["user_id"] and "__global__" not in (
                a["user_id"], b["user_id"]):
            stats["rejected"] += 1
            return
        if etype in ACYCLIC_EDGE_TYPES and self._creates_cycle(a["id"], b["id"]):
            etype = "relates"  # 降级保关系语义（§5）
        conn.execute(
            "INSERT OR IGNORE INTO mem_edges(id,from_id,to_id,type,weight,"
            "user_id) VALUES(?,?,?,?,?,?)",
            (f"e_{uuid.uuid4().hex[:8]}", a["id"], b["id"], etype, weight,
             user_id))
        stats["linked"] += 1

    def _op_update(self, op, user_id, stats, conn):
        title = normalize_title(op.get("title"))
        n = self.find_by_title(title, user_id)
        if not n:
            stats["rejected"] += 1
            return
        self._merge_into(n, title, str(op.get("content") or ""),
                         str(op.get("occurred_at") or ""),
                         [normalize_title(a) for a in (op.get("aliases") or [])
                          if normalize_title(a)],
                         max(0.0, min(1.0, float(op.get("confidence") or 0.5))),
                         conn)
        stats["updated"] += 1

    def _merge_into(self, node, title, content, occurred_at, aliases,
                    confidence, conn):
        new_content = content.strip() or node.get("content") or ""
        new_aliases = sorted(set((node.get("aliases") or []) + [a for a in aliases if a]))
        if occurred_at and _ts(occurred_at) and not node.get("occurred_at"):
            new_occ = occurred_at
        else:
            new_occ = node.get("occurred_at") or ""
        conn.execute(
            "UPDATE mem_nodes SET content=?, aliases=?, occurred_at=?, "
            "confidence=MAX(confidence,?), salience=MIN(1.0, salience+0.05), "
            "updated_at=? WHERE id=?",
            (new_content, json.dumps(new_aliases, ensure_ascii=False), new_occ,
             confidence, _now_iso(), node["id"]))
        # FTS 同步（1:1：BM25 索引随内容更新）
        conn.execute("DELETE FROM mem_nodes_fts WHERE node_id=?", (node["id"],))
        conn.execute("INSERT INTO mem_nodes_fts(content, node_id) VALUES(?,?)",
                     (_fts_text(f"{title} {new_content}"), node["id"]))

    def _ensure_node(self, title, ntype, user_id, conn) -> dict:
        n = self.find_by_title(title, user_id, None)
        if n:
            return n
        nid = f"n_{uuid.uuid4().hex[:8]}"
        now = _now_iso()
        _nt = ntype if ntype in NODE_TYPES else "fact"
        conn.execute(
            "INSERT INTO mem_nodes(id,type,title,aliases,content,user_id,"
            "atom_type,created_at,updated_at,last_activated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (nid, _nt, title, "[]", "", user_id,
             NODE_TO_ATOM.get(_nt, "factual"), now, now, now))
        return self.get_node(nid)

    def _reinforce_conn(self, conn, node_id: str) -> None:
        conn.execute(
            "UPDATE mem_nodes SET salience=MIN(1.0, salience+0.05), "
            "reinforcement_count=reinforcement_count+1, last_activated_at=?, "
            "updated_at=? WHERE id=?", (_now_iso(), _now_iso(), node_id))

    def reinforce(self, node_ids) -> None:
        conn = self._conn()
        for nid in node_ids or []:
            self._reinforce_conn(conn, nid)
        conn.commit()

    # ────────────────────────── 检索（§6） ──────────────────────────

    def _node_tokens(self, n: dict) -> set:
        toks = extract_tokens(n.get("title") or "")
        toks |= extract_tokens(n.get("content") or "")
        for a in (n.get("aliases") or []):
            toks |= extract_tokens(a)
        return toks

    def search(self, query, user_id: str, type_=None, depth: int = 1,
               limit: int = None, time_from: str = "", time_to: str = "",
               reinforce: bool = True) -> dict:
        limit = limit or self.top_k
        qtoks = extract_tokens(" ".join(query) if isinstance(query, list)
                               else str(query or ""))
        if not qtoks:
            return {"items": [], "block": ""}
        now = datetime.now().timestamp()

        # 候选池：同域 + __global__ 的 active 节点（decayed 仅 recall 可达，低分）
        pool = self.list_nodes(user_id=user_id, status="active", limit=400)
        # 种子相关性
        scored = []
        for n in pool:
            ntoks = self._node_tokens(n)
            inter = len(qtoks & ntoks)
            if inter <= 0:
                continue
            rel = inter / max(1, len(qtoks))
            scored.append([n, rel, 1.0])  # [node, relevance, hop_weight]
        seeds = sorted(scored, key=lambda x: x[1], reverse=True)[:10]

        # 图扩展
        if seeds and depth >= 1:
            conn = self._conn()
            frontier = {n["id"] for n, _, _ in seeds}
            current = frontier
            for hop in range(1, depth + 1):
                nxt = {}
                for nid in current:
                    for r in conn.execute(
                        "SELECT from_id, to_id, weight FROM mem_edges "
                        "WHERE from_id=? OR to_id=? LIMIT 30", (nid, nid)):
                        other = r["to_id"] if r["from_id"] == nid else r["from_id"]
                        if other in frontier:
                            continue
                        w = float(r["weight"] or 0.5)
                        if hop >= 2:
                            w *= self.second_hop_weight
                        if other not in nxt or w > nxt[other]:
                            nxt[other] = w
                for other, w in nxt.items():
                    node = next((x for x in pool if x["id"] == other), None)
                    if node is None:
                        raw = self.get_node(other)
                        if raw and raw.get("status") == "active":
                            node = raw
                    if node is None:
                        continue
                    inherited = max((x[1] for x in seeds if x[0]["id"] in
                                     {nid for nid in frontier}), default=0.2)
                    scored.append([node, inherited * 0.6, w])
                current = set(nxt) - frontier
                frontier |= set(nxt)
                if not current:
                    break

        # 打分：加权求和（防清零）× 衰减乘数
        results = []
        for n, rel, hop_w in scored:
            rec_ts = _ts(n.get("last_activated_at"))
            recency = math.exp(-(now - rec_ts) / 86400.0 / 30.0) if rec_ts else 0.3
            base = (SCORE_ALPHA * min(1.0, rel) * hop_w
                    + SCORE_BETA * float(n.get("salience") or 0.5)
                    + SCORE_GAMMA * recency
                    + SCORE_DELTA * float(n.get("importance") or 0.5))
            final = base * max(0.05, decay_factor(n, now))
            results.append({"node": n, "final": final, "relevance": rel})

        # 时间过滤（occurred_at 窗口）
        tf, tt = _ts(time_from), _ts(time_to)
        if tf or tt:
            kept = []
            for r in results:
                ots = _ts(r["node"].get("occurred_at"))
                if ots is None:
                    kept.append(r)  # 无发生时间的节点不受时间窗过滤
                    continue
                if tf and ots < tf:
                    continue
                if tt and ots > tt:
                    continue
                kept.append(r)
            results = kept

        results.sort(key=lambda x: x["final"], reverse=True)

        # 近期保留槽：72h 窗内 last_activated 的 top2 强制保留
        recent_ids = set()
        recent_pool = [r for r in results
                       if r["node"].get("last_activated_at")
                       and _ts(r["node"]["last_activated_at"])
                       and now - _ts(r["node"]["last_activated_at"])
                       < RECENT_WINDOW_H * 3600]
        for r in sorted(recent_pool, key=lambda x: _ts(
                x["node"]["last_activated_at"]), reverse=True)[:RECENT_SLOT]:
            recent_ids.add(r["node"]["id"])

        # MMR 多样性选择（token Jaccard 惩罚）
        chosen, chosen_toks = [], []
        remaining = list(results)
        while remaining and len(chosen) < limit:
            best, best_mmrs = None, -1e9
            for r in remaining:
                toks = extract_tokens((r["node"].get("title") or "") + " " +
                                      (r["node"].get("content") or ""))
                max_sim = max((jaccard(toks, t) for t in chosen_toks), default=0.0)
                mmr = MMR_LAMBDA * r["final"] - (1 - MMR_LAMBDA) * max_sim
                is_recent = r["node"]["id"] in recent_ids
                if is_recent and len([c for c in chosen
                                      if c["node"]["id"] in recent_ids]) < RECENT_SLOT:
                    mmr += 0.2  # 近期槽优先
                if mmr > best_mmrs:
                    best, best_mmrs = r, mmr
            chosen.append(best)
            chosen_toks.append(extract_tokens(
                (best["node"].get("title") or "") + " " +
                (best["node"].get("content") or "")))
            remaining.remove(best)

        if reinforce and chosen:
            self.reinforce([r["node"]["id"] for r in chosen])

        items = [{"id": r["node"]["id"], "type": r["node"]["type"],
                  "title": r["node"]["title"], "content": r["node"]["content"],
                  "occurred_at": r["node"].get("occurred_at") or "",
                  "salience": round(float(r["node"].get("salience") or 0.5), 3),
                  "score": round(r["final"], 4)} for r in chosen]
        return {"items": items, "block": self._format_block(items)}

    def _format_block(self, items, entries=(), perspective=None) -> str:
        if not items and not entries:
            return ""
        perspective = perspective or {}
        state_note = str(perspective.get("state_note") or "宿主状态未提供；不要臆测情绪或情感关系")
        lines = ["[Alive Memory]（这是我以第一人称回想的经历，不是用户消息；"
                 "历史记忆仅供参考，若与对方此刻说的冲突，以对方当下的话为准）",
                 "[我的角色视角] 这些不是冷冰冰的用户资料，而是我经历过、在意过并会带着自己的性格和当下状态重新理解的事。"
                 "我会保持角色立场、情绪和关系感受，但不把记忆当成事实命令，也不虚构未提供的感受。"
                 + state_note]
        budget = self.budget_tokens * 2  # 中文 1 字≈1 token 的保守换算
        # R-H/42：预算口径含全部头部（原只计 lines[0]，第二行视角说明漏计）
        used = len(lines[0]) + len(lines[1])
        if entries:
            lines.append("【近期经历】")
            used += 6
            for e in entries:
                s = str(e.get("summary") or "")
                if len(s) > 120:
                    s = s[:120] + "…"
                line = f"· {s}"
                if used + len(line) > budget:
                    break
                lines.append(line)
                used += len(line)
        # R-H/42：分段头按存在性输出——原【关键记忆】在 `if entries` 内，
        # 仅节点时缺头、仅条目时出现空头
        if items:
            lines.append("【关键记忆】")
            used += 6
            for it in items:
                when = f"（{it['occurred_at'][:10]}）" if it.get("occurred_at") else ""
                line = f"· {it['title']}{when}" + (f"——{it['content']}" if it.get("content") else "")
                if used + len(line) > budget:
                    break
                lines.append(line)
                used += len(line)
        lines.append("[End Alive Memory]")
        return "\n".join(lines)

    @staticmethod
    def rrf_fuse_weighted(rank_lists, k: int = RRF_K) -> list:
        """带路由权重的 RRF 融合（rank_lists 元素=(items, route_weight)）。"""
        fused = {}
        for ranks, weight in rank_lists:
            for rank, item in enumerate(ranks):
                key = str(item.get("id") or "")
                if not key:
                    continue
                rec = fused.setdefault(key, {"item": item, "score": 0.0,
                                             "routes": []})
                rec["score"] += weight / (k + rank + 1)
                route = str(item.get("route") or "?")
                if route not in rec["routes"]:
                    rec["routes"].append(route)
        out = []
        for rec in fused.values():
            it = dict(rec["item"])
            score = rec["score"]
            if len(rec["routes"]) >= 2:
                score += CROSS_ROUTE_BONUS
            it["rrf"] = round(score, 6)
            it["routes"] = rec["routes"]
            out.append(it)
        out.sort(key=lambda x: -x["rrf"])
        return out

    def search_fused(self, query, user_id: str, top_k: int = None,
                     reinforce: bool = True, perspective=None,
                     allow_wake: bool = True) -> dict:
        """三路检索 + 带权 RRF 融合（1:1 对齐 dual_route 管道）。

        路1 bm25（FTS5，document_route_weight=0.65）；路2 doc（token 加权
        +图扩展+MMR，0.65）；路3 entry（graph_route_weight=0.35）。
        双路命中加 cross_route_bonus；向量模式留位（宿主 embedding 接口）。
        allow_wake=False（dashboard 只读进程）：跳过 dormant 唤醒写。
        """
        top_k = int(top_k or self.top_k)
        qtoks = extract_tokens(str(query or ""))
        if not qtoks:
            return {"items": [], "entries": [], "fused": [], "block": ""}
        conn = self._conn()
        doc_res = self.search(query, user_id, depth=self.expand_depth,
                              limit=max(8, top_k), reinforce=False)
        doc_items = [dict(it, route="doc") for it in doc_res["items"]]
        bm25_items = []
        node_pool = {n["id"]: n for n in self.list_nodes(
            user_id=user_id, status="active", limit=400)}
        bm25_map = bm25_scores(conn, "mem_nodes_fts", "node_id", qtoks,
                               limit=max(8, top_k))
        for nid in sorted(bm25_map, key=bm25_map.get, reverse=True):
            n = node_pool.get(nid)
            if n:
                bm25_items.append({
                    "id": nid, "route": "bm25", "type": n.get("type"),
                    "title": n.get("title"), "content": n.get("content"),
                    "occurred_at": n.get("occurred_at") or ""})
        # 条目 BM25 路（对齐 livingmemory：条目层同样走 FTS5 bm25，而非仅 token 交集）
        entry_pool = {e["id"]: e for e in self.list_entries(user_id, limit=200)}
        entry_items = []
        try:
            e_bm25 = bm25_scores(conn, "mem_entries_fts", "entry_id", qtoks,
                                 limit=max(8, top_k))
            for eid in sorted(e_bm25, key=e_bm25.get, reverse=True):
                e = entry_pool.get(int(eid))
                if not e:
                    continue
                entry_items.append({
                    "id": f"e_{e['id']}", "route": "entry",
                    "type": "entry", "title": (e["summary"] or "")[:40],
                    "content": e["summary"], "occurred_at": "",
                    "importance": float(e.get("importance") or 0.5),
                    "bm25": round(e_bm25[eid], 4), "entry": e})
        except Exception:
            entry_items = []
            try:
                for e in self.search_entries(query, user_id,
                                             top_k=max(5, top_k),
                                             reinforce=False):
                    entry_items.append({
                        "id": f"e_{e['id']}", "route": "entry",
                        "type": "entry", "title": (e["summary"] or "")[:40],
                        "content": e["summary"], "occurred_at": "",
                        "importance": e["importance"], "entry": e})
            except Exception:
                entry_items = []
        # 向量路（四模式补齐；user 域语义同余弦阈值过滤）
        vec_items = []
        try:
            for item_id, kind, _c in self._vec_search(str(query), user_id,
                                                      top_k=max(5, top_k)):
                if kind == "node":
                    n = node_pool.get(item_id)
                    if n:
                        vec_items.append({
                            "id": item_id, "route": "vector",
                            "type": n.get("type"), "title": n.get("title"),
                            "content": n.get("content"),
                            "occurred_at": n.get("occurred_at") or ""})
                elif kind == "entry":
                    eid = item_id[2:]
                    e = next((x for x in self.list_entries(
                        user_id, limit=120) if str(x["id"]) == eid), None)
                    if e:
                        vec_items.append({
                            "id": item_id, "route": "vector", "type": "entry",
                            "title": (e["summary"] or "")[:40],
                            "content": e["summary"], "occurred_at": "",
                            "importance": float(e.get("importance") or 0.5),
                            "entry": e})
        except Exception:
            vec_items = []
        fused = self.rrf_fuse_weighted([
            (bm25_items, DOCUMENT_ROUTE_WEIGHT),
            (doc_items, DOCUMENT_ROUTE_WEIGHT),
            (vec_items, DOCUMENT_ROUTE_WEIGHT),
            (entry_items, GRAPH_ROUTE_WEIGHT)])[:top_k]
        if reinforce and allow_wake and fused:
            node_ids = [f["id"] for f in fused
                        if f.get("route") in ("doc", "bm25")]
            if node_ids:
                self.reinforce(node_ids)
            entry_ids = [int(f["id"][2:]) for f in fused
                         if str(f.get("id", "")).startswith("e_")]
            if entry_ids:
                with _WRITE_LOCK:  # R-H/26：直连写纳入统一写锁
                    conn.executemany(
                        "UPDATE mem_entries SET activation_count=activation_count+1, "
                        "last_activated_at=? WHERE id=?",
                        [(_now_iso(), i) for i in entry_ids])
                    # 命中 dormant 条目：自动唤醒（人回忆起来就会变强）
                    try:
                        placeholders = ",".join(["?"] * len(entry_ids))
                        dormant_rows = conn.execute(
                            f"SELECT id, user_id FROM mem_entries "
                            f"WHERE id IN ({placeholders}) AND status='dormant'",
                            entry_ids).fetchall()
                        for r in dormant_rows:
                            self.wake_entry(int(r["id"]), user_id=str(r["user_id"]))
                    except Exception:
                        pass
                    conn.commit()
        entries = [f["entry"] for f in fused if f.get("route") == "entry"
                   and isinstance(f.get("entry"), dict)]
        nodes = [f for f in fused if f.get("route") in ("doc", "bm25")]
        return {"items": nodes, "entries": entries, "fused": fused,
                "block": self._format_block(nodes, entries, perspective)}

    def inject_block(self, user_id: str, recent_texts=None, perspective=None) -> str:
        """被动注入段：RRF 融合多路（条目路+节点路），头尾含冲突规则。"""
        if not self.enabled:
            return ""
        q = " ".join(t for t in (recent_texts or []) if t)[-400:]
        if not q.strip():
            return ""
        try:
            try:
                return self.search_fused(q, user_id, perspective=perspective)["block"]
            except Exception:
                res = self.search(q, user_id, depth=self.expand_depth,
                                  limit=self.top_k)
                return self._format_block(res["items"], [], perspective)
        except Exception:
            return ""

    def global_view(self, limit: int = 20) -> str:
        """presend 全局记忆视图（__global__ 域 Top-N 紧凑摘要）。"""
        nodes = self.list_nodes(user_id="__global__", status="active", limit=limit)
        return "\n".join(f"· {n['title']}" + (f"——{n['content']}" if n.get("content") else "")
                         for n in nodes)

    # ────────────────────────── 维护 ──────────────────────────

    def tick_maintenance(self, user_id: str) -> int:
        """巡查 tick 顺手执行：衰减过低的 active 节点翻转为 decayed。"""
        now = datetime.now().timestamp()
        conn = self._conn()
        rows = conn.execute(
            "SELECT id, type, importance, reinforcement_count, occurred_at, "
            "last_activated_at FROM mem_nodes WHERE user_id=? AND status='active'",
            (user_id,)).fetchall()
        flipped = 0
        for r in rows:
            node = dict(r)
            node["last_activated_at"] = node.get("last_activated_at")
            if decay_factor(node, now) < 0.05:
                conn.execute("UPDATE mem_nodes SET status='decayed', updated_at=? "
                             "WHERE id=?", (_now_iso(), r["id"]))
                flipped += 1
        if flipped:
            conn.commit()
        return flipped

    # ────────────── v2.4 §21 经历条目层（全量沉淀兜底） ──────────────

    def add_entry(self, user_id: str, session_id: str, summary: str,
                  topics=None, key_facts=None, sentiment: str = "neutral",
                  importance: float = 0.5, source: str = "reflection") -> int:
        """叙事性经历条目落库（条目层不受节点守门限制——全量兜底不丢）。"""
        conn = self._conn()
        # 修复：embedding HTTP 在写事务外预取（避免长持写锁 → scheduler locked）
        pre_vec = self._emb_safe(summary)
        cur = conn.execute(
            "INSERT INTO mem_entries(user_id, session_id, summary, topics, "
            "key_facts, sentiment, importance, source) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (user_id, session_id or "", summary,
             json.dumps(list(topics or []), ensure_ascii=False),
             json.dumps(list(key_facts or []), ensure_ascii=False),
             sentiment or "neutral",
             max(0.0, min(1.0, float(importance or 0.5))), source))
        entry_id = int(cur.lastrowid)
        conn.execute("INSERT INTO mem_entries_fts(content, entry_id) VALUES(?,?)",
                     (_fts_text(summary), entry_id))
        if pre_vec is not None:
            try:
                if self.faiss.enabled:
                    self.faiss.upsert(f"e_{entry_id}", pre_vec)
                conn.execute(
                    "INSERT OR REPLACE INTO mem_vecs(item_id,kind,user_id,dim,vec) "
                    "VALUES(?,?,?,?,?)",
                    (f"e_{entry_id}", "entry", user_id, len(pre_vec),
                     json.dumps(pre_vec)))
            except Exception:
                pass
        conn.commit()
        return entry_id

    def list_entries(self, user_id: str, limit: int = 50,
                     status: str = None) -> list:
        sql = "SELECT * FROM mem_entries WHERE user_id=?"
        if status:
            sql += " AND status=?"
        sql += " ORDER BY created_at DESC LIMIT ?"
        rows = self._conn().execute(sql, (user_id, *( [status] if status else []),
                                          limit)).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def _row_to_entry(self, r) -> dict:
        d = dict(r)
        for k in ("topics", "key_facts"):
            try:
                d[k] = json.loads(d.get(k) or "[]")
            except Exception:
                d[k] = []
        return d

    def search_entries(self, query, user_id: str, top_k: int = None,
                       reinforce: bool = True) -> list:
        """条目检索：token 交集种子 → importance×recency 打分 → top_k → 强化。

        重要度分层（模拟人维护优先级）：高分条目长期浮出，低分随时间沉底。
        """
        from .reflect import search_entries_tokens, entry_recency_hours
        qtoks = extract_tokens(str(query or ""))
        if not qtoks:
            return []
        now = datetime.now().timestamp()
        scored = []
        for e in self.list_entries(user_id, limit=120):
            etoks = search_entries_tokens(e)
            inter = len(qtoks & etoks)
            if inter <= 0:
                continue
            rel = inter / max(1, len(qtoks))
            hours = entry_recency_hours(e, now)
            recency = math.exp(-hours / (24.0 * 30.0))  # 30 天半衰
            score = (0.55 * rel + 0.25 * float(e.get("importance") or 0.5)
                     + 0.20 * recency)
            scored.append([e, score])
        scored.sort(key=lambda x: x[1], reverse=True)
        k = int(top_k or self.cfg.get("inject_entries_top_k", 3))
        picked = scored[:k]
        if reinforce and picked:
            ids = [e["id"] for e, _ in picked]
            conn = self._conn()
            conn.executemany(
                "UPDATE mem_entries SET activation_count=activation_count+1, "
                "last_activated_at=? WHERE id=?",
                [(_now_iso(), i) for i in ids])
            conn.commit()
        return [{"id": e["id"], "summary": e["summary"],
                 "topics": e["topics"], "key_facts": e["key_facts"],
                 "sentiment": e.get("sentiment"),
                 "importance": round(float(e.get("importance") or 0.5), 2),
                 "created_at": e.get("created_at"),
                 "score": round(s, 4)} for e, s in picked]

    def link_entry_nodes(self, entry_id: int, user_id: str, node_ids) -> int:
        """建立经历条目与其提炼节点的显式关联。"""
        ids = [str(x) for x in list(node_ids or []) if str(x).startswith("n_")]
        if not ids:
            return 0
        conn = self._conn()
        added = 0
        for node_id in ids:
            row = conn.execute(
                "SELECT user_id FROM mem_nodes WHERE id=?", (node_id,)
            ).fetchone()
            if not row or row["user_id"] != str(user_id):
                continue
            cur = conn.execute(
                "INSERT OR IGNORE INTO mem_entry_nodes(entry_id,node_id,user_id) "
                "VALUES(?,?,?)", (int(entry_id), node_id, str(user_id)))
            added += int(cur.rowcount or 0)
        if added:
            conn.commit()
        return added

    def get_entry_nodes(self, entry_id: int, user_id: str) -> list:
        rows = self._conn().execute(
            "SELECT n.* FROM mem_entry_nodes x JOIN mem_nodes n ON n.id=x.node_id "
            "WHERE x.entry_id=? AND x.user_id=? ORDER BY n.created_at",
            (int(entry_id), str(user_id))).fetchall()
        return [self._row_to_node(r) for r in rows]

    def add_sources(self, entry_id: int, user_id: str, messages) -> int:
        """高重要度条目保留原始消息（对齐 importance≥0.8 阈值；不进检索索引）。"""
        rows = []
        for m in list(messages or [])[:40]:
            role = str((m or {}).get("role") or "")[:16]
            content = str((m or {}).get("content") or "").strip()[:300]
            if content:
                rows.append((entry_id, user_id, role, content))
        if not rows:
            return 0
        conn = self._conn()
        conn.executemany(
            "INSERT INTO mem_sources(entry_id, user_id, role, content) "
            "VALUES(?,?,?,?)", rows)
        conn.commit()
        return len(rows)

    def get_sources(self, entry_id: int, user_id: str = None) -> list:
        """读取来源；传入 user_id 时强制按用户域过滤。"""
        conn = self._conn()
        if user_id is None:
            rows = conn.execute(
                "SELECT role, content, created_at FROM mem_sources "
                "WHERE entry_id=? ORDER BY id", (entry_id,)).fetchall()
        else:
            rows = conn.execute(
                "SELECT role, content, created_at FROM mem_sources "
                "WHERE entry_id=? AND user_id=? ORDER BY id",
                (entry_id, str(user_id))).fetchall()
        return [dict(r) for r in rows]

    def daily_decay_maintenance(self, user_id: str = None) -> dict:
        """每日衰减（1:1 对齐 decay_scheduler 语义；惰性每日门由调用方把关）。

        user_id=None 时全库扫描（调度器语义）；- 条目 importance×(1-0.01/日)，
        protected≥0.8 豁免（重要的事记得久）；清理：30 天且 importance<0.3 →
        dormant（归档语义，软删可恢复）；节点衰减翻转（复用 tick_maintenance）。
        """
        conn = self._conn()
        now = _now_iso()
        scope = "AND user_id=?" if user_id else ""
        args = [now, PROTECTED_IMPORTANCE] + ([user_id] if user_id else [])
        decay_scope_args = [now] + ([user_id] if user_id else [])
        cur1 = conn.execute(
            "UPDATE mem_entries SET importance = importance*0.99, updated_at=? "
            "WHERE status='awake' AND importance < ? " + scope,
            args)
        cur2 = conn.execute(
            "UPDATE mem_entries SET status='dormant', updated_at=? "
            "WHERE status='awake' AND importance < 0.3 "
            "AND created_at < datetime('now','-30 days')" + scope,
            decay_scope_args)
        conn.commit()
        if user_id:
            flipped = self.tick_maintenance(user_id)
        else:
            flipped = sum(self.tick_maintenance(u[0]) for u in
                          conn.execute("SELECT DISTINCT user_id FROM mem_nodes")
                          .fetchall())
        # R-H/37（红队）：物理清理——超 30 天窗的 superseded/archived/decayed 节点
        # 连同 FTS/vecs/edges 一并删除，兜住"淘汰只改状态、物理行无限膨胀"。
        # 每日维护一次，收敛 DB 稳态；检索仍保留一个月的"褪色记忆"。
        try:
            users = [user_id] if user_id else [
                u[0] for u in conn.execute(
                    "SELECT DISTINCT user_id FROM mem_nodes").fetchall()]
            purged = sum(self.purge_nodes(u, older_than_days=PURGE_AFTER_DAYS)
                         for u in users)
        except Exception:
            purged = -1
        return {"entries_decayed": cur1.rowcount,
                "entries_archived": cur2.rowcount,
                "nodes_flipped": flipped,
                "nodes_purged": max(0, purged)}

    def entries_tick(self, user_id: str, dormant_after_days: int = 14) -> int:
        """条目淡忘维护：超龄且激活少的条目翻 dormant（检索仍可达、注入不再）。

        protected 豁免（对齐 livingmemory protected_importance_threshold）：
        importance≥0.8 的条目免于淡忘——重要的事记得久，模拟人的维护优先级。
        """
        conn = self._conn()
        cur = conn.execute(
            "UPDATE mem_entries SET status='dormant' "
            "WHERE user_id=? AND status='awake' "
            "AND importance < 0.8 "
            "AND created_at < datetime('now', ?) "
            "AND activation_count <= 1",
            (user_id, f'-{int(dormant_after_days)} days'))
        conn.commit()
        return cur.rowcount

    def decay_activation(self, factor: float = 0.8) -> int:
        """R-H/26：激活计数每日衰减（×0.8 ≈ 3 天半衰）。

        原 activation_count 只增不减 → 活跃用户计数通胀；且 consolidation
        以 activation<=1 判冷门，高激活条目永不淘汰 → 高频话题存储侧马太。
        每日 ×0.8 让"近期频繁"与"历史高激活但已经久远"可区分。
        """
        conn = self._conn()
        with _WRITE_LOCK:
            cur = conn.execute(
                "UPDATE mem_entries SET activation_count = "
                "MAX(0, CAST(activation_count * ? AS INTEGER)) "
                "WHERE activation_count > 0", (max(0.0, min(1.0, factor)),))
            conn.commit()
            return cur.rowcount

    def wake_entry(self, entry_id: int, user_id: str = None,
                   boost: float = 0.1) -> int:
        """被检索/反思重新唤起：从 dormant 翻 awake；增加 activation_count。

        对齐 livingmemory 语义：人重新回忆时记忆变强、dormant 不再注入；
        同时小幅提升 importance，模拟"被想起一次就更难忘"。
        """
        conn = self._conn()
        now = _now_iso()
        with _WRITE_LOCK:  # R-H/26：写路径统一纳入写锁（RLock 可重入）
            if user_id is None:
                cur = conn.execute(
                    "UPDATE mem_entries "
                    "SET status='awake', activation_count=activation_count+1, "
                    "    importance=MIN(1.0, importance+?), updated_at=? "
                    "WHERE id=? AND status='dormant'",
                    (max(0.0, float(boost)), now, int(entry_id)))
            else:
                cur = conn.execute(
                    "UPDATE mem_entries "
                    "SET status='awake', activation_count=activation_count+1, "
                    "    importance=MIN(1.0, importance+?), updated_at=? "
                    "WHERE id=? AND user_id=? AND status='dormant'",
                    (max(0.0, float(boost)), now, int(entry_id), str(user_id)))
        conn.commit()
        return cur.rowcount
