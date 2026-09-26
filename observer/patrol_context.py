"""Patrol context builder — assembles complete context for the patrol LLM."""

from __future__ import annotations
import json


def build_patrol_prompt(engine, messages: list[dict], user_id: str,
                        stance_review: bool = False) -> str:
    """Build the complete patrol prompt with deep context understanding.

    The patrol LLM receives:
    1. Role definition and task instructions
    2. Current emotional/bond state
    3. Recent conversation (last N messages)
    4. Conversation topic summary
    5. Output format specification

    设计13 §8-I6：stance_review=True 时（约每10巡查周期，与漂移检测同周期搭乘）
    追加社交立场模式回顾附加任务；承诺留意句常驻。
    """
    # Current state
    state = engine.get_state_summary()
    bond = engine.bond.get_all()

    # Recent messages (last 10 turns)
    recent = messages[-20:] if len(messages) > 20 else messages
    conversation_text = _format_conversation(recent)

    # Topic context (last 5 messages for quick topic understanding)
    topic_msgs = messages[-10:] if len(messages) > 10 else messages
    topic_summary = _extract_topic_hint(topic_msgs)

    # 设计13 §8-I6：社交立场模式回顾段（仅漂移检测周期启用，其余周期为空串）
    if stance_review:
        stance_section = (
            "\n## 附加任务：社交立场模式回顾（低频体检）\n"
            "顺带回顾近期对话里 agent 自己的回应模式，是否存在以下失真信号：\n"
            "a) 并没有正忙、也没有冲突，却频繁推脱用户的请求\n"
            'b) 同一款借口（"没电/忙/困"之类）反复使用\n'
            "c) 对关系明显很好的用户持续冷淡或敷衍\n"
            "若存在，在输出 JSON 顶层增加字段（不存在则省略该字段）：\n"
            '  "stance_drift": {"detected": true, "note": "以 agent 第一人称写的一句自省备忘，30字内'
            '（如：最近老拿忙当借口，不太像我）"}\n'
            "不要因此改动其他输出结构。\n"
        )
    else:
        stance_section = ""

    # R15/I2（设计03 §5.1）：用户提及事物识别段（常驻，与事件分析同调用搭乘）
    interest_section = (
        "\n## 附加任务：用户提及的事物（兴趣采集）\n"
        "识别对话中用户提到的**具体事物**（游戏/动漫/作品/名人/活动/食物等）"
        "及用户对其态度。输出 JSON 顶层**必须包含**该字段（用户没有提及具体事物时输出空数组 []）：\n"
        '  "mentioned_interests": [{"name": "归一化名称，10字内，不带书名号/引号", '
        '"attitude": "positive/neutral/negative", "confidence": 0.0-1.0}]\n'
        "只列用户明确表达过兴趣或谈及的具体事物；抽象概念、纯日程安排不算。\n"
    )

    # 升级方案 §7：长期记忆沉淀段（常驻搭乘，宁缺勿滥）
    memory_section = (
        "\n## 附加任务：长期记忆沉淀\n"
        "从对话中识别**有跨会话价值**的信息，在输出 JSON 顶层增加字段"
        "（没有值得记的就输出空数组 []，最多 3 条）：\n"
        '  "memory_ops": [\n'
        '    {"op": "add_node", "type": "person/fact/event/topic/goal", '
        '"title": "归一化名称，10字内", "content": "一句话事实，20字内", '
        '"occurred_at": "YYYY-MM-DD，事件/约定必填（从对话日期与相对时间换算）", '
        '"confidence": 0.0-1.0, "aliases": ["可选别名"], "importance": 0.0-1.0},\n'
        '    {"op": "link", "from": "已有节点标题", "rel": "part_of/causes/relates", '
        '"to": "另一节点标题"}\n'
        "  ]\n"
        "入库判据（宁缺勿滥）：身份事实、稳定偏好、承诺约定、显著事件、重要新人才记；"
        "本轮寒暄、临时细节、正在讨论的过程性内容**不要**记。"
        "注意：confidence 这里是记忆置信度，与上方事件的 0.6 纪律是两个独立标准。"
        "type=emotion 仅用于重大情感里程碑（激烈冲突、和解），日常情绪不要记。\n"
    )

    prompt = f"""你是一个情感分析系统，负责从对话中识别情感事件。

## 你的任务
分析以下对话，识别其中发生的情感事件。你必须先理解对话的整体语境，再判断事件类型。

## 当前状态
- PAD情绪: P={state['pad_p']}, A={state['pad_a']}, D={state['pad_d']}
- 情绪标签: {state['emotion_label']}
- 情感关系: C={bond['c']:.2f}, D_rel={bond['d_rel']:.2f}, I={bond['i']:.2f}, T={bond['t']:.2f}
- 信任创伤状态: {'活跃' if state.get('trauma_active') else '无'}

## 对话主题提示
{topic_summary}

## 近期对话
{conversation_text}

## 分析步骤（必须按顺序执行）
1. 首先理解对话的整体主题和上下文
2. 然后逐条分析用户消息，识别情感事件
3. 特别注意：讽刺、反语、开玩笑等需要根据上下文判断真实意图
4. 注意区分"用户调侃"和"用户真实批评"
5. 留意承诺的作出与兑现：agent 答应稍后做的事、事后是否兑现，都是重要的关系事件

## 可识别的事件类型（必须输出在detected_events中）
正面事件：positive_feedback, encouragement, trust_delegation, shared_interest, deep_collaboration, user_return, task_success, repair_attempt
负面事件：negative_feedback, neglect, trust_violation, task_failure
特殊事件：prolonged_absence（用户长时间不在线>2小时时），interest_enjoyed（Agent做了喜欢的事时）
混合事件：可以同时返回多个事件（如"建议很好但语气太冲"= positive_feedback + negative_feedback）

## user_sentiment 判定标尺（重要，2026-09-06）
user_sentiment 指**用户对我们这段互动/聊天氛围的态度**，不是用户自己处境的好坏：
- 用户遭遇挫折、情绪低落、抱怨生活（"项目黄了""心情糟透了"）——只要 ta 在**主动向你倾诉**，
  说明对互动是信任的，user_sentiment 应判 **neutral 或 positive**，**不要判 negative**；
- 只有用户**对 Agent 本人**表达不满/批评/疏远/冷淡（"你不懂我""别再烦我""你说得不对"）才判 negative；
- 聊天融洽、被安慰、解决问題→ positive；普通寒暄→ neutral。
{stance_section}{interest_section}{memory_section}
## 输出格式（严格JSON）
```json
{{
  "detected_events": [
    {{
      "type": "事件类型",
      "intensity": "mild/moderate/strong",
      "confidence": 0.0-1.0,
      "reason": "判断理由（简短）"
    }}
  ],
  "conversation_topic": "当前对话主题的一句话摘要",
  "user_sentiment": "positive/negative/mixed/neutral",
  "mentioned_interests": [{{"name": "...", "attitude": "positive/neutral/negative", "confidence": 0.0-1.0}}]
}}
```

## 关键规则
- confidence < 0.6的事件不要输出
- 讽刺/反语：如果用户表面正面但语境负面（如"你这么蠢是故意逗我开心吧"），分类为negative_feedback
- 如果对话中没有明显的情感事件，detected_events返回空数组
- 如果用户长时间不在线（从消息时间戳判断），添加prolonged_absence事件
- 不要输出PAD数值变化，只输出事件分类"""

    return prompt


