"""In-memory task chips. The caller supplies accepted events and current snapshots."""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal

from .sessions import SessionNames
from .tasks import TaskRecord

Source = Literal["claude_code", "claude_chat", "chatgpt"]
Status = Literal["waiting", "working", "done"]
WaitReason = Literal["permission", "checkpoint", "plan_ready", "need_input", "permission_unknown"]
ChipKey = tuple[str, ...]
LedgerKey = tuple[str, str, str, str]

MAX_DONE = 8
MAX_VISIBLE = 4
CHAT_KEY = ("claude_chat",)
STATUS_ORDER = {"waiting": 0, "working": 1, "done": 2}


@dataclass(frozen=True)
class BoardInputs:
    cc_working: tuple[str, ...] = ()
    cc_holding: tuple[str, ...] = ()
    cc_permissions: tuple[str | None, ...] = ()
    cc_link_enabled: bool = True
    chat_phase: str = "idle"
    ledger_tasks: Mapping[LedgerKey, TaskRecord] = field(default_factory=dict)
    ledger_ttl: float = 300.0
    private: bool = False
    ledger_now: float | None = None


@dataclass(frozen=True)
class TaskChip:
    key: ChipKey
    source: Source
    name: str
    status: Status
    started_at: float
    wait_reason: WaitReason | None
    tooltip: str


@dataclass(frozen=True)
class BoardView:
    all_chips: tuple[TaskChip, ...]
    visible_chips: tuple[TaskChip, ...]
    overflow_count: int
    show_clear_done: bool


@dataclass(frozen=True)
class _Timing:
    started_at: float
    sequence: int


@dataclass(frozen=True)
class _Row:
    key: ChipKey
    source: Source
    status: Status
    timing: _Timing
    wait_reason: WaitReason | None = None
    ended_at: float | None = None


@dataclass
class _CodexTurn:
    turn_id: str
    timing: _Timing
    ended_seen: bool = False


