"""Columnar charging sessions and exact interval integration on time grids.

Scenario requests can cover thousands of points, so sessions travel as numpy
columns (UTC epoch seconds) rather than one Python object per connection.
`records()` converts to `ScenarioSession` objects for code that needs them.
"""

from dataclasses import dataclass
from datetime import datetime

import numpy as np

from backend.scenario_sampling import UTC, ScenarioSession


def epoch(value):
    if value.utcoffset() is None:
        raise ValueError("Session windows require timezone-aware timestamps")
    return value.timestamp()


@dataclass(frozen=True, eq=False)
class SessionFrame:
    cp_id: np.ndarray
    start: np.ndarray
    end: np.ndarray
    energy_kwh: np.ndarray

    def __post_init__(self):
        columns = [np.asarray(self.cp_id, np.int64), *(np.asarray(getattr(self, name), float)
                                                      for name in ("start", "end", "energy_kwh"))]
        if len({len(column) for column in columns}) > 1:
            raise ValueError("Session columns must have equal lengths")
        for name, column in zip(("cp_id", "start", "end", "energy_kwh"), columns):
            object.__setattr__(self, name, column)
        if len(self) and not (np.isfinite(self.start).all() and (self.end > self.start).all()
                              and np.isfinite(self.energy_kwh).all() and (self.energy_kwh >= 0).all()):
            raise ValueError("Sessions require increasing timestamps and finite nonnegative energy")

    def __len__(self):
        return len(self.cp_id)

    @classmethod
    def empty(cls):
        return cls(np.zeros(0, np.int64), np.zeros(0), np.zeros(0), np.zeros(0))

    @classmethod
    def from_records(cls, records):
        if isinstance(records, cls):
            return records
        records = list(records)
        return cls(np.array([record.cp_id for record in records], np.int64),
                   np.array([epoch(record.start) for record in records], float),
                   np.array([epoch(record.end) for record in records], float),
                   np.array([record.energy_kwh for record in records], float))

    @classmethod
    def concat(cls, frames):
        frames = [frame for frame in frames if len(frame)]
        if not frames:
            return cls.empty()
        return cls(*(np.concatenate([getattr(frame, name) for frame in frames])
                     for name in ("cp_id", "start", "end", "energy_kwh")))

    def select(self, mask):
        return SessionFrame(self.cp_id[mask], self.start[mask], self.end[mask], self.energy_kwh[mask])

    def sorted(self):
        return self.select(np.lexsort((self.end, self.start, self.cp_id)))

    def overlapping(self, left, right):
        """Sessions connected at some time in [left, right), as epoch seconds."""
        return self.select((self.start < right) & (self.end > left))

    def records(self):
        stamp = datetime.fromtimestamp
        return [ScenarioSession(int(cp_id), stamp(start, UTC), stamp(end, UTC), float(energy))
                for cp_id, start, end, energy in zip(self.cp_id, self.start, self.end, self.energy_kwh)]

    def equals(self, other):
        return all(np.array_equal(getattr(self, name), getattr(other, name))
                   for name in ("cp_id", "start", "end", "energy_kwh"))


def as_frame(sessions):
    return sessions if isinstance(sessions, SessionFrame) else SessionFrame.from_records(sessions)


def bin_integrals(left, right, weight, count, step, rows=None, row_count=1):
    """Sum of weight*overlap/step per grid bin, for intervals relative to the grid start.

    Bins are [i*step, (i+1)*step). An interval fully covering a bin adds its
    weight; partial overlaps add their exact fraction. Fully interior bins use a
    difference array, so the cost is linear in intervals plus bins.
    """
    rows = np.zeros(len(left), np.int64) if rows is None else np.asarray(rows, np.int64)
    span = count*step
    left = np.clip(np.asarray(left, float), 0., span)
    right = np.clip(np.asarray(right, float), 0., span)
    weight = np.broadcast_to(np.asarray(weight, float), left.shape)
    keep = right > left
    left, right, weight, rows = left[keep], right[keep], weight[keep], rows[keep]
    first = np.minimum((left//step).astype(np.int64), count-1)
    last = np.minimum(np.ceil(right/step).astype(np.int64)-1, count-1)
    size = row_count*count
    single = first == last
    output = np.bincount(rows[single]*count+first[single], weight[single]*(right-left)[single]/step, size).astype(float)
    many = ~single
    if many.any():
        f, l, w, r = first[many], last[many], weight[many], rows[many]
        output += np.bincount(r*count+f, w*((f+1)*step-left[many])/step, size)
        output += np.bincount(r*count+l, w*(right[many]-l*step)/step, size)
        # Interior bins f+1..l-1 carry the full weight. Each interval opens and
        # closes inside its own row, so the running sum never crosses rows.
        delta = np.bincount(r*count+f+1, w, size+1)-np.bincount(r*count+l, w, size+1)
        output += np.cumsum(delta)[:-1]
    return output.reshape(row_count, count) if row_count > 1 else output
