# -*- coding: utf-8 -*-
"""memory.reflect — v2.4 §21 经历记忆层：反思流（对话 → 叙事条目 → 择优节点）。

对齐 livingmemory 的反思/概括设计思想（第一人称叙事+重要度评分+相对时间
换算+昵称规则），代码独立重写（AGPL 思想参考 / MIT 独立实现）。

分层沉淀：**条目层（mem_entries）全量兜底不丢**——日常流水也入库，低重要度
靠 TTL 自然淡忘；**节点层（mem_nodes）守门择优不滥**——key_facts 经规则
分类+守门层（时间绑定/去重/容量）落地。上下文压缩后由两层共同兜底记忆。
"""
import json
import re
import time
from datetime import datetime

from .normalize import extract_tokens

# ── 规则分类器（对齐 atom_classifier 思想，零 LLM 开销） ──

# 动作/计划词（时间+动作 → 约定/计划）
_ACTION_RE = re.compile(
    r"要去|要去|打算|准备|计划|约定|约好|约了|答应|提醒|办卡|搬家|开会|"
    r"参加|见面|碰头|出发|回来|休息|生日|纪念日|考试|面试")
# 偏好词（→ person 型"喜好"）
_PREF_RE = re.compile(
    r"喜欢|讨厌|爱吃|爱吃|爱喝|最爱|偏爱|热衷|沉迷|不喜欢|讨厌吃|偏好")
# 关系/身份词（→ person）
_REL_RE = re.compile(
    r"朋友|同学|同事|家人|亲戚|室友|老板|上司|下属|搭档|队友|邻居|"
    r"情侣|夫妻|哥哥|姐姐|弟弟|妹妹|爸爸|妈妈|爷爷|奶奶|外公|外婆|"
    r"是做|从事|职业|工作于|在.{0,6}上班|学的是|专业是")
# 状态词（→ fact）
_STAT_RE = re.compile(r"是|有|属于|住在|位于|等于|包括|已经|一直|总是")

_DATE_RE = re.compile(r"\d{4}-\d{1,2}-\d{1,2}")
_ENTRY_ID_RE = re.compile(r"\d+")


def extract_date(text: str) -> str:
    """从 key_fact 提取绝对日期（LLM 已按 prompt 把相对时间换算为 YYYY-MM-DD）。"""
    m = _DATE_RE.search(text or "")
    if not m:
        return ""
    try:
        y, mo, d = m.group(0).split("-")
        return "%04d-%02d-%02d" % (int(y), int(mo), int(d))
    except Exception:
        return ""


def classify_key_fact(fact: str):
    """规则分类单条 key_fact → (node_type, atom_type, occurred_at)。

    1:1 对齐 livingmemory atom_classifier 的认知五类（episodic/factual/
    relational/preference/planned）语义：只有解析到绝对日期的才判
    planned（goal）/episodic（event）——守门层时间绑定对节点层依然严格，
    解析不出的内容已由条目层 summary 兜底，不会丢；偏好 → preference；
    关系/职业身份 → relational；状态与兜底 → factual。
    """
    t = (fact or "").strip()
    date = extract_date(t)
    has_date = bool(date)
    has_action = bool(_ACTION_RE.search(t))
    if has_action and has_date:
        return "goal", "planned", date
    if has_date:
        return "event", "episodic", date
    if _PREF_RE.search(t):
        return "person", "preference", ""
    if _REL_RE.search(t):
        return "person", "relational", ""
    if _STAT_RE.search(t):
        return "fact", "factual", ""
    return "fact", "factual", ""


def build_reflection_prompt(uid: str, nickname: str, messages: list) -> str:
    """第一人称回顾 prompt（对齐 livingmemory 概括思想：叙事+评分+时间换算）。"""
    lines = []
    for m in messages:
        role = str(m.get("role") or "")
        content = str(m.get("content") or "").replace("\n", " ")
        if len(content) > 300:
            content = content[:300] + "…"
        if role == "assistant":
            lines.append(f"[我] {content}")
        elif role == "user":
            lines.append(f"[{nickname or uid}] {content}")
    today = time.strftime("%Y-%m-%d")
    return (
        "# 任务\n"
        "以第一人称回顾并概括以下最近对话，生成一条你自己的经历记忆。\n\n"
        f"**当前日期**: {today}\n"
        "**时间要求**: 对话里的相对时间（明天/周六/下个月3号）必须换算成"
        "YYYY-MM-DD 写进记忆；换算不了的保留原说法，不要编日期。\n\n"
        "# 最近对话\n" + "\n".join(lines[-60:]) + "\n\n"
        "# 要求\n"
        "1. summary 用第一人称、带你自己说话的语气描述这次交流（像在回想"
        "刚才发生的事），必须写清楚对方（"
        f"{nickname or uid}" "）说了什么、我回了什么、聊了什么话题、"
        "中间发生的事和值得留意的细节；不要写成第三人称报告。\n"
        "2. topics：聊到的主题词，最多 5 个。\n"
        "3. key_facts：从对话里拆出的具体事实，每条一句话（20 字内），"
        "最多 5 条；带时间的约定要含换算后的日期；"
        f"必须写\"{nickname or uid}\"而不是\"用户\"。\n"
        "4. sentiment：positive/neutral/negative。\n"
        "5. importance：0.0-1.0 这段对话对未来相处的参考价值"
        "（重要约定/身份 0.8+；具体计划 0.6-0.8；日常交流 0.4-0.6；"
        "琐碎寒暄 0.1-0.3）。\n\n"
        "# 输出\n"
        "只输出一个 JSON 对象：\n"
        '{"summary": "...", "topics": ["..."], "key_facts": ["..."],'
        ' "sentiment": "neutral", "importance": 0.5}'
    )


