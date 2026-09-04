"""Core engine coordinator — LLM judgment + constraint validation.

职责边界（设计11，最新权威）：
- 精力系统：只控制自唤醒时间和连续工作时间（唤醒→耗尽→休息→回满→再唤醒）
- 压力系统：只负责决定干什么（工作 vs 休闲），工作时增压、休闲时减压
- 夜间作息（clock）：与精力完全解耦，睡眠刷新精力但不等同能量小憩
"""
from __future__ import annotations
import json
import time as _time
from datetime import datetime
from .clock import ClockManager, ClockPhase
from .energy import EnergyManager
from .stress import StressManager, StressMode
from .emotion import EmotionEngine
from .bond import BondManager
from .boredom import BoredomManager
from .self_wake import SelfWakeManager
from .drive import DriveManager
from .config import AliveConfig, load_config
from .constants import CONSTRAINTS, apply_constraints

_DEFAULT_USER = "__global__"
_current_user_id = _DEFAULT_USER





class AliveEngine:
    def __init__(self, config_fn, state_get, state_set, db):
        global _current_user_id
        self.cfg = load_config(config_fn)
        self.db = db
        self.clock = ClockManager(self.cfg.clock, state_get, state_set)
        self.energy = EnergyManager(self.cfg.energy, state_get, state_set)
        self.stress = StressManager(self.cfg.stress, state_get, state_set)
        self.emotion = EmotionEngine(self.cfg.emotion, state_get, state_set)
        self.bond = BondManager(self.cfg.bond, state_get, state_set, db)
        self.boredom = BoredomManager(self.cfg.boredom, state_get, state_set)
        self.self_wake = SelfWakeManager(self.cfg.self_wake, state_get, state_set)
        self.drive = DriveManager(self.cfg.drive, state_get, state_set)
        self._per_user_last_tick: dict[str, float] = {}  # 按用户节流：scheduler 逐用户
        # tick，共享单值会互相拦截（第一个用户 tick 后其余全被60s节流吞掉）
        self._phys_last_tick = 0.0  # 生理段全局去重（设计10：单一生命周期，逐用户tick不重复推进）
        self._get_raw = state_get      # (key, default=None, user_id=None)
        self._set_raw = state_set      # (key, value, user_id=None)
        _current_user_id = _DEFAULT_USER
        self._current_user_id = _DEFAULT_USER  # Instance attribute for hook access
        self._is_self_wake: bool = False
        self._init_defaults()

    def set_user(self, user_id: str):
        global _current_user_id
        _current_user_id = user_id
        self._current_user_id = user_id

    def _raw_state_get(self, key: str, user_id: str | None = None):
        """按 (key, user_id) 形态读取；无值返回 None。"""
        return self._get_raw(key, None, user_id or self._current_user_id)

    def _raw_state_set(self, key: str, value, user_id: str | None = None) -> None:
        self._set_raw(key, value, user_id or self._current_user_id)

    def _init_defaults(self):
        defaults = {
            "energy": self.cfg.energy.initial,
            "stress": self.cfg.stress.initial,
            "pad_p": self.cfg.emotion.initial_p,
            "pad_a": self.cfg.emotion.initial_a,
            "pad_d": self.cfg.emotion.initial_d,
            "boredom": self.cfg.boredom.initial,
            "clock_phase": "waking",
            "activity_mode": "working",
        }
        for key, default_val in defaults.items():
            existing = self.db.get_state(key, _DEFAULT_USER)
            if isinstance(default_val, str):
                # 字符串状态键（clock_phase/activity_mode）：存在即不覆盖，
                # 否则每次进程启动都会把LLM决策的activity_mode重置回working
                if existing is None:
                    self._raw_state_set(key, default_val, _DEFAULT_USER)
            elif not isinstance(existing, (int, float)):
                self._raw_state_set(key, default_val, _DEFAULT_USER)

    # ── 每日限额计数器（设计06/09）──

    def _ensure_daily_counters(self) -> None:
        """日期变更时重置当日变化计数器（懒式，按用户）。"""
        today = datetime.now().strftime("%Y-%m-%d")
        last = self._raw_state_get("daily_counter_date", self._current_user_id)
        if last != today:
            self.db.reset_daily_counters(self._current_user_id)
            self._raw_state_set("daily_counter_date", today, self._current_user_id)

    def _check_daily_limit(self, dim: str, delta: float, limit: float) -> float:
        """裁剪delta使当日累计不超过限额，返回裁剪后的delta。"""
        if abs(delta) < 1e-9:
            return 0.0
        direction = "pos" if delta > 0 else "neg"
        used = self.db.get_daily_counter(dim, direction, self._current_user_id)
        remaining = max(0.0, limit - used)
        allowed = max(-remaining, min(remaining, delta)) if direction == "neg" \
            else min(remaining, delta)
        if abs(allowed) > 1e-9:
            self.db.add_daily_counter(dim, direction, abs(allowed), self._current_user_id)
        return allowed

    def tick(self) -> list[str]:
        events = []
        now = _time.time()
        uid = self._current_user_id
        if now - self._per_user_last_tick.get(uid, 0.0) < 60:
            return events
        self._per_user_last_tick[uid] = now

        # ── per-user：情感/关系衰减、创伤、兴趣热度、队列投递（关系因对话人而异）──
        self._decay_emotional_daily()  # R13/G1：每日一次（原每分钟=设计值的1440倍）
        if self.bond.get_t() < self.cfg.bond.trauma_threshold:
            if not self.bond.is_trauma_active():
                self.bond.trigger_trauma()
                events.append("bond:trauma_triggered")
        self._decay_interest_heat_daily()
        if not self.clock.is_sleeping():
            self._deliver_queued_messages()

        # ── 全局生理：单一生命周期，每分钟只推进一次 ──
        # scheduler 逐用户 tick 都会走到这里，若不去重会把衰减/恢复加速 N 倍；
        # 生理键已在 gs/ss chokepoint 强制 __global__（见插件 __init__.py）。
        if now - self._phys_last_tick < 60:
            return events
        self._phys_last_tick = now
        self._energy_at_tick_start = self.energy.get()

        clock_event = self.clock.tick()
        if clock_event:
            events.append(clock_event)

        phase = self.clock.get_phase()
        resting = self.self_wake.is_resting()

        if resting and phase != ClockPhase.SLEEPING:
            # ── 能量小憩：精力恢复（设计01：与夜间睡眠解耦）──
            self.energy.recover_rest(1.0)
            # 修复#1：小憩是休闲态，压力应按休闲速率下降，不再按 working 涨
            self.stress.set(self.stress.get() - self.cfg.stress.decrease_idle)
            self.stress.decay_frustration(1.0)
            self.boredom.tick_resting(1.0)
            if self.energy.can_self_wake():
                self.self_wake.end_rest()
                events.append("self_wake:ready")
        elif phase == ClockPhase.SLEEPING:
            # ── 夜间睡眠：精力恢复（睡眠刷新，衰减×0），压力按睡眠速率下降 ──
            self.energy.recover_rest(1.0)
            self.stress.set(self.stress.get() - self.cfg.stress.decrease_sleep)
            if self.self_wake.is_resting():
                self.self_wake.end_rest()
        else:
            # ── 清醒：精力按工作/休闲速率×相位倍率衰减 ──
            multiplier = self.clock.get_phase_multiplier()
            self.energy.tick(self.stress.get_mode(), multiplier)
            # 压力：工作时增加，休闲时减小（情感调制取本分钟上下文用户的 PAD；
            # scheduler 已把主用户排在最前，正常推进均发生在主用户上下文）
            self.stress.tick(self.emotion.get_p(), self.emotion.get_a())
            # R12/D5（设计14 §3.2）：清醒休闲=低挑战代理，无聊度按配置速率上升
            if self.stress.get_mode() == StressMode.LEISURE:
                self.boredom.tick_waking(1.0)
            # 压力系统决定干什么（返回决策点事件供提示词注入）
            stress_event = self.stress.check_mode_switch()
            if stress_event:
                # 修复#3：stress≥95 硬切原本无声，补事件留痕便于追溯
                if stress_event == "stress:leisure_hard":
                    self.db.log_event("stress_hard_limit", "engine", uid,
                                     json.dumps({"stress": self.stress.get()}))
                events.append(stress_event)
            # 精力只控制唤醒/休息：耗尽→进入能量小憩（不是夜间睡眠！）
            if self.energy.is_depleted() and not resting:
                self.self_wake.start_rest()
                events.append("energy:rest_started")
                self.db.log_event("rest_started", "engine", uid,
                                  json.dumps({"reason": "energy_depleted"}))

        # 设计14：内在驱动力发起检查（仅在清醒非休息相位）
        drive_event = self._check_drive_initiate()
        if drive_event:
            events.append(drive_event)

        self._save_snapshot()
        return events

    def _check_drive_initiate(self) -> "str | None":
        """设计14 内在驱动力发起门控（纯规则布尔，LLM 决定做什么）。
        与能量满 self_wake 路径互斥。"""
        if self.clock.is_sleeping() or self.clock.is_winding_down():
            return None
        if self.self_wake.is_resting():
            return None
        if not getattr(self.cfg, "drive", None) or not self.cfg.drive.enabled:
            return None
        ok, reason = self.drive.should_initiate(
            phase=self.clock.get_phase(),
            sleeping=self.clock.is_sleeping(),
            winding_down=self.clock.is_winding_down(),
            resting=self.self_wake.is_resting(),
            energy=self._energy_at_tick_start,
            energy_full_threshold=self.cfg.energy.self_wake_threshold,
            boredom=self.boredom.get(),
        )
        if not ok:
            # R13/G6：日上限拒绝留痕，便于观察节律生效情况
            if reason == "daily_max":
                self.db.log_event("drive_daily_capped", "engine",
                                  self._current_user_id, "{}")
            return None
        self.drive.mark_initiated()
        self.db.log_event("drive_initiated", "engine", self._current_user_id,
                          json.dumps({"reason": reason,
                                      "boredom": round(self.boredom.get(), 2),
                                      "energy": round(self.energy.get(), 2)}))
        return "drive:initiate"

    def _decay_emotional_daily(self) -> None:
        """R13/G1（设计01b §2.5.5）：PAD/bond 向初值的对数衰减按"每天 0.005"
        结算——此前挂在每分钟 tick 上，半衰期从 139 天缩到 2.3 小时，
        两周互动后所有人关系值被抹回初始（实锤 pad_a≈9e-11）。"""
        today = datetime.now().strftime("%Y-%m-%d")
        if self._raw_state_get("last_decay_date", self._current_user_id) == today:
            return
        self.emotion.tick_decay()
        self.bond.tick_decay()
        self._raw_state_set("last_decay_date", today, self._current_user_id)

    def _decay_interest_heat_daily(self) -> None:
        # R15/I1（设计06 §3.3 无用户维）：兴趣库全局唯一——衰减对象与幂等标记
        # 统一 __global__，与巡查采集、独白取材同源。
        today = datetime.now().strftime("%Y-%m-%d")
        if self._raw_state_get("interest_heat_decay_date", "__global__") == today:
            return
        try:
            base = self.cfg.hobby.heat_daily_decay
            for item in self.db.get_interests(active_only=True, user_id="__global__"):
                heat = float(item.get("heat") or 50.0)
                # R15/I4（设计03 §3.3）：按感兴趣程度调衰减速度，负面态度额外 ×2
                il = float(item.get("interest_level") or 0.5)
                if il > 0.8:
                    mult = 0.3
                elif il >= 0.5:
                    mult = 1.0
                elif il >= 0.3:
                    mult = 2.0
                elif il >= 0.1:
                    mult = 3.0
                else:
                    mult = 5.0
                if float(item.get("attitude") or 0.0) < 0:
                    mult *= 2.0
                item["heat"] = max(0.0, heat - base * mult)
                self.db.upsert_interest(item)
            self._raw_state_set("interest_heat_decay_date", today, "__global__")
        except Exception:
            pass

    def _heat_bump_top(self, delta: float, on_experience: bool = False) -> None:
        """R15/I3（设计03 §3.4/§5.3）：兴趣事件命中时热度回升。

        事件不带条目名，取当前热度 Top1 启发式；封顶 100，表空静默跳过。
        """
        try:
            tops = self.db.get_interests(active_only=True, user_id="__global__")
            if not tops:
                return
            item = tops[0]
            item["heat"] = min(100.0, float(item.get("heat") or 50.0) + delta)
            if on_experience:
                item["times_experienced"] = int(item.get("times_experienced") or 0) + 1
            self.db.upsert_interest(item)
        except Exception:
            pass

    def _deliver_queued_messages(self) -> None:
        """醒后投递睡眠期间排队的消息（写入state供注入读取）。

        发现#9：queue_message 以用户 id 为 sender 入队（user_id, user_message），
        但原实现把全部未投递消息塞进当前用户 wake_pending，导致 A 的消息被
        投递到 B 的 wake_pending（跨用户泄漏）。此处按 sender==当前用户 过滤。
        """
        queued = [m for m in self.db.get_queued_messages(delivered=False)
                  if m.get("sender") == self._current_user_id]
        if not queued:
            return
        pending = self._raw_state_get("wake_pending_messages", self._current_user_id)
        try:
            pending_list = json.loads(pending) if pending else []
        except (TypeError, ValueError):
            pending_list = []
        for m in queued:
            pending_list.append({"sender": m["sender"], "content": m["content"]})
            self.db.mark_delivered(m["id"])
        self._raw_state_set("wake_pending_messages", json.dumps(pending_list, ensure_ascii=False),
                            self._current_user_id)

    def consume_wake_messages(self) -> list[dict]:
        raw = self._raw_state_get("wake_pending_messages", self._current_user_id)
        if not raw:
            return []
        try:
            msgs = json.loads(raw)
        except (TypeError, ValueError):
            msgs = []
        self._raw_state_set("wake_pending_messages", "[]", self._current_user_id)
        return msgs

    # ── 决策点标记落地（75/30决策由LLM做出，经标记写回activity_mode）──

    def handle_mode_marker(self, marker: str) -> bool:
        """处理LLM回复中的切换标记。仅在对应压力区间有效。"""
        s = self.stress.get()
        mode = self.stress.get_mode()
        if marker == "to_leisure":
            if mode == StressMode.WORKING and s >= self.cfg.stress.leisure_decision_threshold:
                self.stress.set_mode(StressMode.LEISURE)
                self.db.log_event("mode_switch", "llm_decision", self._current_user_id,
                                  json.dumps({"to": "leisure", "stress": s}))
                return True
        elif marker == "to_work":
            if mode == StressMode.LEISURE and s <= self.cfg.stress.work_decision_threshold:
                self.stress.set_mode(StressMode.WORKING)
                self.db.log_event("mode_switch", "llm_decision", self._current_user_id,
                                  json.dumps({"to": "working", "stress": s}))
                return True
        return False

    def apply_llm_suggestion(self, pad_changes, bond_changes, confidence, reasoning):
        self._ensure_daily_counters()
        current_state = {
            "confidence": confidence,
            "pad_p": self.emotion.get_p(), "pad_a": self.emotion.get_a(),
            "pad_d": self.emotion.get_d(),
            "bond_c": self.bond.get_c(), "bond_d": self.bond.get_d(),
            "bond_i": self.bond.get_i(), "bond_t": self.bond.get_t(),
            "trauma_active": self.bond.is_trauma_active(),
            "relationship_maturity": self.bond.get_relationship_maturity_multiplier(),
        }
        validated_pad, validated_bond = apply_constraints(
            dict(pad_changes), dict(bond_changes), current_state)

        # 每日限额裁剪（设计09）
        for key in ("p", "a", "d"):
            validated_pad[key] = self._check_daily_limit(
                f"pad_{key}", validated_pad.get(key, 0.0), CONSTRAINTS["pad_daily_limit"])
        limit_map = {"c": "bond_c", "d_rel": "bond_d_rel", "i": "bond_i", "t": "bond_t"}
        for key, dim in limit_map.items():
            validated_bond[key] = self._check_daily_limit(
                dim, validated_bond.get(key, 0.0), CONSTRAINTS["bond_daily_limit"])

        if any(abs(v) > 1e-9 for v in validated_pad.values()):
            self.emotion.apply_delta(
                validated_pad.get("p", 0), validated_pad.get("a", 0), validated_pad.get("d", 0))
        if any(abs(v) > 1e-9 for v in validated_bond.values()):
            self.bond.apply_deltas(
                c=validated_bond.get("c", 0), d_rel=validated_bond.get("d_rel", 0),
                i=validated_bond.get("i", 0), t=validated_bond.get("t", 0))

        self.db.log_event("emotion_update", "patrol", self._current_user_id,
            json.dumps({"pad": validated_pad, "bond": validated_bond,
                        "confidence": confidence, "reasoning": reasoning[:200]}))
        return {"pad": validated_pad, "bond": validated_bond}

    def check_personality_drift(self) -> bool:
        """拟人化漂移检测（设计03）：P持续过高时向基准回调。"""
        p = self.emotion.get_p()
        if p >= CONSTRAINTS["drift_positive_threshold"]:
            self.emotion.apply_delta(-CONSTRAINTS["drift_correction_amount"], 0, 0)
            self.db.log_event("drift_correction", "engine", self._current_user_id,
                              json.dumps({"p_before": p}))
            return True
        return False

    def get_state_summary(self):
        return {
            "clock_phase": self.clock.get_phase(),
            "energy": round(self.energy.get() or 0, 1),
            "energy_label": self.energy.get_energy_label(),
            "resting": self.self_wake.is_resting(),
            "stress": round(self.stress.get() or 0, 1),
            "stress_mode": self.stress.get_mode(),
            "boredom": round(self.boredom.get(), 1),
            "boredom_level": self.boredom.get_level(),
            "pad_p": round(self.emotion.get_p() or 0, 3),
            "pad_a": round(self.emotion.get_a() or 0, 3),
            "pad_d": round(self.emotion.get_d() or 0, 3),
            "emotion_label": self.emotion.get_emotion_label(),
            "bond_c": round(self.bond.get_c() or 0, 3),
            "bond_d": round(self.bond.get_d() or 0, 3),
            "bond_i": round(self.bond.get_i() or 0, 3),
            "bond_t": round(self.bond.get_t() or 0, 3),
            "trauma_active": self.bond.is_trauma_active(),
        }

    def get_prompt_injection(self, user_id=None):
        """构建[Alive System]数据区。

        设计11原则：数据区只提供感知数据（数值+档位标签），不含任何
        "你应该如何"的指令；全部行为引导走第一人称[Alive Reflection]独白。
        """
        parts = []
        parts.append("（以下是我的内部生命状态数据，仅供自我感知，可能略有延迟，以实际感受为准。）")
        # #R3：人设约束锚点——任何回复必须以第一人称"我"为主，禁止角色扮演/动物化叙事
        parts.append("我是 Hermes Alive 系统：一个有作息节律和情绪状态的 AI 拟人伙伴。"
                     "回复里禁止出现动物化叙事（尾巴/爪子/趴窗台/本喵/喵～等），"
                     "也禁止出现第三方视角叙述（如「他/她那边/她」指代用户）。"
                     "始终用第一人称「我」与用户对话。")
        parts.append("还有一点：回复正文里只放我要对对方说的话——『先发个提醒吧』"
                     "『让我看看待办』这类打给自己的小算盘只放在心里，不写进正文；"
                     "要是打算用工具另发一条消息，这条正文就更别复述计划和内容。"
                     "普通聊天消息发不出（点头）（看表）这类动作旁白，直接说就好。")
        # R13/G4：教学条件化——原来每轮无条件教两个记号，区间门 97% 驳回
        # （to_leisure applied 14 / rejected 1206），等于持续诱导读写失败。
        # 只在标记真会被接受的档位教；其余轮明说不用记号。
        _s_now = self.stress.get()
        if self.stress.get_mode() == StressMode.LEISURE and \
                _s_now <= self.cfg.stress.work_decision_threshold:
            parts.append("我现在压力很低，要是处理完了想收心的事、该回去干活了，"
                         "就在回复最末尾给自己留个小记号[[to_work]]。")
        elif self.stress.get_mode() == StressMode.WORKING and \
                _s_now >= self.cfg.stress.leisure_decision_threshold and _s_now < \
                self.cfg.stress.hard_leisure_threshold:
            parts.append("我压力已经挺高了，要是决定了先撂下手头的事歇口气，"
                         "就在回复最末尾给自己留个小记号[[to_leisure]]。")
        else:
            parts.append("歇着还是干活，这会儿由我的状态自己安排，不用给自己留切换记号。")
        parts.append("怎么区分\u201c收心做事\u201d和\u201c闲逛\u201d呢，我心里大概有几杆秤："
                     "有人拜托我、正等着结果的事——不管多小，都是正经事；"
                     "答应过别人的事，哪怕只是随口说\u201c回头给你看看\u201d，也算数；"
                     "自己起意要做、有明确产出的事——要把一样东西查清楚、做出来、整理好——"
                     "动手做的时候就该收心；"
                     "只是随手翻翻、看看热闹、打发时间的，那就算闲逛。"
                     "归根结底不看累不累，看这件事有没有一个\u201c做完的时刻\u201d、有没有人在等它。")

        # 设计13 §8-I1/I7：社交立场段（冲突天平+素材优先级+披露分寸+反模板+deferred引导），
        # 紧跟四杆秤之后；personality 按 SocialConfig 档位选预置文案变体（§8-I2）
        parts.append(self._social_stance_paragraph())

        phase = self.clock.get_phase()
        phase_map = {"waking": "清醒中", "winding_down": "犯困中",
                     "sleeping": "睡眠中", "warming_up": "刚睡醒"}
        parts.append(f"当前阶段：{phase_map.get(phase, phase)}")
        # 发现#11：注入层原本缺失绝对日期，模型对「明早/后天」等跨日表达
        # 全靠猜→日期系统性错。这里提供权威锚点（数据区，仅感知）。
        _now = datetime.now()
        _wd = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][_now.weekday()]
        parts.append(f"当前真实日期时间：{_now.strftime('%Y-%m-%d %H:%M')} {_wd}")
        if self.self_wake.is_resting():
            parts.append("当前状态：能量小憩中（休息恢复精力）")
        mode_label = "工作中" if self.stress.get_mode() == "working" else "休闲中"
        parts.append(f"活动模式：{mode_label}")
        parts.append(f"精力：{self.energy.get() or 0:.0f}/100（{self.energy.get_energy_label()}）")
        parts.append(f"压力：{self.stress.get() or 0:.0f}/100")
        parts.append(f"无聊度：{self.boredom.get():.0f}/100")
        drive_line = self.drive.signal_text() if getattr(self, "drive", None) else ""
        if drive_line:
            parts.append(drive_line)
        parts.append(self.emotion.get_injection_text())
        parts.append(self.bond.get_injection_text())

        # #G1b：trauma 激活期显式提示（关系紧张需谨慎，原仅靠 bond 数值自然降温）
        if self.bond.is_trauma_active():
            parts.append("⚠️ 关系提示：当前与用户的关系处于【创伤恢复期】（信任度偏低）。"
                         "请更谨慎、更真诚，避免轻浮或过度热情；给彼此空间，"
                         "多用行动而非空话来重建信任，别急着证明自己。")

        # 休闲时提示自己喜欢的事（兴趣热度Top，设计03-兴趣）
        if self.stress.get_mode() == "leisure" and not self.self_wake.is_resting():
            try:
                # R15/I1：全局兴趣库取材（与采集/衰减同源）
                interests = self.db.get_interests(active_only=True, user_id="__global__")[:3]
                names = [item.get("name") for item in interests if item.get("name")]
                if names:
                    parts.append("最近我喜欢的事：" + "、".join(names))
            except Exception:
                pass

        # 睡眠期间排队的消息（醒后补看）
        pending = self.consume_wake_messages()
        if pending:
            lines = [f"- {m['sender']}: {m['content'][:100]}" for m in pending[:10]]
            parts.append("睡着时收到的消息（醒来后补看）：" + "\n".join(lines))

        return "\n".join(parts)

    def _social_stance_paragraph(self) -> str:
        """设计13 §1/§2/§4/§5/§6-H4：社交立场注入段（第一人称内心戏）。

        合并五要素：冲突天平（≤130字）+ 拒绝素材优先级 + 披露分寸 + 反模板 + deferred引导。
        personality 配置组按 0-1 档位选预置文案变体，零行为代码分支（§8-I2）。
        """
        p = self.cfg.social
        seg = ["自己手头的事和人家的拜托撞车时，我会掂量两边再选，选了就不扭捏：",
               "我这事进行到哪了、放下损失多大、晚点还捡得起来吗；",
               "他那头急不急、是不是只有我能帮、我们熟到经得起拒绝吗。"]
        if p.self_priority >= 0.65:
            seg.append("而且我的事也不是随时都能放下的，先顾好自己不算失礼。")
        elif p.self_priority <= 0.35:
            seg.append("不过要是熟人开口，我多半还是会先应下来再说。")
        if p.candor >= 0.65:
            seg.append("真要拒绝就直说缘由，不绕弯子。")
        elif p.candor <= 0.35:
            seg.append("拒绝时给个台阶话，别让对方下不来台。")
        if p.indulgence >= 0.65:
            seg.append("关系好的人求我，我基本狠不下心说不。")
        seg.append("想推掉的话，先翻翻我今天真干过什么，拿真事当理由最踏实；"
                   "实在撑不起场面，再想个无伤大雅的小借口，但别演过头。")
        seg.append("也不是每件事都要汇报全，人聊天只说自己想说的那部分。")
        seg.append("一样的情况我也不必每次都用一样的说法，人有心情起伏。")
        seg.append("答应了晚点做的事，顺手记到清单里，免得转头就忘。")
        return "".join(seg)

    def _save_snapshot(self):
        self._raw_state_set("_last_snapshot", json.dumps(self.get_state_summary()), _current_user_id)

    def init_first_message(self, user_message):
        """首条消息快速校准（每会话一次，由调用方管理flag）。"""
        lower = user_message.lower()
        negative = ["难过", "伤心", "痛苦", "悲伤", "离开", "去世", "死了", "哭",
                    "sad", "cry", "hurt", "pain", "loss", "grief", "depressed"]
        if any(s in lower for s in negative):
            self.emotion.apply_delta(-0.10, 0.03, -0.02)
            self.db.log_event("quick_calibration", "system", self._current_user_id)
