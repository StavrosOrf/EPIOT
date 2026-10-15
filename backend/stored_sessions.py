"""Stored charging sessions as input to the same engine the scenario sources use.

The `sessions` table holds local, timezone-free timestamps. Everything the
engine does (profiles, flexibility, KPIs) works on UTC instants, so a stored
session is interpreted in the application's local timezone and converted once,
here.
"""

from sqlalchemy import select

from backend.models import Session
from backend.scenario_sampling import UTC, ScenarioSession

STORED_LABEL = "Stored sessions"
STORED_NOTE = "Stored session dataset; local charging observations are not verified."


def stored_records(db_session, ids, left, right, zone):
    """Sessions of these charging points connected at some time in [left, right).

    `left` and `right` are naive local datetimes, like the stored timestamps.
    The comparison is a plain range test on (cp_id, start), so the session
    indexes apply. Rows with missing or inconsistent values are dropped.
    """
    rows = db_session.execute(
        select(Session.cp_id, Session.start, Session.end, Session.consumption)
        .where(Session.cp_id.in_(ids), Session.start < right, Session.end > left)).all()
    return [ScenarioSession(cp_id, start.replace(tzinfo=zone).astimezone(UTC),
                            end.replace(tzinfo=zone).astimezone(UTC), float(energy or 0))
            for cp_id, start, end, energy in rows
            if start and end and end > start and (energy or 0) >= 0]
