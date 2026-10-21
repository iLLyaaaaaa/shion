"""Shion 的状态机与持久化。

纯 Python，不 import Qt。所有时间都通过 ``now`` 参数传入，内部不调用 ``datetime.now()``，
这样测试里可以瞬间模拟“2 小时后”。界面层根据返回的 ``Reaction`` 去说台词，
根据 ``PetState.current(now)`` 决定显示哪张精灵图。
"""
from __future__ import annotations

import json
import logging
import os
import random
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Callable, Optional

from shion.affection import AffectionRules

log = logging.getLogger("shion.state")

# 有持续时间的临时状态（同时也是 react 事件允许的表情名）
TEMP_STATES = ("happy", "stop", "dizzy", "done", "proud")
EXPRESSIONS = ("happy", "proud", "stop", "dizzy", "working", "done", "sleep", "idle", "neglect2")
ACTIVITY_LEVELS = ("quiet", "normal", "lively")
SAVE_VERSION = 5  # v5 增加等级和每日好感记录；保留旧存档迁移
FEEDBACK_MAX = 5  # 反馈队列最多几条，满了丢最早的
FEEDBACK_TEXT_MAX = 200
REMOTE_DEFAULTS = {"pause_timeout": 1800, "permission_timeout": 120}  # 秒

MIN_HEIGHT, MAX_HEIGHT = 120, 600  # 存档里的显示高度范围（右键菜单只提供 160~320）
SAVE_RETRY = timedelta(seconds=30)  # 写盘失败后多久再试

# 本地时间，含起点、不含终点；跨午夜的时段以 start > end 表示。
TIME_SPEECH_PERIODS = {
    "time_morning": (time(5), time(10)),
    "time_noon": (time(11, 30), time(13, 30)),
    "time_evening": (time(17, 30), time(19, 30)),
    "time_late": (time(23), time(2)),
    "time_dawn": (time(2), time(5)),
}
DEFAULT_WINDOW = {"x": None, "y": None, "height": 200}  # x/y 为 None 表示用默认位置（右下角）


def time_speech_period(now: datetime) -> Optional[str]:
    t = now.time()
    for key, (start, end) in TIME_SPEECH_PERIODS.items():
        matches = start <= t < end if start < end else t >= start or t < end
        if matches:
            return key
    return None


def _time_speech_record(raw) -> dict:
    empty = {"date": "", "spoken": []}
    if not isinstance(raw, dict) or not isinstance(raw.get("date"), str):
        return empty
    try:
        datetime.strptime(raw["date"], "%Y-%m-%d")
    except ValueError:
        return empty
    spoken = raw.get("spoken")
    if not isinstance(spoken, list):
        return empty
    return {"date": raw["date"], "spoken": sorted({s for s in spoken
            if isinstance(s, str) and s in TIME_SPEECH_PERIODS})}


