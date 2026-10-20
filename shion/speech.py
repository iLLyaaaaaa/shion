"""气泡的时间与仲裁规则；只依赖传入的单调时钟，不依赖 Qt。"""
from enum import IntEnum

CHAR_INTERVAL = 0.030
HOLD = 4.0
FADE = 0.3
LOW_MIN_VISIBLE = 2.5
LOW_CATEGORY_COOLDOWN = 4.0
PAT_SESSION_GAP = 1.0
PAT_REPEAT_AFTER = 6.0


class Priority(IntEnum):
    LOW = 0
    MEDIUM = 1
    HIGH = 2


HIGH_KEYS = {"claude_done", "tool_error", "nudge", "claude_waiting", "permission_request", "plan_ready"}
MEDIUM_KEYS = {
    "intro", "startup", "greeting", "wake", "neglect_return", "praise_menu",
    "feedback_sent", "feedback_bad", "resumed",
    "cheek_release", "tickle_end",
}


def speech_kind(key: str) -> tuple[Priority, str]:
    if key in HIGH_KEYS:
        return Priority.HIGH, key
    if key in MEDIUM_KEYS:
        return Priority.MEDIUM, key
    # 同一次戳的台词类别会随表情变化，冷却仍按同一个触发来源算。
    return Priority.LOW, "poke" if key in {"poke", "stop", "dizzy"} else key


class SpeechGate:
    def __init__(self):
        self.priority = Priority.LOW
        self.started = 0.0
        self.until = 0.0
        self.last_low: dict[str, float] = {}
        self.sticky = False  # 正在显示的是不会自己消失的“暂停中”

    def allows(self, now: float, priority: Priority, category: str) -> bool:
        if priority == Priority.HIGH:
            return True
        if priority == Priority.LOW:
            last = self.last_low.get(category)
            if last is not None and now - last < LOW_CATEGORY_COOLDOWN:
                return False
        if now < self.until:
            if self.priority >= Priority.MEDIUM:
                return False
            if priority == Priority.LOW and now - self.started < LOW_MIN_VISIBLE:
                return False
        return True

    def start(self, now: float, text: str, priority: Priority, category: str,
              sticky: bool = False) -> bool:
        if not text or not self.allows(now, priority, category):
            return False
        # “暂停中”一直挂着，但别的台词可以盖掉它，所以按低优先级占位
        self.priority, self.started, self.sticky = (Priority.LOW if sticky else priority), now, sticky
        self.until = float("inf") if sticky else (
            now + len(text.replace("\r\n", "\n")) * CHAR_INTERVAL + HOLD + FADE)
        if priority == Priority.LOW:
            self.last_low[category] = now
        return True

    def dismiss(self) -> None:
        self.until = 0.0
        self.sticky = False


class PatSession:
    """每个连续摸头过程只在开始和持续超过阈值时各尝试说一句，不排队。"""

    def __init__(self):
        self.last: float | None = None
        self.started = 0.0
        self.repeated = False
        self.new_session = False

    def feed(self, now: float) -> bool:
        new = self.last is None or now - self.last > PAT_SESSION_GAP
        self.new_session = new
        self.last = now
        if new:
            self.started, self.repeated = now, False
            return True
        if not self.repeated and now - self.started > PAT_REPEAT_AFTER:
            self.repeated = True
            return True
        return False