def _format_conversation(messages: list[dict]) -> str:
    """Format messages for patrol context."""
    lines = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if isinstance(content, list):
            content = " ".join(str(c) for c in content)
        if len(content) > 500:
            content = content[:500] + "..."
        prefix = "用户" if role == "user" else "Agent" if role == "assistant" else role
        lines.append(f"[{prefix}]: {content}")
    return "\n".join(lines)


def _extract_topic_hint(messages: list[dict]) -> str:
    """Extract a brief topic hint from recent messages."""
    if not messages:
        return "无对话历史"
    recent_user_msgs = [m.get("content", "") for m in messages[-5:] if m.get("role") == "user"]
    if not recent_user_msgs:
        return "无用户消息"
    combined = " ".join(recent_user_msgs[-3:])
    if len(combined) > 200:
        combined = combined[:200] + "..."
    return f"近期话题: {combined}"


def parse_patrol_response(response_text: str) -> dict:
    """Parse the patrol LLM's JSON response."""
    try:
        # Try to extract JSON from the response
        text = response_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            json_lines = []
            in_json = False
            for line in lines:
                if line.strip().startswith("```json"):
                    in_json = True
                    continue
                if line.strip().startswith("```") and in_json:
                    break
                if in_json:
                    json_lines.append(line)
            text = "\n".join(json_lines)

        data = json.loads(text)
        result = {
            "detected_events": data.get("detected_events", []),
            "topic": data.get("conversation_topic", ""),
            "sentiment": data.get("user_sentiment", "neutral"),
        }
        # 设计13 §8-I6：立场回顾可选字段——旧格式响应无此键，解析不报错
        stance = data.get("stance_drift")
        if isinstance(stance, dict):
            result["stance_drift"] = {
                "detected": bool(stance.get("detected")),
                "note": str(stance.get("note") or ""),
            }
        else:
            result["stance_drift"] = {"detected": False, "note": ""}
        # R15/I2：兴趣采集可选键——旧格式响应无此键时为空表
        mi = data.get("mentioned_interests")
        result["mentioned_interests"] = [x for x in mi if isinstance(x, dict)] \
            if isinstance(mi, list) else []

        # 升级方案 §7：memory_ops 解析（顶层可选字段，缺失/非列表一律空处理）
        mops = data.get("memory_ops")
        result["memory_ops"] = [x for x in mops if isinstance(x, dict)] \
            if isinstance(mops, list) else []
        return result
    except (json.JSONDecodeError, Exception):
        return {"detected_events": [], "topic": "", "sentiment": "neutral"}
