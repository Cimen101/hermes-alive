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
        self._wake_drift: int = random.randint(-cfg.drift_range, cfg.drift_range)
        # 测试用假时钟偏移（秒）：读取文件 HERMES_ALIVE_CLOCK_OFFSET_FILE
        # （默认 /tmp/hermes_fake_clock_offset），文件内容为整型秒数；
        # 默认 0（文件不存在）。非测试环境不创建该文件即完全无影响。
        self._offset_cached = 0
        self._offset_cached_ts = 0.0

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

    def _schedule(self) -> dict:
        """Effective schedule for today (weekend override supported)."""
        if self._is_weekend():
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

    def tick(self) -> str | None:
        """Called every minute. Returns phase change event or None."""
        now = self._now()
        current = self.get_phase()
        sched = self._schedule()
        soft = sched["soft"]
        hard = sched["hard"]
        wind_down = sched["wind_down"]
        wake_base = _parse_time(self.cfg.wake_time)
        actual_wake = (datetime.combine(datetime.today(), wake_base)
                       + timedelta(minutes=self._wake_drift)).time()

        new_phase = current

        if current == ClockPhase.SLEEPING:
            # 仅在晨间窗口 (wake_time ~ wind_down_start) 醒来。
            # 用 now < wind_down 而非 now < hard：晚安后当晚整段
            # (wake<=now<hard) 都满足，会每 tick 误判为「早晨已过 wake」而
            # 翻回 warming_up，导致夜间睡眠无法保持（发现#12）。
            if now >= actual_wake and now < wind_down:
                new_phase = ClockPhase.WARMING_UP
                self.refresh_wake_drift()
        elif current == ClockPhase.WARMING_UP:
            if now >= (datetime.combine(datetime.today(), actual_wake)
                       + timedelta(minutes=self.cfg.warm_up_minutes)).time():
                new_phase = ClockPhase.WAKING
        elif current == ClockPhase.WAKING:
            if now >= hard or now < wake_base:
                # Past hard limit, or still before today's wake time (past midnight)
                new_phase = ClockPhase.SLEEPING
            elif now >= wind_down and now < soft:
                new_phase = ClockPhase.WINDING_DOWN
        elif current == ClockPhase.WINDING_DOWN:
            if now >= hard or now < wind_down:
                # Hard limit reached, or time regressed before wind-down start
                # (e.g. user said goodnight earlier / midnight wrap) → re-evaluate
                if now >= hard or now < wake_base:
                    new_phase = ClockPhase.SLEEPING
                else:
                    new_phase = ClockPhase.WAKING

        if new_phase != current:
            self._set("clock_phase", new_phase)
            return f"clock:{current}_to_{new_phase}"
        return None

    def force_sleep(self) -> None:
        self._set("clock_phase", ClockPhase.SLEEPING)

    def force_wake(self) -> None:
        self._set("clock_phase", ClockPhase.WARMING_UP)

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
        self._wake_drift = random.randint(-self.cfg.drift_range, self.cfg.drift_range)

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