@dataclass(frozen=True)
class Config:
    """所有阈值都在这里，方便调整。"""

    neglect1: timedelta = timedelta(minutes=30)
    neglect2: timedelta = timedelta(hours=2)
    sleep_idle: timedelta = timedelta(minutes=15)
    working_timeout: timedelta = timedelta(minutes=5)  # 没有工具在执行时，多久没新事件就退出 working
    tool_timeout: timedelta = timedelta(minutes=30)  # 工具执行中（PreToolUse 之后还没 PostToolUse）最长保持多久
    night_start: time = time(0, 30)
    night_end: time = time(6, 30)

    # 临时状态持续时间
    happy_for: timedelta = timedelta(seconds=1.5)
    stop_for: timedelta = timedelta(seconds=2)
    dizzy_for: timedelta = timedelta(seconds=3)
    done_for: timedelta = timedelta(seconds=3)
    proud_for: timedelta = timedelta(seconds=3)
    react_for: timedelta = timedelta(seconds=3)
    tool_error_for: timedelta = timedelta(seconds=2)

    # 催你回来：Claude 停下后这么久没有新消息就提醒，最多提醒 nudge_max 次
    nudge_after: timedelta = timedelta(minutes=5)
    nudge_max: int = 2

    poke_gap: timedelta = timedelta(seconds=1.5)
    poke_early: int = 3
    poke_late: int = 5
    poke_early_stop: float = 0.60
    poke_early_dizzy: float = 0.20
    poke_late_stop: float = 0.55
    poke_late_dizzy: float = 0.40
    shake_dizzy_for: timedelta = timedelta(seconds=2.5)
    expression_for: timedelta = timedelta(seconds=5)
    idle_expression_for: timedelta = timedelta(seconds=2)
    pat_affection: int = 1
    praise_affection: int = 3
    snack_affection: int = 2
    snack_limit: int = 5
    eating_for: timedelta = timedelta(seconds=2)

    @classmethod
    def debug(cls) -> "Config":
        """SHION_DEBUG=1 时使用：冷落、睡眠的阈值缩短为秒级。"""
        return cls(
            neglect1=timedelta(seconds=20),
            neglect2=timedelta(seconds=40),
            sleep_idle=timedelta(seconds=60),
            working_timeout=timedelta(seconds=60),
            nudge_after=timedelta(seconds=20),
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


@dataclass
class WorkSession:
    """一个 CC 会话的工作状态（不存档）。tools：在执行的工具 tool_use_id → 开始时间。"""

    last: datetime
    tools: dict = field(default_factory=dict)

    def active(self, now: datetime, cfg: "Config") -> bool:
        if any(now - start < cfg.tool_timeout for start in self.tools.values()):
            return True
        return now - self.last < cfg.working_timeout


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


def _feedback_items(raw) -> list:
    out = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and item.get("kind") in ("good", "bad"):
                text = item.get("text")
                text = " ".join(text.split())[:FEEDBACK_TEXT_MAX] if isinstance(text, str) else ""
                out.append({"kind": item["kind"], "text": text})
    return out[-FEEDBACK_MAX:]


def _bool(value, default: bool) -> bool:
    return value if isinstance(value, bool) else default


@dataclass
class SaveData:
    schema_version: int = SAVE_VERSION
    first_run: Optional[datetime] = None
    affection: int = 0
    affection_level: Optional[int] = None
    affection_daily: dict = field(default_factory=dict)
    last_attended: Optional[datetime] = None
    feedback_queue: list = field(default_factory=list)  # [{"kind": "good"|"bad", "text": str}]
    remote: dict = field(default_factory=lambda: dict(REMOTE_DEFAULTS))
    stats: dict = field(default_factory=lambda: {"date": "", "pats": 0, "claude_tasks": 0})
    window: dict = field(default_factory=lambda: dict(DEFAULT_WINDOW))
    bubble_muted: bool = False
    inject_praise: bool = True
    privacy_mode: bool = False  # 只显示状态，不显示文件名/命令/回复内容
    language: Optional[str] = None  # None = 还没选过，首次启动时跟随系统语言
    fixed_expression: Optional[str] = None
    activity_level: str = "normal"
    snacks: dict = field(default_factory=lambda: {"date": "", "count": 0})
    release_to_taskbar: bool = False
    always_on_top: bool = True
    time_speech: dict = field(default_factory=lambda: {"date": "", "spoken": []})

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "first_run": self.first_run.isoformat(timespec="seconds") if self.first_run else None,
            "affection": self.affection,
            "affection_level": self.affection_level,
            "affection_daily": {**self.affection_daily, "talks": list(self.affection_daily.get("talks", []))},
            "last_attended": self.last_attended.isoformat(timespec="seconds") if self.last_attended else None,
            "feedback_queue": [dict(i) for i in self.feedback_queue],
            "remote": dict(self.remote),
            "stats": dict(self.stats),
            "window": dict(self.window),
            "bubble_muted": self.bubble_muted,
            "inject_praise": self.inject_praise,
            "privacy_mode": self.privacy_mode,
            "language": self.language,
            "fixed_expression": self.fixed_expression,
            "activity_level": self.activity_level,
            "snacks": dict(self.snacks),
            "release_to_taskbar": self.release_to_taskbar,
            "always_on_top": self.always_on_top,
            "time_speech": {"date": self.time_speech["date"], "spoken": list(self.time_speech["spoken"])},
        }

    @classmethod
    def from_dict(cls, raw) -> "SaveData":
        """逐个字段校验，缺失或类型不对的字段用默认值，绝不抛异常。"""
        d = cls()
        if not isinstance(raw, dict):
            return d
        d.schema_version = _int(raw.get("schema_version"), 1, minimum=1)
        d.first_run = _parse_dt(raw.get("first_run"))
        d.last_attended = _parse_dt(raw.get("last_attended"))
        d.affection = _int(raw.get("affection"), 0)
        level = raw.get("affection_level")
        d.affection_level = level if type(level) is int and 1 <= level <= 5 else None
        daily = raw.get("affection_daily")
        if isinstance(daily, dict) and isinstance(daily.get("date"), str):
            talks = daily.get("talks")
            d.affection_daily = {
                "date": daily["date"], "pat": _int(daily.get("pat"), 0),
                "snack": _int(daily.get("snack"), 0), "open": min(_int(daily.get("open"), 0), 1),
                "talks": sorted({s for s in talks if isinstance(s, str) and s}) if isinstance(talks, list) else [],
            }
        d.feedback_queue = _feedback_items(raw.get("feedback_queue"))
        if d.schema_version == 2 and not d.feedback_queue:
            old = _int(raw.get("pending_praise"), 0)  # v2 的待表扬都来自菜单“做得好”
            d.feedback_queue = [{"kind": "good", "text": ""}] * min(old, FEEDBACK_MAX)
        remote = raw.get("remote")
        if isinstance(remote, dict):
            d.remote["pause_timeout"] = max(60, min(_int(remote.get("pause_timeout"), 1800), 1880))
            d.remote["permission_timeout"] = max(10, min(_int(remote.get("permission_timeout"), 120), 170))
        d.bubble_muted = _bool(raw.get("bubble_muted"), False)
        d.inject_praise = _bool(raw.get("inject_praise"), True)
        d.privacy_mode = _bool(raw.get("privacy_mode"), False)
        d.release_to_taskbar = _bool(raw.get("release_to_taskbar"), False)
        d.always_on_top = _bool(raw.get("always_on_top"), True)
        d.time_speech = _time_speech_record(raw.get("time_speech"))
        lang = raw.get("language")
        d.language = lang if isinstance(lang, str) and lang else None
        expr = raw.get("fixed_expression")
        d.fixed_expression = expr if expr in EXPRESSIONS else None
        level = raw.get("activity_level")
        d.activity_level = level if level in ACTIVITY_LEVELS else "normal"
        snacks = raw.get("snacks")
        if isinstance(snacks, dict):
            date = snacks.get("date")
            d.snacks = {"date": date if isinstance(date, str) else "",
                        "count": _int(snacks.get("count"), 0)}

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
        rng: Optional[random.Random] = None,
        affection: Optional[AffectionRules] = None,
    ):
        self.config = config or Config()
        self.affection = affection
        self.save = data
        self._on_change = on_change
        self._rng = rng or random.Random()

        self._dragging = False
        self._temp: Optional[tuple[str, datetime]] = None  # (状态名, 到期时间)
        self._sessions: dict[str, WorkSession] = {}  # 正在工作的会话（session_id → 状态；旧 hook 没带 id 时用 ""）
        self._stopped_at: Optional[datetime] = None  # Claude 停下的时间（催你回来用）
        self._nudges = 0
        self._last_activity = now  # 最近一次鼠标交互或 Claude 事件（用于睡眠）
        self._woken_date = None  # 今天夜里是否已被叫醒过
        self._poke_count = 0
        self._last_poke: Optional[datetime] = None
        self._manual: Optional[tuple[str, datetime]] = None
        self._idle_expression: Optional[tuple[str, datetime]] = None
        self._last_logged: Optional[str] = None
        self.paused = False  # 用户在诗音上点了“暂停”（不存档）
        self._menu_sleep = False
        self._resting = False
        self._resting_auto = False
        self._eating_until: Optional[datetime] = None
        if self.save.schema_version < SAVE_VERSION:
            self.save.schema_version = SAVE_VERSION
            self._changed(now)

        if self.save.first_run is None:
            self.save.first_run = now
            self._changed(now)
        if self.save.last_attended is None:
            self.save.last_attended = now
            self._changed(now)
        self._roll_stats(now)
        if self.affection is not None:
            # 配置暂时失效时旧逻辑仍记摸头/零食；恢复后也不能重新领取这些额度。
            daily = self.save.affection_daily
            for source, observed in (("pat", self.save.stats["pats"]), ("snack", self.save.snacks["count"])):
                if observed > daily[source]:
                    daily[source] = observed
                    self._changed(now)
            # 初始化/恢复配置时只建立基线，不发升级事件。
            level = self.affection.level(self.save.affection)
            if self.save.affection_level != level:
                self.save.affection_level = level
                self._changed(now)

    # ------------------------------------------------------------ 查询

    def current(self, now: datetime) -> str:
        """优先级：drag > 固定/手动表情 > 临时反应 > 暂停 > working > sleep > 待机/底层。"""
        if self._dragging:
            return "drag"
        if self.save.fixed_expression:
            return self.save.fixed_expression
        if self._manual and now < self._manual[1]:
            return self._manual[0]
        if self._eating_until is not None:
            return "happy"
        if self._temp and now < self._temp[1]:
            return self._temp[0]
        if self.paused:
            return "stop"
        if self.is_working(now):
            return "working"
        if self._is_asleep(now):
            return "sleep"
        if self._resting and (not self._resting_auto or self._neglect_level(now) == 1):
            return "desk"
        if self._idle_expression and now < self._idle_expression[1]:
            return self._idle_expression[0]
        return ("idle", "neglect1", "neglect2")[self._neglect_level(now)]

    def is_working(self, now: datetime) -> bool:
        """任意一个会话在工作就算。"""
        return any(sess.active(now, self.config) for sess in self._sessions.values())

    def working_sessions(self, now: datetime) -> list[str]:
        return [key for key, sess in self._sessions.items() if sess.active(now, self.config)]

    def tool_starts(self, session: str) -> list[datetime]:
        """这个会话里还在执行的工具的开始时间。"""
        sess = self._sessions.get(session)
        return sorted(sess.tools.values()) if sess else []

    def end_session(self, session: Optional[str]) -> None:
        """这个会话的这一轮结束了（被中断 / 停太久结束）：不再算工作中，不计完成任务。"""
        self._sessions.pop(session or "", None)

    def can_idle(self, now: datetime) -> bool:
        return (
            not self._dragging and not self.is_working(now)
            and not self.paused and self.current(now) != "desk"
            and self._eating_until is None
            and not self.save.fixed_expression and not self._is_asleep(now)
            and not (self._manual and now < self._manual[1])
            and not (self._temp and now < self._temp[1])
        )

    def pending_time_speech(self, now: datetime) -> Optional[str]:
        """仅查询，不消耗资格；用真实工作/睡眠状态，避免临时表情掩盖。"""
        key = time_speech_period(now)
        if (key is None or self.is_working(now) or self.save.bubble_muted
                or self._is_asleep(now) or self.current(now) == "sleep" or self.paused):
            return None
        record = self.save.time_speech
        if record["date"] == now.date().isoformat() and key in record["spoken"]:
            return None
        return key

    def mark_time_speech_spoken(self, key: str, now: datetime) -> None:
        """控制器实际显示成功后才调用。"""
        if key != time_speech_period(now):
            return
        self._roll_stats(now)
        if key not in self.save.time_speech["spoken"]:
            self.save.time_speech["spoken"].append(key)
            self._changed(now)

    def select_expression(self, name: str, now: datetime) -> None:
        if name not in EXPRESSIONS:
            return
        self._touch(now, attend=False)
        if name in ("stop", "dizzy"):
            self._poke_count, self._last_poke = 0, None
        if self.save.fixed_expression:
            self.save.fixed_expression = name
            self._changed(now)
        else:
            self._manual = (name, now + self.config.expression_for)

    def fix_expression(self, fixed: bool, now: datetime) -> None:
        if fixed:
            name = self.current(now)
            self.save.fixed_expression = name if name in EXPRESSIONS else "idle"
        else:
            self.save.fixed_expression = None
            self._temp = None
        self._manual = None
        self._idle_expression = None
        self._changed(now)

    def idle_expression(self, name: str, now: datetime) -> None:
        if self.can_idle(now) and name in ("happy", "idle"):
            self._idle_expression = (name, now + self.config.idle_expression_for)

    # ------------------------------------------------------------ 输入

    def tick(self, now: datetime) -> list[Reaction]:
        """定时调用：清理到期的临时状态和 working，日期翻天时清零统计；返回“催你回来”等主动反应。"""
        self._roll_stats(now)
        reactions: list[Reaction] = []
        if self._resting_auto and self._neglect_level(now) != 1:
            self._resting = self._resting_auto = False
        if self._eating_until is not None and now >= self._eating_until:
            self._eating_until = None
            if self.save.snacks["count"] < self.snack_limit:
                self.save.snacks["count"] += 1
                reactions.extend(self.gain_affection("snack", now))
                self._changed(now)
        if self._temp and now >= self._temp[1]:
            self._temp = None
        for key in [k for k, sess in self._sessions.items() if not sess.active(now, self.config)]:
            del self._sessions[key]
        cfg = self.config
        if (
            self._stopped_at is not None
            and self._nudges < cfg.nudge_max
            and now - self._stopped_at >= cfg.nudge_after
            and not self._is_asleep(now)
        ):
            self._nudges += 1
            self._stopped_at = now  # 下一次提醒再隔一个 nudge_after
            reactions.append(_say("nudge"))
            reactions.append(Reaction("nudge", ""))
        self._log_state(now)
        return reactions

    def interact(self, now: datetime) -> list[Reaction]:
        """双击、菜单操作等实际操作：唤醒但不算“被理会”；悬停不调用此入口。"""
        reactions = self._touch(now, attend=False)
        self._log_state(now)
        return reactions

    @property
    def eating(self) -> bool:
        return self._eating_until is not None

    def start_snack(self, now: datetime) -> bool:
        self._roll_stats(now)
        if self.eating or self.save.snacks["count"] >= self.snack_limit:
            return False
        self._touch(now, attend=True)  # 回应由菜单提供，不另说唤醒台词
        self._eating_until = now + self.config.eating_for
        return True

    def cancel_snack(self) -> None:
        self._eating_until = None

    def menu_talk(self, now: datetime, expression: Optional[str] = None, sleep: bool = False) -> None:
        self._touch(now, attend=True)
        if sleep:
            self._menu_sleep = True
            self._temp = None
        elif expression in TEMP_STATES:
            self._set_temp(expression, now)
        elif expression in ("idle", "neglect2"):
            self._temp = (expression, now + self.config.react_for)

    def rest_at_desk(self, now: datetime, *, automatic: bool = False) -> None:
        if not automatic:
            self._touch(now, attend=True)
            self._temp = None
        self._resting = True
        self._resting_auto = automatic

    def sleep_in_bed(self, now: datetime) -> bool:
        return self._menu_sleep or (self._in_night(now) and self._is_asleep(now))

    def drag_start(self, now: datetime) -> list[Reaction]:
        reactions = self._touch(now, attend=True)
        self._dragging = True
        self._poke_count, self._last_poke = 0, None
        if not reactions:
            reactions.append(_say("drag"))
        self._log_state(now)
        return reactions

    def drag_end(self, now: datetime, shaken: bool = False) -> list[Reaction]:
        self._dragging = False
        reactions = self._touch(now, attend=True)
        if shaken:
            self._temp = ("dizzy", now + self.config.shake_dizzy_for)
            self._poke_count, self._last_poke = 0, None
            reactions.append(_say("dizzy"))
        self._log_state(now)
        return reactions

    def pat(self, now: datetime) -> list[Reaction]:
        """摸头一次（界面层累计移动 40px 算一次）。"""
        reactions = self._touch(now, attend=True)
        reactions.extend(self.gain_affection("pat", now))
        self.save.stats["pats"] += 1
        self._set_temp("happy", now)

        self._changed(now)
        self._log_state(now)
        return reactions

    def click(self, now: datetime) -> list[Reaction]:
        """单击身体一次。"""
        reactions = self._touch(now, attend=True)
        cfg = self.config
        if self._last_poke is None or now - self._last_poke > cfg.poke_gap:
            self._poke_count = 0
        self._last_poke = now
        self._poke_count += 1
        result = None
        if self._poke_count >= cfg.poke_early:
            late = self._poke_count >= cfg.poke_late
            stop = cfg.poke_late_stop if late else cfg.poke_early_stop
            dizzy = cfg.poke_late_dizzy if late else cfg.poke_early_dizzy
            if self.affection is not None:
                stop, dizzy = self.affection.probabilities(self.affection_level, stop, dizzy)
            roll = self._rng.random()
            if roll < stop:
                result = "stop"
            elif roll < round(stop + dizzy, 12):
                result = "dizzy"
        if result:
            self._poke_count, self._last_poke = 0, None
            self._set_temp(result, now)
            reactions.append(_say(result))
        elif not reactions:
            reactions.append(_say("poke"))
        self._log_state(now)
        return reactions

    def gesture(self, key: str, now: datetime) -> list[Reaction]:
        """捏脸和肚子交互不加好感度、不计普通戳或摸头。"""
        if key not in {"belly", "cheek_pull", "cheek_release", "tickle", "tickle_end"}:
            return []
        self._touch(now, attend=True)
        self._poke_count, self._last_poke = 0, None
        self._log_state(now)
        return [] if key == "belly" else [_say(key)]

    def feedback_good(self, now: datetime) -> list[Reaction]:
        """右键菜单“做得好”：加入反馈队列，等下次送达 Claude。"""
        reactions = self._touch(now, attend=False)
        if self.affection is None:
            self.save.affection += self.config.praise_affection
        self._enqueue({"kind": "good", "text": ""})
        self._set_temp("proud", now)
        self._changed(now)
        reactions.append(_say("praise_menu_working" if self.is_working(now) else "praise_menu"))
        self._log_state(now)
        return reactions

    def feedback_bad(self, text: str, now: datetime) -> list[Reaction]:
        """右键菜单“有问题”：附一句话（单行，可留空）。"""
        reactions = self._touch(now, attend=False)
        self._enqueue({"kind": "bad", "text": " ".join((text or "").split())[:FEEDBACK_TEXT_MAX]})
        self._changed(now)
        reactions.append(_say("feedback_bad_working" if self.is_working(now) else "feedback_bad"))
        return reactions

    def _enqueue(self, item: dict) -> None:
        self.save.feedback_queue.append(item)
        del self.save.feedback_queue[:-FEEDBACK_MAX]

    def take_feedback(self, now: Optional[datetime] = None) -> list:
        """读取并清空反馈队列（送达时调用）。now 用来给存档防抖计时。"""
        items = [dict(i) for i in self.save.feedback_queue]
        if items:
            self.save.feedback_queue = []
            self._changed(now or self._last_activity)
        return items

    def claude_event(self, etype: str, detail: Optional[str], now: datetime,
                     session: Optional[str] = None, tool_id: Optional[str] = None) -> list[Reaction]:
        """处理本地 HTTP 服务转来的事件。未知类型直接忽略。

        session：CC 的 session_id（旧 hook 没有，用 ""）；tool_id：PreToolUse 与 PostToolUse 配对用的 tool_use_id。
        """
        if etype not in ("session_start", "prompt", "working", "tool_done", "stop", "notification", "react",
                         "tool_error", "plan_ready"):
            log.info("忽略未知事件：%r", etype)
            return []
        if etype == "react" and detail not in TEMP_STATES:
            log.info("忽略未知表情：%r", detail)
            return []

        reactions = self._touch(now, attend=True)
        key = session or ""
        if etype in ("session_start", "prompt", "working"):
            self._stopped_at, self._nudges = None, 0  # Claude 又开始干活了，不用催
        if etype in ("prompt", "working") or (etype in ("tool_done", "tool_error") and key in self._sessions):
            was_working = self.is_working(now)
            sess = self._sessions.get(key)
            if sess is None or not sess.active(now, self.config):
                sess = self._sessions[key] = WorkSession(now)
            sess.last = now  # 有新事件就续期
            if etype == "working" and tool_id:
                sess.tools[tool_id] = now
            elif etype in ("tool_done", "tool_error"):
                sess.tools.pop(tool_id, None) if tool_id else sess.tools.clear()
            if etype == "working" and not was_working:
                reactions.append(_say("claude_working"))
        if etype == "session_start":
            reactions.append(_say("greeting"))
        elif etype == "plan_ready":
            self._sessions.pop(key, None)
            reactions.append(_say("plan_ready"))
        elif etype == "stop":
            self._sessions.pop(key, None)  # 只结束这个会话；别的会话还在工作时 done 之后回到 working
            self._stopped_at, self._nudges = now, 0
            self.save.stats["claude_tasks"] += 1
            self._set_temp("done", now)
            self._changed(now)
            reactions.append(_say("claude_done"))
        elif etype == "tool_error":
            self._poke_count, self._last_poke = 0, None
            self._temp = ("dizzy", now + self.config.tool_error_for)
            reactions.append(_say("tool_error"))
        elif etype == "notification":
            if detail == "idle_prompt":
                # CC 回复完一直在等输入：这个会话肯定不在干活（例如在提问框上按 Esc，CC 不发 PostToolUse / Stop）
                self._sessions.pop(key, None)
            reactions.append(_say("claude_waiting"))
        elif etype == "react":
            if detail in ("stop", "dizzy"):
                self._poke_count, self._last_poke = 0, None
            self._temp = (detail, now + self.config.react_for)
        self._log_state(now)
        return reactions

    # ------------------------------------------------------------ 内部

    def _touch(self, now: datetime, attend: bool) -> list[Reaction]:
        """任何交互的公共入口：翻日、唤醒、刷新“被理会”时间。"""
        self._roll_stats(now)
        was_asleep = self._is_asleep(now)
        self._menu_sleep = False
        self._resting = self._resting_auto = False
        prev_level = self._neglect_level(now)

        self._last_activity = now
        self._idle_expression = None
        if self._in_night(now):
            self._woken_date = now.date()
        if attend:
            self.save.last_attended = now
            self._changed(now)
        if attend or was_asleep:
            self._stopped_at, self._nudges = None, 0  # 用户回来了，不用再催

        if attend and prev_level == 2:
            return [_say("neglect_return")]
        if was_asleep:
            return [_say("wake")]
        return []

    def _is_asleep(self, now: datetime) -> bool:
        if self._menu_sleep:
            return True
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
        if name in ("stop", "dizzy"):
            self._poke_count, self._last_poke = 0, None
        self._temp = (name, now + self.config.temp_duration(name))

    def _roll_stats(self, now: datetime) -> None:
        today = now.date().isoformat()
        if self.save.time_speech.get("date") != today:
            self.save.time_speech = {"date": today, "spoken": []}
            self._changed(now)
        if self.save.snacks.get("date") != today:
            self.save.snacks = {"date": today, "count": 0}
            self._changed(now)
        if self.save.stats.get("date") != today:
            self.save.stats = {"date": today, "pats": 0, "claude_tasks": 0}
            self._changed(now)
        if self.affection is not None:
            daily = self.save.affection_daily
            if daily.get("date") != today:
                # 旧存档已有当天摸头/喂食记录，不重复发放额度。
                migrating = not daily
                self.save.affection_daily = {
                    "date": today, "pat": self.save.stats["pats"] if migrating else 0,
                    "snack": self.save.snacks["count"], "open": 0, "talks": [],
                }
                self._changed(now)

    @property
    def affection_level(self) -> int | None:
        return self.affection.level(self.save.affection) if self.affection is not None else None

    @property
    def snack_limit(self) -> int:
        return self.affection.daily["snack"]["limit"] if self.affection else self.config.snack_limit

    def gain_affection(self, source: str, now: datetime, ident: str = "") -> list[Reaction]:
        """成功完成的获取入口；返回至多一次升级事件，不从查询中发奖励。"""
        self._roll_stats(now)
        if self.affection is None:
            amount = {"pat": self.config.pat_affection, "snack": self.config.snack_affection}.get(source, 0)
        else:
            rule = self.affection.daily[source]
            daily = self.save.affection_daily
            if source == "talk":
                if not ident or ident in daily["talks"]:
                    return []
                daily["talks"].append(ident)
            else:
                if daily[source] >= rule["limit"]:
                    return []
                daily[source] += 1
            amount = rule["amount"]
        previous = self.affection_level
        self.save.affection += amount
        self._changed(now)
        if self.affection is not None:
            self.save.affection_level = self.affection_level
            if self.affection_level > previous:
                return [Reaction("level_up", str(self.affection_level))]
        return []

    def affection_remaining(self, now: datetime, talk_ids) -> int:
        self._roll_stats(now)
        if self.affection is None:
            return 0
        daily, rules = self.save.affection_daily, self.affection.daily
        total = sum(max(0, rules[s]["limit"] - daily[s]) * rules[s]["amount"]
                    for s in ("pat", "snack", "open"))
        return total + len(set(talk_ids) - set(daily["talks"])) * rules["talk"]["amount"]

    def _changed(self, now: datetime) -> None:
        if self._on_change:
            self._on_change(now)

    def _log_state(self, now: datetime) -> None:
        state = self.current(now)
        if state != self._last_logged:
            log.info("状态：%s → %s", self._last_logged, state)
            self._last_logged = state
