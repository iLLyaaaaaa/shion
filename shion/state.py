"""Shion 的状态机与持久化。

纯 Python，不 import Qt。所有时间都通过 ``now`` 参数传入，内部不调用 ``datetime.now()``，
这样测试里可以瞬间模拟“2 小时后”。界面层根据返回的 ``Reaction`` 去说台词，
根据 ``PetState.current(now)`` 决定显示哪张精灵图。
"""
from __future__ import annotations

import json
import logging
import os
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger("shion.state")

# 有持续时间的临时状态（同时也是 react 事件允许的表情名）
TEMP_STATES = ("happy", "stop", "dizzy", "done", "proud")

MIN_HEIGHT, MAX_HEIGHT = 120, 600  # 存档里的显示高度范围（右键菜单只提供 160~320）
SAVE_RETRY = timedelta(seconds=30)  # 写盘失败后多久再试

DEFAULT_WINDOW = {"x": None, "y": None, "height": 200}  # x/y 为 None 表示用默认位置（右下角）


@dataclass(frozen=True)
class Config:
    """所有阈值都在这里，方便调整。"""

    neglect1: timedelta = timedelta(minutes=30)
    neglect2: timedelta = timedelta(hours=2)
    sleep_idle: timedelta = timedelta(minutes=15)
    working_timeout: timedelta = timedelta(minutes=2)
    night_start: time = time(0, 30)
    night_end: time = time(6, 30)

    # 临时状态持续时间
    happy_for: timedelta = timedelta(seconds=1.5)
    stop_for: timedelta = timedelta(seconds=2)
    dizzy_for: timedelta = timedelta(seconds=3)
    done_for: timedelta = timedelta(seconds=3)
    proud_for: timedelta = timedelta(seconds=3)
    react_for: timedelta = timedelta(seconds=3)

    # 连戳 / 戳到爆
    stop_clicks: int = 5
    stop_window: timedelta = timedelta(seconds=3)
    dizzy_clicks: int = 10
    dizzy_window: timedelta = timedelta(seconds=5)

    # 摸头换来的“待夸奖”计数：每个窗口内最多 +N
    praise_per_window: int = 5
    praise_window: timedelta = timedelta(seconds=60)

    @classmethod
    def debug(cls) -> "Config":
        """SHION_DEBUG=1 时使用：冷落、睡眠的阈值缩短为秒级。"""
        return cls(
            neglect1=timedelta(seconds=20),
            neglect2=timedelta(seconds=40),
            sleep_idle=timedelta(seconds=60),
            working_timeout=timedelta(seconds=20),
        )

    def temp_duration(self, name: str) -> timedelta:
        return getattr(self, f"{name}_for")


@dataclass(frozen=True)
class Reaction:
    """状态机告诉界面层“该做点什么”。目前只有 say：key 对应 zh.json 里的台词分类。"""

    kind: str
    key: str


def _say(key: str) -> Reaction:
    return Reaction("say", key)


# ---------------------------------------------------------------- 存档数据

def _parse_dt(value) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=None)
    except ValueError:
        return None


