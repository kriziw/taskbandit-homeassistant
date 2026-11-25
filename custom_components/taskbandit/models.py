"""Parsed TaskBandit state snapshot."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from homeassistant.util import dt as dt_util


@dataclass(frozen=True, slots=True)
class Member:
    """A household member."""

    id: str
    display_name: str
    role: str | None
    points: int
    streak: int
    open_chores: int
    overdue_chores: int
    due_today: int
    presence: str | None


@dataclass(frozen=True, slots=True)
class Chore:
    """An open chore due by the end of today."""

    id: str
    title: str
    group: str | None
    assignee_id: str | None
    due_at: datetime | None
    overdue: bool
    state: str | None
    requires_photo: bool
    points: int


@dataclass(frozen=True, slots=True)
class Goal:
    """The active family goal."""

    id: str | None
    title: str
    points: int
    target_points: int
    progress: float


@dataclass(frozen=True, slots=True)
class Routine:
    """A routine."""

    id: str
    name: str
    enabled: bool


@dataclass(slots=True)
class TaskBanditState:
    """The whole snapshot from `GET /state`."""

    household_id: str
    household_name: str
    timezone: str | None
    server_version: str | None
    presence_enabled: bool
    members: dict[str, Member] = field(default_factory=dict)
    chores: list[Chore] = field(default_factory=list)
    goal: Goal | None = None
    routines: dict[str, Routine] = field(default_factory=dict)
    updated_at: datetime | None = None

    def chores_for(self, member_id: str | None) -> list[Chore]:
        """Chores assigned to a member, or the unassigned ones for None."""
        return [chore for chore in self.chores if chore.assignee_id == member_id]

    def chore(self, chore_id: str) -> Chore | None:
        """Find a chore by id."""
        return next((chore for chore in self.chores if chore.id == chore_id), None)

    @property
    def overdue_count(self) -> int:
        """Number of overdue chores."""
        return sum(1 for chore in self.chores if chore.overdue)

    @property
    def due_today_count(self) -> int:
        """Number of chores due later today (not yet overdue)."""
        return sum(1 for chore in self.chores if not chore.overdue)


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return dt_util.parse_datetime(value)
    except ValueError:
        return None


def parse_state(data: dict[str, Any]) -> TaskBanditState:
    """Parse a `/state` response. Raises ValueError when it has no household."""
    household = data.get("household")
    if not isinstance(household, dict) or not _str(household.get("id")):
        raise ValueError("The TaskBandit snapshot has no household id")

    members: dict[str, Member] = {}
    for raw in data.get("members") or []:
        if not isinstance(raw, dict) or not _str(raw.get("id")):
            continue
        members[raw["id"]] = Member(
            id=raw["id"],
            display_name=_str(raw.get("displayName")) or raw["id"],
            role=_str(raw.get("role")),
            points=_int(raw.get("points")),
            streak=_int(raw.get("streak")),
            open_chores=_int(raw.get("openChores")),
            overdue_chores=_int(raw.get("overdueChores")),
            due_today=_int(raw.get("dueToday")),
            presence=_str(raw.get("presence")),
        )

    chores: list[Chore] = []
    for raw in data.get("chores") or []:
        if not isinstance(raw, dict) or not _str(raw.get("id")):
            continue
        chores.append(
            Chore(
                id=raw["id"],
                title=_str(raw.get("title")) or raw["id"],
                group=_str(raw.get("group")),
                assignee_id=_str(raw.get("assigneeId")),
                due_at=_datetime(raw.get("dueAt")),
                overdue=bool(raw.get("overdue")),
                state=_str(raw.get("state")),
                requires_photo=bool(raw.get("requiresPhoto")),
                points=_int(raw.get("points")),
            )
        )

    goal: Goal | None = None
    raw_goal = data.get("goal")
    if isinstance(raw_goal, dict):
        target = _int(raw_goal.get("targetPoints"))
        points = _int(raw_goal.get("points"))
        progress = raw_goal.get("progress")
        if isinstance(progress, bool) or not isinstance(progress, (int, float)):
            progress = points / target if target else 0.0
        goal = Goal(
            id=_str(raw_goal.get("id")),
            title=_str(raw_goal.get("title")) or "",
            points=points,
            target_points=target,
            progress=float(progress),
        )

    routines: dict[str, Routine] = {}
    for raw in data.get("routines") or []:
        if not isinstance(raw, dict) or not _str(raw.get("id")):
            continue
        routines[raw["id"]] = Routine(
            id=raw["id"],
            name=_str(raw.get("name")) or raw["id"],
            enabled=bool(raw.get("enabled", True)),
        )

    return TaskBanditState(
        household_id=household["id"],
        household_name=_str(household.get("name")) or "TaskBandit",
        timezone=_str(household.get("timezone")),
        server_version=_str(data.get("serverVersion")),
        presence_enabled=bool(data.get("presenceEnabled")),
        members=members,
        chores=chores,
        goal=goal,
        routines=routines,
        updated_at=_datetime(data.get("updatedAt")),
    )
