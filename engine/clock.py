"""Clock manager — sleep/wake cycle."""
from __future__ import annotations
import os
import random
import time as _time
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from .config import ClockConfig


class ClockPhase:
    WAKING = "waking"
    WINDING_DOWN = "winding_down"
    SLEEPING = "sleeping"
    WARMING_UP = "warming_up"


def _parse_time(t: str) -> time:
    h, m = t.split(":")
    return time(int(h), int(m))


class ClockManager:
    def __init__(self, cfg: ClockConfig, get_state, set_state):
        self.cfg = cfg
        self._get = get_state
        self._set = set_state
        self._load_wake_drift()
        # 测试用假时钟偏移（秒）：读取文件 HERMES_ALIVE_CLOCK_OFFSET_FILE
        # （默认 /tmp/hermes_fake_clock_offset），文件内容为整型秒数；
        # 默认 0（文件不存在）。非测试环境不创建该文件即完全无影响。
        self._offset_cached = 0
        self._offset_cached_ts = 0.0

    def _load_wake_drift(self) -> None:
        """R-H/12（红队审查）：起床漂移持久化到 __global__ 状态键——
        原每次构造随机导致容器重启作息被反复洗牌；首次随机一次后落库，
        之后 refresh 在旧值上小幅游走（连续化）。"""
        try:
            v = float(self._get("clock_wake_drift", None) or 0)
        except (TypeError, ValueError):
            v = 0.0
        if not v:
            v = float(random.randint(-self.cfg.drift_range, self.cfg.drift_range))
            try:
                self._set("clock_wake_drift", v)
            except Exception:
                pass
        self._wake_drift = int(v)

    def get_phase(self) -> str:
        return self._get("clock_phase", ClockPhase.WAKING)

    def _clock_offset(self) -> int:
        """测试假时钟偏移（秒），读取偏移文件并缓存 2 秒。默认 0。

        用法（容器内）：
            echo 43200 > /tmp/hermes_fake_clock_offset   # 快进 12 小时
            rm /tmp/hermes_fake_clock_offset             # 恢复真实时钟
        偏移文件由测试驱动写入，生产环境不存在该文件，行为不变。
        """
        now = _time.time()
        if now - self._offset_cached_ts > 2.0:
            try:
                path = os.environ.get(
                    "HERMES_ALIVE_CLOCK_OFFSET_FILE", "/tmp/hermes_fake_clock_offset"
                )
                if os.path.exists(path):
                    with open(path) as fh:
                        self._offset_cached = int(fh.read().strip())
                else:
                    self._offset_cached = 0
            except Exception:
                self._offset_cached = 0
            self._offset_cached_ts = now
        return self._offset_cached

    def _local_now(self):
        """作息时区的墙钟时间（R2）。timezone 为空=跟随进程时区（旧行为）。
        假时钟测试偏移一律叠加在本地墙上。相位判定与时刻文案都从这里取。"""
        tzname = (getattr(self.cfg, "timezone", "") or "").strip()
        try:
            now = datetime.now(ZoneInfo(tzname)) if tzname else datetime.now()
        except Exception:
            now = datetime.now()  # 时区名无效时退回旧行为，绝不崩溃
        off = self._clock_offset()
        return now + timedelta(seconds=off) if off else now

    def _now(self) -> time:
        return self._local_now().time()

    def _is_weekend(self) -> bool:
        return self.cfg.weekend_enabled and self._local_now().weekday() >= 5

    def _schedule(self, is_weekend: bool | None = None) -> dict:
        """Effective schedule for today (weekend override supported).

        is_weekend=None → 按当前墙钟日期判定；显式传值用于夜晚锚点
        （R-H/40：凌晨时段归属前一晚的作息）。"""
        if is_weekend is None:
            is_weekend = self._is_weekend()
        if is_weekend:
            return {
                "soft": _parse_time(self.cfg.weekend_soft),
                "hard": _parse_time(self.cfg.weekend_hard),
                "wind_down": _parse_time(self.cfg.weekend_soft),  # wind-down starts at soft limit on weekends
            }
        return {
            "soft": _parse_time(self.cfg.sleep_soft_time),
            "hard": _parse_time(self.cfg.sleep_hard_time),
            "wind_down": _parse_time(self.cfg.wind_down_start),
        }

    def _night_weekend(self) -> bool:
        """R-H/40（红队）：夜间带的锚定周末判定——凌晨 0-8 点归前一晚。

        原 `_is_weekend()` 按当前墙钟日期判定：周日夜跨到周一 00:00 后
        变成工作日，weekday band [23:30, 07:30) 的 wrap 分支在 00:01 就
        掐断入睡——weekend_hard=00:30 的"周末可熬到 00:30"只对周六夜生效，
        周日夜实际 00:01 就被迫睡（日历翻转击穿硬限制）。8h 偏移让
        00:00-08:00 归属前一晚：周日夜（周末锚定）可守到 00:30 才睡。
        晨醒判决仍用 `_is_weekend()`（当日），保住周六睡懒觉的 weekend_wake。
        """
        return self.cfg.weekend_enabled and (
            self._local_now() - timedelta(hours=8)).weekday() >= 5

    @staticmethod
    def _to_mins(t: time) -> int:
        return t.hour * 60 + t.minute

    @staticmethod
    def _in_interval(now: time, start: time, end: time) -> bool:
        """now ∈ [start, end)，end 跨午夜（end < start）时带跨 0 点。"""
        n = ClockManager._to_mins(now)
        s = ClockManager._to_mins(start)
        e = ClockManager._to_mins(end)
        if s <= e:
            return s <= n < e
        return n >= s or n < e

    def _in_overnight_band(self, now: time, wake: time, hard: time) -> bool:
        """now 是否处于夜间睡眠带 [hard, wake)（hard 跨午夜时带跨 0 点）。

        R-H/33（红队）：原相位机用裸 time 比较 `now >= hard`，当 hard 跨午夜
        （如 weekend_enabled 时 weekend_hard=00:30）该式对全天任意时刻几乎
        恒真——周六清晨刚醒就被判「已过就寝」→ 醒 30 分钟又睡着，周末整天
        无法保持清醒。改为按分钟数做「睡眠带」归属判断。
        """
        n = self._to_mins(now)
        w = self._to_mins(wake)
        h = self._to_mins(hard)
        if h <= w:          # 常规：就寝(h) < 晨醒(w)，带 = [h, w)
            return h <= n < w
        # hard 跨午夜（如 00:30）：带 = [h, 1440) ∪ [0, w)，即已过 h 或在晨醒前
        return n >= h or n < w

    def _sleep_session_before_wake(self, start_ts, actual_wake: time) -> bool:
        """睡眠会话起点（按钟面墙钟折算）是否早于今日 actual_wake。

        R-H/33（红队）：提前晚安（如 21:00，wind_down 之前）原会被相位机
        「晨间窗口」误判为「早晨已过」→ 下一秒翻回 warming_up 反弹唤醒。
        改为记录会话起点：只有「昨夜开始的觉」（起点在今日晨醒点之前）才在
        晨间醒；当晚提前入睡保持睡眠直至次日晨。起点折算用钟面墙钟差，规避
        假时钟（epoch 漂移回 1970）下日期失真。
        """
        try:
            start = float(start_ts)
        except (TypeError, ValueError):
            return False
        try:
            now_wall = self._local_now()
            elapsed = max(0.0, _time.time() - start)
            start_wall = now_wall - timedelta(seconds=elapsed)
        except Exception:
            return False
        if start_wall.date() < now_wall.date():
            return True
        if start_wall.date() == now_wall.date():
            return start_wall.time() < actual_wake
        return False

    def tick(self) -> str | None:
        """Called every minute. Returns phase change event or None."""
        now = self._now()
        current = self.get_phase()
        # R-H/40：夜间带/犯困窗用「夜晚锚点」判周末（凌晨归前一晚——
        # 周日夜可守到 weekend_hard=00:30，不被日历翻转击穿）
        sched = self._schedule(self._night_weekend())
        soft = sched["soft"]
        hard = sched["hard"]
        wind_down = sched["wind_down"]
        # R-H/33: 周末醒时用独立配置（原 weekend_wake 从未被读取——死配置）；
        # 晨醒判决用当日周末（保住周六睡懒觉）
        wake_base = _parse_time(self.cfg.weekend_wake) if self._is_weekend() \
            else _parse_time(self.cfg.wake_time)
        actual_wake = (datetime.combine(datetime.today(), wake_base)
                       + timedelta(minutes=self._wake_drift)).time()

        new_phase = current
        # 犯困窗终点：平日 soft；周末 wind_down==soft → 窗延至 hard
        # （从 soft 一直犯困到硬就寝，期间进入 winding_down 相位感知「犯困中」）
        wd_end = hard if wind_down == soft else soft

        if current == ClockPhase.SLEEPING:
            # R-H/33: 晨醒判定改「睡眠会话跨日到达晨醒点」——记录会话起点
            # （force_sleep / 相位机入睡转移写入 clock_sleep_start_ts）：
            #   ① 整夜自然睡眠（会话始于昨夜 → 跨日醒来）
            #   ② 当晚提前晚安（会话始于今日晨醒点之后 → 保持睡眠直至次晨）
            #   ③ 凌晨才睡（会话始于今日晨醒点之前 → 当日晨正常醒）
            # 无会话起点（升级前遗留状态）退回原「晨间窗口」规则。
            _start = self._get("clock_sleep_start_ts", None)
            if not _start:
                if now >= actual_wake and now < wind_down:
                    new_phase = ClockPhase.WARMING_UP
                    self.refresh_wake_drift()
            elif now >= actual_wake and self._sleep_session_before_wake(_start, actual_wake):
                new_phase = ClockPhase.WARMING_UP
                self.refresh_wake_drift()
        elif current == ClockPhase.WARMING_UP:
            if now >= (datetime.combine(datetime.today(), actual_wake)
                       + timedelta(minutes=self.cfg.warm_up_minutes)).time():
                new_phase = ClockPhase.WAKING
        elif current == ClockPhase.WAKING:
            # R-H/33: 入睡判定改「夜间带」归属（hard 跨午夜时不再裸比较恒真）
            if self._in_overnight_band(now, actual_wake, hard):
                new_phase = ClockPhase.SLEEPING
                self._set("clock_sleep_start_ts", _time.time())
            elif self._in_interval(now, wind_down, wd_end):
                new_phase = ClockPhase.WINDING_DOWN
        elif current == ClockPhase.WINDING_DOWN:
            # R-H/33: 入睡判定同 WAKING——带内即入睡；离开犯困窗
            # （午夜回绕/提前晚安后再评估）→ 回清醒
            if self._in_overnight_band(now, actual_wake, hard):
                new_phase = ClockPhase.SLEEPING
                self._set("clock_sleep_start_ts", _time.time())
            elif not self._in_interval(now, wind_down, wd_end):
                new_phase = ClockPhase.WAKING

        if new_phase != current:
            self._set("clock_phase", new_phase)
            return f"clock:{current}_to_{new_phase}"
        return None

    def force_sleep(self) -> None:
        """R-H/33: 强制入睡同时记录会话起点（提前晚安不再被误判为次日晨醒）。"""
        self._set("clock_phase", ClockPhase.SLEEPING)
        self._set("clock_sleep_start_ts", _time.time())

    def force_wake(self) -> None:
        self._set("clock_phase", ClockPhase.WARMING_UP)
        self._set("clock_sleep_start_ts", 0)

    def is_sleeping(self) -> bool:
        return self.get_phase() == ClockPhase.SLEEPING

    def is_winding_down(self) -> bool:
        return self.get_phase() == ClockPhase.WINDING_DOWN

    def is_waking(self) -> bool:
        return self.get_phase() == ClockPhase.WAKING

    def past_soft_limit(self) -> bool:
        """True after the soft goodnight limit (agent should say goodnight)."""
        sched = self._schedule()
        now = self._now()
        soft, hard = sched["soft"], sched["hard"]
        if soft <= hard:
            return now >= soft
        # hard wraps past midnight (e.g. weekend hard 00:30)
        return now >= soft or now < hard

    def refresh_wake_drift(self) -> None:
        """R-H/12（红队审查）：漂移连续化——旧值 ±7min 小步游走而非每次
        重新随机（真人起床时间日间连续），clamp 到 ±drift_range 并持久化。"""
        new = self._wake_drift + random.randint(-7, 7)
        new = max(-self.cfg.drift_range, min(self.cfg.drift_range, new))
        self._wake_drift = new
        try:
            self._set("clock_wake_drift", new)
        except Exception:
            pass

    def get_phase_multiplier(self) -> float:
        """Energy decay multiplier for current phase.

        SLEEPING×0（睡眠不消耗）、WARMING_UP×0.5、WINDING_DOWN×1.5（配置驱动）。
        """
        phase = self.get_phase()
        if phase == ClockPhase.SLEEPING:
            return 0.0
        if phase == ClockPhase.WARMING_UP:
            return 0.5
        if phase == ClockPhase.WINDING_DOWN:
            return 1.5  # clock.wind_down.multiplier (design doc 02 §2)
        return 1.0