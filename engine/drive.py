"""Drive manager — 内在驱动力信号合成（设计14）。

定位（00b 总纲）：驱动力是注入 LLM 的上下文信号，规则只管门控；
本模块不建 MCTS / 不做硬加权求和阈值。

信号合成（仅供注入提示词）：
  signal = clamp01(boredom_norm*0.6 + engagement*0.2 + noise*0.2 + feedback_bias)
  - boredom_norm : 当前 boredom / max_value（低挑战/信息差代理）
  - engagement   : 近期正向事件指数衰减计数（胜任感代理）
  - noise        : 受控随机共振（仅影响表达强度，不决定触发）
  - feedback_bias: 轻量反馈闭环（接纳↑/冷落↓），不碰 PAD/Bond 约束引擎

触发门控 should_initiate 是布尔门控，与能量满自唤醒路径互斥。
"""
from __future__ import annotations
import random
import time as _time
from .config import DriveConfig


class DriveManager:
    def __init__(self, cfg: DriveConfig, get_state, set_state):
        self.cfg = cfg
        self._get = get_state
        self._set = set_state
        # R-H/39（红队）：冷却时间戳持久化——原纯内存态，进程重启/双进程
        # （gateway+dashboard 各自实例）都会丢失 90min 冷却，重启后可能立即
        # 再次主动发起（虽有 daily_max 兜底，行为仍毛糙）。启动时回载。
        self._last_initiate_ts = 0.0
        try:
            v = self._get("drive_last_initiate_ts", None)
            if v:
                self._last_initiate_ts = float(v)
        except (TypeError, ValueError):
            self._last_initiate_ts = 0.0

    # ── 注入信号 ──

    def signal(self) -> float:
        if not self.cfg.enabled:
            return 0.0
        try:
            boredom = float(self._get("boredom", 0) or 0)
        except (TypeError, ValueError):
            boredom = 0.0
        max_v = max(1.0, float(self._get("boredom_max", 100) or 100))
        b_norm = max(0.0, min(1.0, boredom / max_v))
        eng = self._get_engagement()
        noise = random.gauss(0.0, self.cfg.noise_sigma)
        noise = max(-0.3, min(0.3, noise))
        s = b_norm * 0.6 + eng * 0.2 + noise * 0.2 + self._get_feedback_bias()
        return max(0.0, min(1.0, s))

    def signal_text(self) -> str:
        s = self.signal()
        if s <= 0:
            return ""
        if s < 0.34:
            return "驱动力：有点想做点事，但不那么强烈。"
        if s < 0.67:
            return "驱动力：我有点想做点什么/找人唠唠。"
        return "驱动力：我挺想做点事/找人聊聊的——现在就有点想动起来。"

    # ── 触发门控（布尔）──

    def should_initiate(self, *, phase: str, sleeping: bool, winding_down: bool,
                        resting: bool, energy: float, energy_full_threshold: float,
                        boredom: float) -> tuple:
        if not self.cfg.enabled:
            return (False, "disabled")
        if sleeping or winding_down or resting:
            return (False, "phase_guard")
        if energy < self.cfg.energy_min:
            return (False, "energy_low")
        if energy >= energy_full_threshold:
            return (False, "energy_full_path")
        jitter = random.gauss(0.0, self.cfg.threshold_jitter_sigma)
        th = self.cfg.boredom_threshold + jitter
        if boredom < th:
            return (False, "boredom_below")
        now = _time.time()
        if self._last_initiate_ts and (now - self._last_initiate_ts) < self.cfg.cooldown_seconds:
            return (False, "cooldown")
        # R13/G6（§八）：每日本地日封顶 daily_max 轮（发起时刻才计数）
        daily = self._daily_count()
        if daily >= int(self.cfg.daily_max or 0):
            return (False, "daily_max")
        return (True, "boredom_high")

    def mark_initiated(self) -> None:
        self._last_initiate_ts = _time.time()
        try:
            # R-H/39：冷却时间戳同步持久化（全局键，跨重启/双进程共享）
            self._set("drive_last_initiate_ts", self._last_initiate_ts)
            # R16（审计§十七）：与读方 _daily_count 自洽的 "日期:次数" 格式——
            # 此前写裸整数致读方解析恒失败→daily_max 闸门恒失效
            import datetime as _dt
            self._set("drive_daily",
                      "%s:%d" % (_dt.date.today().isoformat(), self._daily_count() + 1))
        except Exception:
            pass

    def _daily_count(self) -> int:
        """R13/G6：当日（本地日）已自发轮数。"""
        import datetime as _dt
        raw = self._get("drive_daily", "") or ""
        try:
            d, n = str(raw).split(":", 1)
        except ValueError:
            return 0
        return int(n) if d == _dt.date.today().isoformat() else 0

    # ── 反馈软乘子（不碰 PAD/Bond）──

    def on_accepted(self) -> None:
        v = float(self._get("drive_feedback", 1.0) or 1.0)
        v = min(self.cfg.feedback_max, v + self.cfg.feedback_step)
        self._set("drive_feedback", v)

    def on_ignored(self) -> None:
        v = float(self._get("drive_feedback", 1.0) or 1.0)
        v = max(self.cfg.feedback_min, v - self.cfg.feedback_step * 2)
        self._set("drive_feedback", v)

    def _get_feedback_bias(self) -> float:
        try:
            v = float(self._get("drive_feedback", 1.0) or 1.0)
        except (TypeError, ValueError):
            return 0.0
        return max(-0.2, min(0.2, (v - 1.0) * 0.2))

    # ── engagement（指数衰减）──

    def _get_engagement(self) -> float:
        try:
            v = float(self._get("drive_engagement", 0.0) or 0.0)
        except (TypeError, ValueError):
            v = 0.0
        ts = float(self._get("drive_engagement_ts", 0.0) or 0.0)
        if ts <= 0:
            return max(0.0, min(1.0, v))
        dt = max(0.0, _time.time() - ts)
        decayed = v * (0.5 ** (dt / 7200.0))
        return max(0.0, min(1.0, decayed))

    def bump_engagement(self, delta: float = 0.2) -> None:
        cur = self._get_engagement()
        nv = max(0.0, min(1.0, cur + delta))
        self._set("drive_engagement", nv)
        self._set("drive_engagement_ts", _time.time())