def _int(value, default: int, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return max(value, minimum)


def _bool(value, default: bool) -> bool:
    return value if isinstance(value, bool) else default


@dataclass
class SaveData:
    first_run: Optional[datetime] = None
    affection: int = 0
    last_attended: Optional[datetime] = None
    pending_praise: int = 0
    stats: dict = field(default_factory=lambda: {"date": "", "pats": 0, "claude_tasks": 0})
    window: dict = field(default_factory=lambda: dict(DEFAULT_WINDOW))
    bubble_muted: bool = False
    inject_praise: bool = True

    def to_dict(self) -> dict:
        return {
            "first_run": self.first_run.isoformat(timespec="seconds") if self.first_run else None,
            "affection": self.affection,
            "last_attended": self.last_attended.isoformat(timespec="seconds") if self.last_attended else None,
            "pending_praise": self.pending_praise,
            "stats": dict(self.stats),
            "window": dict(self.window),
            "bubble_muted": self.bubble_muted,
            "inject_praise": self.inject_praise,
        }

    @classmethod
    def from_dict(cls, raw) -> "SaveData":
        """逐个字段校验，缺失或类型不对的字段用默认值，绝不抛异常。"""
        d = cls()
        if not isinstance(raw, dict):
            return d
        d.first_run = _parse_dt(raw.get("first_run"))
        d.last_attended = _parse_dt(raw.get("last_attended"))
        d.affection = _int(raw.get("affection"), 0)
        d.pending_praise = _int(raw.get("pending_praise"), 0)
        d.bubble_muted = _bool(raw.get("bubble_muted"), False)
        d.inject_praise = _bool(raw.get("inject_praise"), True)

        stats = raw.get("stats")
        if isinstance(stats, dict):
            date = stats.get("date")
            d.stats = {
                "date": date if isinstance(date, str) else "",
                "pats": _int(stats.get("pats"), 0),
                "claude_tasks": _int(stats.get("claude_tasks"), 0),
            }

        window = raw.get("window")
        if isinstance(window, dict):
            for key in ("x", "y"):
                v = window.get(key)
                if isinstance(v, int) and not isinstance(v, bool):
                    d.window[key] = v
            h = _int(window.get("height"), DEFAULT_WINDOW["height"], minimum=1)
            d.window["height"] = max(MIN_HEIGHT, min(h, MAX_HEIGHT))
        return d


def load(path: Path) -> SaveData:
    """读取存档。文件不存在 → 默认值；损坏 → 坏文件改名为 .bad，用默认值。"""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return SaveData()
    except OSError as e:
        log.warning("读取存档失败：%s", e)
        return SaveData()
    try:
        raw = json.loads(text)
        if not isinstance(raw, dict):
            raise ValueError("顶层不是对象")
    except ValueError as e:
        bad = path.with_name(path.name + ".bad")
        log.warning("存档损坏（%s），已备份为 %s", e, bad.name)
        try:
            os.replace(path, bad)
        except OSError as e2:
            log.warning("备份损坏存档失败：%s", e2)
        return SaveData()
    return SaveData.from_dict(raw)


def save(path: Path, data: SaveData) -> None:
    """先写临时文件再替换，防止写到一半损坏。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


class SaveScheduler:
    """防抖写盘：最后一次变化 2 秒后才写。界面层用 QTimer 定期调 poll，退出时调 flush。

    写盘失败（目录只读、被占用、杀软拦截……）不会抛异常：记日志，保持 dirty，
    过 ``retry`` 之后再试，不会每个 tick 都重试。
    """

    def __init__(
        self,
        path: Path,
        data: SaveData,
        delay: timedelta = timedelta(seconds=2),
        retry: timedelta = SAVE_RETRY,
    ):
        self.path = Path(path)
        self.data = data
        self.delay = delay
        self.retry = retry
        self.dirty = False
        self._last_change: Optional[datetime] = None
        self._retry_at: Optional[datetime] = None

    def mark_dirty(self, now: datetime) -> None:
        self.dirty = True
        self._last_change = now

    def due(self, now: datetime) -> bool:
        if not self.dirty or self._last_change is None:
            return False
        if self._retry_at is not None and now < self._retry_at:
            return False
        return now - self._last_change >= self.delay

    def poll(self, now: datetime) -> bool:
        if self.due(now):
            return self.flush(now)
        return False

    def flush(self, now: Optional[datetime] = None) -> bool:
        """立即写盘。成功返回 True；失败返回 False（不抛异常，dirty 保持）。"""
        if not self.dirty:
            return True
        try:
            save(self.path, self.data)
        except OSError as e:
            log.warning("写存档失败（%s），%s 秒后重试", e, int(self.retry.total_seconds()))
            if now is not None:
                self._retry_at = now + self.retry
            return False
        self.dirty = False
        self._retry_at = None
        return True


# ---------------------------------------------------------------- 状态机

class PetState:
    def __init__(
        self,
        data: SaveData,
        now: datetime,
        config: Optional[Config] = None,
        on_change: Optional[Callable[[datetime], None]] = None,
    ):
        self.config = config or Config()
        self.save = data
        self._on_change = on_change

        self._dragging = False
        self._temp: Optional[tuple[str, datetime]] = None  # (状态名, 到期时间)
        self._working_until: Optional[datetime] = None
        self._last_activity = now  # 最近一次鼠标交互或 Claude 事件（用于睡眠）
        self._woken_date = None  # 今天夜里是否已被叫醒过
        self._clicks: deque[datetime] = deque()
        self._praise_marks: deque[datetime] = deque()
        self._last_logged: Optional[str] = None

        if self.save.first_run is None:
            self.save.first_run = now
            self._changed(now)
        if self.save.last_attended is None:
            self.save.last_attended = now
            self._changed(now)
        self._roll_stats(now)

    # ------------------------------------------------------------ 查询

    def current(self, now: datetime) -> str:
        """当前应显示的精灵名。优先级：drag > 临时反应 > working > sleep > 底层状态。"""
        if self._dragging:
            return "drag"
        if self._temp and now < self._temp[1]:
            return self._temp[0]
        if self._working_until and now < self._working_until:
            return "working"
        if self._is_asleep(now):
            return "sleep"
        return ("idle", "neglect1", "neglect2")[self._neglect_level(now)]

    # ------------------------------------------------------------ 输入

    def tick(self, now: datetime) -> None:
        """定时调用：清理到期的临时状态和 working，日期翻天时清零统计。"""
        self._roll_stats(now)
        if self._temp and now >= self._temp[1]:
            self._temp = None
        if self._working_until and now >= self._working_until:
            self._working_until = None
        self._log_state(now)

    def interact(self, now: datetime) -> list[Reaction]:
        """悬停、双击、右键等：只负责唤醒，不算“被理会”。（拖动算，见 drag_start）"""
        reactions = self._touch(now, attend=False)
        self._log_state(now)
        return reactions

    def drag_start(self, now: datetime) -> list[Reaction]:
        reactions = self._touch(now, attend=True)
        self._dragging = True
        if not reactions:
            reactions.append(_say("drag"))
        self._log_state(now)
        return reactions

    def drag_end(self, now: datetime) -> list[Reaction]:
        self._dragging = False
        reactions = self._touch(now, attend=True)
        self._log_state(now)
        return reactions

    def pat(self, now: datetime) -> list[Reaction]:
        """摸头一次（界面层累计移动 40px 算一次）。"""
        reactions = self._touch(now, attend=True)
        self.save.affection += 1
        self.save.stats["pats"] += 1
        self._set_temp("happy", now)

        window = self.config.praise_window
        while self._praise_marks and now - self._praise_marks[0] >= window:
            self._praise_marks.popleft()
        if len(self._praise_marks) < self.config.praise_per_window:
            self._praise_marks.append(now)
            self.save.pending_praise += 1
        self._changed(now)
        self._log_state(now)
        return reactions

    def click(self, now: datetime) -> list[Reaction]:
        """单击身体一次。"""
        reactions = self._touch(now, attend=True)
        self._clicks.append(now)
        while self._clicks and now - self._clicks[0] >= self.config.dizzy_window:
            self._clicks.popleft()

        cfg = self.config
        recent_stop = sum(1 for t in self._clicks if now - t < cfg.stop_window)
        if len(self._clicks) >= cfg.dizzy_clicks:
            self._clicks.clear()
            self._set_temp("dizzy", now)
            reactions.append(_say("dizzy"))
        elif recent_stop >= cfg.stop_clicks and not self._temp_active("stop", now):
            self._set_temp("stop", now)
            reactions.append(_say("stop"))
        elif not reactions:
            reactions.append(_say("poke"))
        self._log_state(now)
        return reactions

    def praise_claude(self, now: datetime) -> list[Reaction]:
        """右键菜单“夸夸 Claude”。"""
        reactions = self._touch(now, attend=False)
        self.save.affection += 3
        self.save.pending_praise += 1
        self._set_temp("proud", now)
        self._changed(now)
        reactions.append(_say("praise_menu"))
        self._log_state(now)
        return reactions

    def take_praise(self, now: Optional[datetime] = None) -> int:
        """读取并清零待夸奖计数（给 /praise/take 用）。now 用来给存档防抖计时。"""
        count = self.save.pending_praise
        if count:
            self.save.pending_praise = 0
            self._changed(now or self._last_activity)
        return count

    def claude_event(self, etype: str, detail: Optional[str], now: datetime) -> list[Reaction]:
        """处理本地 HTTP 服务转来的事件。未知类型直接忽略。"""
        if etype not in ("session_start", "prompt", "working", "stop", "notification", "react"):
            log.info("忽略未知事件：%r", etype)
            return []
        if etype == "react" and detail not in TEMP_STATES:
            log.info("忽略未知表情：%r", detail)
            return []

        reactions = self._touch(now, attend=True)
        if etype == "session_start":
            reactions.append(_say("greeting"))
        elif etype == "working":
            if not (self._working_until and now < self._working_until):
                reactions.append(_say("claude_working"))
            self._working_until = now + self.config.working_timeout  # 有新事件就续期
        elif etype == "stop":
            self._working_until = None
            self.save.stats["claude_tasks"] += 1
            self._set_temp("done", now)
            self._changed(now)
            reactions.append(_say("claude_done"))
        elif etype == "notification":
            reactions.append(_say("claude_waiting"))
        elif etype == "react":
            self._temp = (detail, now + self.config.react_for)
        self._log_state(now)
        return reactions

    # ------------------------------------------------------------ 内部

    def _touch(self, now: datetime, attend: bool) -> list[Reaction]:
        """任何交互的公共入口：翻日、唤醒、刷新“被理会”时间。"""
        self._roll_stats(now)
        was_asleep = self._is_asleep(now)
        prev_level = self._neglect_level(now)

        self._last_activity = now
        if self._in_night(now):
            self._woken_date = now.date()
        if attend:
            self.save.last_attended = now
            self._changed(now)

        if attend and prev_level == 2:
            return [_say("neglect_return")]
        if was_asleep:
            return [_say("wake")]
        return []

    def _is_asleep(self, now: datetime) -> bool:
        if now - self._last_activity >= self.config.sleep_idle:
            return True
        return self._in_night(now) and self._woken_date != now.date()

    def _in_night(self, now: datetime) -> bool:
        start, end, t = self.config.night_start, self.config.night_end, now.time()
        if start <= end:
            return start <= t < end
        return t >= start or t < end

    def _neglect_level(self, now: datetime) -> int:
        elapsed = now - self.save.last_attended
        if elapsed >= self.config.neglect2:
            return 2
        if elapsed >= self.config.neglect1:
            return 1
        return 0

    def _set_temp(self, name: str, now: datetime) -> None:
        self._temp = (name, now + self.config.temp_duration(name))

    def _temp_active(self, name: str, now: datetime) -> bool:
        return bool(self._temp and self._temp[0] == name and now < self._temp[1])

    def _roll_stats(self, now: datetime) -> None:
        today = now.date().isoformat()
        if self.save.stats.get("date") != today:
            self.save.stats = {"date": today, "pats": 0, "claude_tasks": 0}
            self._changed(now)

    def _changed(self, now: datetime) -> None:
        if self._on_change:
            self._on_change(now)

    def _log_state(self, now: datetime) -> None:
        state = self.current(now)
        if state != self._last_logged:
            log.info("状态：%s → %s", self._last_logged, state)
            self._last_logged = state