class TaskBoard:
    """Merge snapshots on one thread. Times use the caller's monotonic clock.

    Supply the full ledger in insertion order after its normal expiry pass.
    Chat notices come from ChatActivity.receive(), before reading its phase.
    """

    def __init__(self) -> None:
        self._sequence = 0
        self._done: OrderedDict[ChipKey, _Row] = OrderedDict()
        self._cc_active: dict[str, _Timing] = {}
        self._cc_plans: dict[str, _Timing] = {}
        self._chat_timing: _Timing | None = None
        self._chat_name: str | None = None
        self._codex_turns: dict[ChipKey, _CodexTurn] = {}
        self._codex_numbers: dict[ChipKey, int] = {}

    def _start(self, now: float) -> _Timing:
        self._sequence += 1
        return _Timing(now, self._sequence)

    def _complete(self, key: ChipKey, source: Source, timing: _Timing, now: float) -> None:
        self._done[key] = _Row(key, source, "done", timing, ended_at=now)
        if len(self._done) > MAX_DONE:
            oldest = min(self._done, key=lambda k: self._done[k].ended_at)
            del self._done[oldest]

    def note_cc_stop(self, session_id: str | None, *, ended_by_shion: bool, now: float) -> None:
        session = session_id or ""
        key = ("claude_code", session)
        timing = self._cc_active.pop(session, None) or self._cc_plans.get(session)
        self._cc_plans.pop(session, None)
        if ended_by_shion:
            self._done.pop(key, None)
        elif key not in self._done:
            self._complete(key, "claude_code", timing or self._start(now), now)

    def note_cc_plan_ready(self, session_id: str | None, *, now: float) -> None:
        """Call after CC clears the working state for plan_ready."""
        session = session_id or ""
        self._done.pop(("claude_code", session), None)
        timing = self._cc_active.pop(session, None) or self._cc_plans.get(session)
        self._cc_plans[session] = timing or self._start(now)

    def note_chat(self, notice: str | None, *, task_name: str | None = None,
                  private: bool, now: float) -> None:
        if private:
            self._chat_name = None
        if notice == "working":
            self._done.pop(CHAT_KEY, None)
            self._chat_timing = self._start(now)
            self._chat_name = None if private else task_name
        elif notice == "need_input":
            self._done.pop(CHAT_KEY, None)
            if self._chat_timing is None:
                self._chat_timing = self._start(now)
        elif notice == "done":
            if CHAT_KEY not in self._done:
                self._complete(CHAT_KEY, "claude_chat", self._chat_timing or self._start(now), now)
            self._chat_timing = None

    def dismiss_done(self, key: ChipKey) -> None:
        self._done.pop(key, None)

    def clear_done(self) -> None:
        self._done.clear()

    def dismiss_plan(self, key: ChipKey) -> None:
        if len(key) == 2 and key[0] == "claude_code":
            self._cc_plans.pop(key[1], None)

    def _cc_rows(self, inputs: BoardInputs, now: float) -> list[_Row]:
        if not inputs.cc_link_enabled:
            self._cc_active.clear()
            self._cc_plans.clear()
            return []
        working = set(inputs.cc_working)
        holding = set(inputs.cc_holding)
        permissions = {session or "" for session in inputs.cc_permissions}
        active = dict.fromkeys((*inputs.cc_working, *inputs.cc_holding,
                                *(session or "" for session in inputs.cc_permissions)))
        rows = []
        timings = {}
        for session in dict.fromkeys((*active, *self._cc_plans)):
            if session in working:
                self._cc_plans.pop(session, None)
            timing = self._cc_active.get(session) or self._cc_plans.get(session) or self._start(now)
            if session in active:
                timings[session] = timing
            reason: WaitReason | None = None
            if session in permissions:
                reason = "permission"
            elif session in holding:
                reason = "checkpoint"
            elif session in self._cc_plans:
                reason = "plan_ready"
            key = ("claude_code", session)
            self._done.pop(key, None)
            rows.append(_Row(key, "claude_code", "waiting" if reason else "working", timing, reason))
        self._cc_active = timings
        return rows

    def _chat_rows(self, phase: str, now: float) -> list[_Row]:
        if phase not in ("working", "need_input"):
            self._chat_timing = None
            if CHAT_KEY not in self._done:
                self._chat_name = None
            return []
        self._done.pop(CHAT_KEY, None)
        if self._chat_timing is None:
            self._chat_timing = self._start(now)
        if phase == "need_input":
            return [_Row(CHAT_KEY, "claude_chat", "waiting", self._chat_timing, "need_input")]
        return [_Row(CHAT_KEY, "claude_chat", "working", self._chat_timing)]

    def _codex_rows(self, inputs: BoardInputs, now: float) -> list[_Row]:
        # The observer and Qt animation clocks may have different origins on Windows.
        ledger_now = now if inputs.ledger_now is None else inputs.ledger_now
        latest: dict[ChipKey, tuple[str, TaskRecord]] = {}
        for (provider, namespace, session, turn_id), task in inputs.ledger_tasks.items():
            if provider == "chatgpt":
                latest[(provider, namespace, session)] = (turn_id, task)
        rows = []
        for key, (turn_id, task) in latest.items():
            stamp = now + (task.last - ledger_now)
            turn = self._codex_turns.get(key)
            if turn is None or turn.turn_id != turn_id:
                self._done.pop(key, None)
                turn = _CodexTurn(turn_id, self._start(stamp))
                self._codex_turns[key] = turn
            if task.state == "interrupted":
                turn.ended_seen = True
                self._done.pop(key, None)
                continue
            if task.state == "turn_ended":
                if not turn.ended_seen:
                    self._complete(key, "chatgpt", turn.timing, stamp)
                    turn.ended_seen = True
            elif (task.permission_unknown and not task.terminal
                  and task.state in ("observed_working", "uncertain")
                  and not (task.continuity_lost or task.observation_paused or task.observation_gap_at is not None
                           and task.state == "uncertain")
                  and (task.lease_supported or ledger_now - task.last < inputs.ledger_ttl)):
                rows.append(_Row(key, "chatgpt", "waiting", turn.timing, "permission_unknown"))
            elif task.state == "observed_working":
                rows.append(_Row(key, "chatgpt", "working", turn.timing))
            else:
                continue
            if key not in self._codex_numbers:
                self._codex_numbers[key] = len(self._codex_numbers) + 1
        return rows

    def snapshot(self, inputs: BoardInputs, *, now: float, session_names: SessionNames,
                 ui: Callable[..., str]) -> BoardView:
        if inputs.private:
            self._chat_name = None
        rows = self._cc_rows(inputs, now)
        rows.extend(self._chat_rows(inputs.chat_phase, now))
        rows.extend(self._codex_rows(inputs, now))
        done = [row for row in self._done.values()
                if inputs.cc_link_enabled or row.source != "claude_code"]
        rows.extend(done)
        rows.sort(key=lambda row: (STATUS_ORDER[row.status], row.timing.started_at, row.timing.sequence))
        cc_labels = session_names.labels((row.key[1] for row in rows if row.source == "claude_code"),
                                        inputs.private, ui)
        chips = tuple(self._chip(row, cc_labels, ui, now) for row in rows)
        return BoardView(chips, chips[:MAX_VISIBLE], max(0, len(chips) - MAX_VISIBLE), len(done) > 2)

    def _chip(self, row: _Row, cc_labels: Mapping[str, str], ui: Callable[..., str],
              now: float) -> TaskChip:
        source_label = ui(f"task_board_source_{row.source}")
        if row.source == "claude_code":
            name = cc_labels.get(row.key[1], source_label)
        elif row.source == "claude_chat":
            name = self._chat_name or source_label
        else:
            number = self._codex_numbers[row.key]
            name = source_label if number == 1 else f"{source_label} {number}"
        status = ui(f"task_board_state_{row.wait_reason or row.status}")
        end = now if row.ended_at is None else row.ended_at
        duration = max(0, int(end - row.timing.started_at))
        tooltip = ui("task_board_tooltip", source=source_label, name=name, state=status, seconds=duration)
        return TaskChip(row.key, row.source, name, row.status, row.timing.started_at, row.wait_reason, tooltip)