def parse_reflection(text: str) -> dict | None:
    """容错解析反思输出（剥围栏/取最外层大括号/字段校验）。"""
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S).strip()
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        data = json.loads(t[i:j + 1])
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    summary = str(data.get("summary") or "").strip()
    if not summary:
        return None
    out = {
        "summary": summary[:600],
        "topics": [str(x)[:30] for x in (data.get("topics") or [])[:5]
                   if str(x).strip()],
        "key_facts": [str(x)[:80] for x in (data.get("key_facts") or [])[:5]
                      if str(x).strip()],
        "sentiment": str(data.get("sentiment") or "neutral"),
        "importance": _clamp_importance(data.get("importance")),
    }
    return out


def _clamp_importance(v) -> float:
    try:
        f = float(v)
    except Exception:
        return 0.5
    return max(0.0, min(1.0, f))


def land_reflection(store, uid: str, session_id: str, parsed: dict,
                    source: str = "reflection", messages=None) -> dict:
    """条目落库 + key_facts 择优生成节点（守门层照走）。返回统计。

    importance≥0.8 时保留原始消息（mem_sources，可核验/回放；1:1 对齐
    livingmemory 的 memory_sources 语义），不进检索索引。
    """
    entry_id = store.add_entry(
        uid, session_id,
        summary=parsed["summary"],
        topics=parsed["topics"],
        key_facts=parsed["key_facts"],
        sentiment=parsed["sentiment"],
        importance=parsed["importance"],
        source=source)
    if parsed["importance"] >= 0.8 and messages:
        try:
            store.add_sources(entry_id, uid, messages)
        except Exception:
            pass
    stats = {"entry_id": entry_id, "nodes_added": 0, "nodes_updated": 0,
             "nodes_rejected": 0}
    linked_nodes = []
    imp = parsed["importance"]
    for fact in parsed["key_facts"]:
        ntype, atom, occurred_at = classify_key_fact(fact)
        ops = [{"op": "add_node", "type": ntype, "atom_type": atom,
                "title": _fact_title(fact), "content": fact,
                "occurred_at": occurred_at,
                "importance": max(0.35, min(0.9, imp)),
                "confidence": 0.75}]
        try:
            st = store.apply_memory_ops(ops, uid, source=source)
            stats["nodes_added"] += int(st.get("added") or 0)
            stats["nodes_updated"] += int((st.get("updated") or 0)
                                          + (st.get("dedup_reinforced") or 0))
            stats["nodes_rejected"] += int(st.get("rejected_time") or 0) \
                + int(st.get("rejected") or 0)
            node = store.find_by_title(ops[0]["title"], uid)
            if node:
                linked_nodes.append(node["id"])
        except Exception:
            stats["nodes_rejected"] += 1
    try:
        store.link_entry_nodes(entry_id, uid, linked_nodes)
    except Exception:
        pass
    try:
        store.backfill_cooccurrence_edges(user_id=uid, entry_id=entry_id)
    except Exception:
        pass
    return stats


def _fact_title(fact: str):
    """key_fact → 节点标题：取事实主体（去首尾标点，截 16 字）。"""
    t = re.sub(r"[。！？!?\s]+$", "", (fact or "").strip())
    t = re.sub(r"^(对方|他|她|我)说(?:要|的|道)?", "", t)
    return (t[:16] or "记忆") if t else "记忆"


def search_entries_tokens(entry: dict) -> set:
    """条目检索 token 集（summary+topics+key_facts）。"""
    toks = extract_tokens(str(entry.get("summary") or ""))
    try:
        for tp in json.loads(entry.get("topics") or "[]"):
            toks |= extract_tokens(str(tp))
    except Exception:
        pass
    try:
        for kf in json.loads(entry.get("key_facts") or "[]"):
            toks |= extract_tokens(str(kf))
    except Exception:
        pass
    return toks


def entry_recency_hours(entry: dict, now: float = None) -> float:
    """条目年龄（小时，按 created_at ISO 文本）。"""
    if now is None:
        now = time.time()
    try:
        c = datetime.strptime(str(entry.get("created_at") or ""),
                              "%Y-%m-%d %H:%M:%S").timestamp()
        return max(0.0, (now - c) / 3600.0)
    except Exception:
        return 1e9


__all__ = [
    "build_reflection_prompt", "parse_reflection", "classify_key_fact",
    "extract_date", "land_reflection", "search_entries_tokens",
    "entry_recency_hours", "_fact_title",
]
