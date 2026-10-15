"""Minimum-cost and vehicle-to-grid charging, optimised by ReFlex and kept in a plan store.

Without congestion points ReFlex optimises every charge point on its own
against the price signal, so the plan of a connection depends only on the
connection (arrival, departure, energy, plug power), the operating mode and the
day-ahead prices while it is plugged in. Each connection is therefore sent as
its own ReFlex charge point and its plan is stored under a key made of exactly
those inputs. Any later request containing the connection, from another area,
the neighbouring two-day window or another draw of an ensemble, reads the plan
instead of calling ReFlex; prices published later change the key and the
connection is optimised again.

What ReFlex 0.3.0 does, measured against the service (October 2026):

- It works on whole 10-minute intervals and charges a partly plugged interval
  at full power. It is therefore only sent the intervals a vehicle is plugged
  in from start to end; energy that does not fit there goes to the partly
  plugged edge intervals, cheapest first.
- A one-way session's end time is inclusive (the interval starting at the end
  is used), a V2X session's is exclusive. The end time sent differs accordingly.
- A session of one interval never finishes, and several sessions on one charge
  point are scheduled wrongly. Connections covering fewer than two whole
  intervals are scheduled locally (cheapest first, which is optimal for them),
  and every other connection is a charge point of its own.
- V2X plans charge at most about 95 % of the plug's power and end 1-3 % short
  of `minEnergyToCharge`; short one-way sessions on fast plugs can get whole
  intervals at full power, more than `energyToCharge`. Such a plan is adjusted
  to the exact energy, adding in the cheapest or removing in the dearest
  intervals with room, within every limit, and counted.

Every plan is checked against the plug and battery limits. One that breaks
them, or misses the energy by more than a quarter, is replaced by the exact
local solution and counted.

A request never waits for ReFlex. A connection without a stored plan gets the
exact local optimum at once (cheapest first, or one linear programme for all
V2G connections), stored as provisional, and is queued for ReFlex in a
background thread whose plan then replaces it. ReFlex plans cost 0-3 % more
than that optimum on test sessions, so the switch hardly changes a profile.
`scripts/prepare_reflex_plans.py` waits for ReFlex instead.
"""

from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, fields
from datetime import datetime, timezone
import hashlib
import logging
from pathlib import Path
import sqlite3
import threading
import time

import numpy as np
from scipy.optimize import linprog
from scipy.sparse import coo_matrix

from backend.api_calls.reflex import ReflexClient, ReflexError
from backend.day_ahead_prices import PriceStore, price_zone
from backend.scenario_profiles import point_table, point_powers
from backend.session_frame import as_frame, bin_integrals, epoch

LOG = logging.getLogger(__name__)
ENGINE_VERSION = "reflex-0.3.0/epiot-1"  # change when requests or checks change: stored plans are then redone
STEP = 600
STEP_HOURS = STEP/3600
JOULE_PER_KWH = 3.6e6
TOLERANCE_KWH = 0.003      # ReFlex returns whole joules; differences below this are rounding
MAX_ADJUSTMENT = 0.25      # largest energy difference, as a share of the energy, adjusted rather than replaced
MODES = ("ocost", "v2g")
PROVISIONAL = "provisional"   # the local optimum, until ReFlex's plan replaces it
LP_CHUNK = 200                # V2G connections per linear programme: larger ones solve more slowly
RETRY_SECONDS = 600           # a connection ReFlex failed on is not queued again before this

COST_NOTE = ("Minimum-cost schedule against day-ahead prices, optimised per connection by the DRIVE2X ReFlex "
             "service. Every connection receives the same energy as under the other strategies.")
V2G_NOTE = ("Vehicle-to-grid scenario: every connected vehicle is assumed bidirectional at the plug's power and "
            "may be discharged by up to {depth:g} kWh below its arrival charge, as long as it leaves with the "
            "same energy as under the other strategies. Optimised against day-ahead prices by DRIVE2X ReFlex; "
            "negative load is energy returned to the grid.")
PRICE_REFERENCE_NOTE = ("Day-ahead prices were not published for part of these connections; the price at the same "
                        "time on the nearest day with prices was used.")


@dataclass(frozen=True)
class CostSettings:
    v2g_depth_kwh: float = 10.   # how far below its arrival charge a V2G vehicle may be discharged
    batch_sessions: int = 300    # connections per one-way ReFlex run (about a second for 1000)
    v2g_batch_sessions: int = 10  # connections per V2X run (ReFlex needs about 3 s per V2X connection)
    parallel_runs: int = 4       # runs on the shared service at once; it runs only a few at a time
    run_timeout: float = 120.    # seconds a request waits for ReFlex
    background_timeout: float = 1800.  # seconds the background queue waits for one batch

    @classmethod
    def from_config(cls, config):
        settings = cls(float(config.get("REFLEX_V2G_DEPTH_KWH", cls.v2g_depth_kwh)),
                       int(config.get("REFLEX_BATCH_SESSIONS", cls.batch_sessions)),
                       int(config.get("REFLEX_V2G_BATCH_SESSIONS", cls.v2g_batch_sessions)),
                       int(config.get("REFLEX_PARALLEL_RUNS", cls.parallel_runs)),
                       float(config.get("REFLEX_RUN_TIMEOUT", cls.run_timeout)),
                       float(config.get("REFLEX_BACKGROUND_TIMEOUT", cls.background_timeout)))
        if not (np.isfinite(settings.v2g_depth_kwh) and settings.v2g_depth_kwh >= 0 and settings.batch_sessions > 0
                and settings.v2g_batch_sessions > 0 and settings.parallel_runs > 0 and settings.run_timeout > 0
                and settings.background_timeout > 0):
            raise ValueError("ReFlex settings must be positive")
        return settings


class PlanStore:
    """Plans by key: the first absolute 10-minute step and the power (kW) of each step from there."""

    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        try:
            with connection:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("CREATE TABLE IF NOT EXISTS plans (key TEXT PRIMARY KEY, first INTEGER NOT NULL, "
                                   "power BLOB NOT NULL, solver TEXT NOT NULL, created_at TEXT NOT NULL)")
                yield connection
        finally:
            connection.close()

    def get_many(self, keys):
        keys, found = list(dict.fromkeys(keys)), {}
        with self.connect() as connection:
            for chunk in range(0, len(keys), 500):
                part = keys[chunk:chunk+500]
                for key, first, power, solver in connection.execute(
                        f"SELECT key, first, power, solver FROM plans WHERE key IN ({','.join('?'*len(part))})", part):
                    found[key] = (first, np.frombuffer(power, np.float64), solver)
        return found

    def put_many(self, plans):
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            connection.executemany("INSERT OR REPLACE INTO plans VALUES (?,?,?,?,?)", [
                (key, int(first), np.asarray(power, np.float64).tobytes(), solver, now)
                for key, (first, power, solver) in plans.items()])


@dataclass
class Problems:
    """Per-connection arrays for one batch; steps are absolute 10-minute indices (epoch // 600)."""
    keys: list
    zone: np.ndarray
    start: np.ndarray
    end: np.ndarray
    energy: np.ndarray       # kWh to deliver
    power: np.ndarray        # kW charge limit
    discharge: np.ndarray    # kW discharge limit (0 without V2G)
    first: np.ndarray        # first step touched
    last: np.ndarray         # one past the last step touched
    full_first: np.ndarray   # whole plugged-in steps [full_first, full_last)
    full_last: np.ndarray
    prices: list             # EUR/MWh per step from `first`
    reference: np.ndarray    # some of those prices are references

    def capacity(self, index):
        """kWh the plug can take in every step of connection `index`, exact at the edges."""
        edges = np.arange(self.first[index], self.last[index]+1)*STEP
        plugged = np.clip(np.minimum(edges[1:], self.end[index])-np.maximum(edges[:-1], self.start[index]), 0, STEP)
        return self.power[index]*plugged/3600

    def whole(self, index):
        """The whole plugged-in steps, as a slice of the connection's own steps."""
        offset = self.first[index]
        return slice(self.full_first[index]-offset, self.full_last[index]-offset)

    def whole_energy(self, index):
        """What the whole steps can hold of the connection's energy."""
        return min(self.energy[index], self.power[index]*(self.full_last[index]-self.full_first[index])*STEP_HOURS)

    def subset(self, indices):
        indices = list(indices)
        return Problems(**{field.name: ([getattr(self, field.name)[i] for i in indices]
                                        if isinstance(getattr(self, field.name), list)
                                        else getattr(self, field.name)[indices]) for field in fields(self)})

    @staticmethod
    def concat(parts):
        return Problems(**{field.name: (sum((getattr(part, field.name) for part in parts), [])
                                        if isinstance(getattr(parts[0], field.name), list)
                                        else np.concatenate([getattr(part, field.name) for part in parts]))
                           for field in fields(Problems)})


def cheapest_first(prices, capacity, energy, plan=None):
    """Add charging to `plan` (kWh per step) in the cheapest steps with room until it holds `energy`.

    On its own this is the optimal one-way plan; earlier steps win ties.
    """
    plan = np.zeros(len(capacity)) if plan is None else np.array(plan, float)
    need = energy-plan.sum()
    for step in np.lexsort((np.arange(len(prices)), prices)):
        if need <= 1e-12:
            break
        add = min(capacity[step]-plan[step], need)
        if add > 0:
            plan[step] += add
            need -= add
    return plan


def v2g_lps(problems, depth):
    """Exact minimum-cost bidirectional plans (kWh per step), one linear programme for all.

    `problems` holds (prices, charge limit per step, discharge limit, energy) per
    connection. The running net energy s_t = s_t-1 + charge_t - discharge_t starts
    at 0, stays in [-depth, energy] and ends at `energy`: the limits ReFlex is given.
    The constraint matrix is sparse, so this is far faster than one programme each.
    """
    if not problems:
        return []
    sizes = np.array([len(problem[0]) for problem in problems])
    total, starts = sizes.sum(), np.concatenate([[0], np.cumsum(sizes)[:-1]])
    first = np.zeros(total, bool)
    first[starts] = True
    last = np.zeros(total, bool)
    last[starts+sizes-1] = True
    prices = np.concatenate([np.asarray(problem[0], float) for problem in problems])
    charge = np.concatenate([np.asarray(problem[1], float) for problem in problems])
    discharge = np.repeat([float(problem[2]) for problem in problems], sizes)
    energy = np.repeat([float(problem[3]) for problem in problems], sizes)
    step = np.arange(total)
    # Columns: charge, discharge, running energy; one balance row per step
    rows = np.concatenate([step, step, step, step[~first]])
    columns = np.concatenate([2*total+step, step, total+step, 2*total+step[~first]-1])
    values = np.concatenate([np.ones(total), -np.ones(total), np.ones(total), -np.ones((~first).sum())])
    balance = coo_matrix((values, (rows, columns)), shape=(total, 3*total)).tocsr()
    # A tiny throughput cost stops charging and discharging in the same step
    throughput = 1e-6*max(np.abs(prices).max(initial=0), 1)
    cost = np.concatenate([prices+throughput, -prices+throughput, np.zeros(total)])
    bounds = np.column_stack([np.concatenate([np.zeros(2*total), np.where(last, energy, -depth)]),
                              np.concatenate([charge, discharge, energy])])
    result = linprog(cost, A_eq=balance, b_eq=np.zeros(total), bounds=bounds, method="highs")
    if result.status != 0:
        raise ValueError(f"No feasible vehicle-to-grid plan: {result.message}")
    net = result.x[:total]-result.x[total:2*total]
    return [net[start:start+size] for start, size in zip(starts, sizes)]


def v2g_lp(prices, charge, discharge, energy, depth):
    """The exact plan of one connection; see v2g_lps."""
    return v2g_lps([(prices, charge, discharge, energy)], depth)[0]


def complete(plan, prices, upper, lower, energy, depth):
    """Move `plan` to net `energy` in the cheapest (or, to remove, dearest) steps with room.

    Every step stays in [lower, upper] and the running net energy in
    [-depth, energy]. Returns None if that cannot reach `energy`.
    """
    plan = np.clip(plan, lower, upper)
    difference = energy-plan.sum()
    order = np.lexsort((np.arange(len(prices)), prices))
    for step in (order if difference > 0 else order[::-1]):
        if abs(difference) <= 1e-12:
            break
        later = np.cumsum(plan)[step:]
        if difference > 0:
            change = min(upper[step]-plan[step], energy-later.max(), difference)
        else:
            change = max(lower[step]-plan[step], -depth-later.min(), difference)
        if change*difference > 0:
            plan[step] += change
            difference -= change
    return plan if abs(difference) <= 1e-9 else None


def use_edges(plan, prices, capacity, whole, energy, depth):
    """Move charging from the dearest whole steps into cheaper partly plugged edge steps.

    ReFlex never sees the edges, which are sometimes the cheapest steps of a
    connection. Running net energy stays in [-depth, energy].
    """
    plan = plan.copy()
    edges = [step for step in (whole.start-1, whole.stop) if 0 <= step < len(plan)]
    for edge in sorted(edges, key=lambda step: prices[step]):
        for step in sorted(range(whole.start, whole.stop), key=lambda step: -prices[step]):
            if prices[step] <= prices[edge]:
                break
            amount = min(capacity[edge]-plan[edge], max(plan[step], 0.))
            running = np.cumsum(plan)
            if edge < step:
                amount = min(amount, energy-running[edge:step].max())
            else:
                amount = min(amount, running[step:edge].min()+depth)
            if amount > 1e-12:
                plan[edge] += amount
                plan[step] -= amount
    return plan


class CostOptimiser:
    """Min-cost (`ocost`) and V2G (`v2g`) load profiles from the plan store, filled through ReFlex."""

    def __init__(self, plan_store, price_store, settings=CostSettings(), client_factory=None):
        self.plans = plan_store
        self.prices = price_store
        self.settings = settings
        self.client_factory = client_factory or (lambda: ReflexClient(run_timeout=settings.run_timeout))
        # Background queue: (mode, Problems) batches waiting for ReFlex, and their keys
        self.condition = threading.Condition()
        self.waiting = []
        self.queued = set()
        self.busy = False
        self.retry_after = {}
        self.worker = None

    def depth(self, mode):
        return self.settings.v2g_depth_kwh if mode == "v2g" else 0.

    # Problems -------------------------------------------------------------------------------
    def problems(self, chargers, frame, mode):
        """Arrays for `frame`, whose points must all be in `chargers`, and how many lack a price zone."""
        chargers = point_table(chargers)
        power = point_powers(chargers, frame.cp_id)
        countries = {int(charger["id"]): charger.get("country") for charger in chargers}
        zones = [price_zone(countries.get(int(cp_id))) for cp_id in frame.cp_id]
        zone = np.array([z for z, _ in zones], object)
        discharge = power if mode == "v2g" else np.zeros(len(power))
        energy = np.minimum(frame.energy_kwh, power*(frame.end-frame.start)/3600)
        first = np.floor(frame.start/STEP).astype(np.int64)
        last = np.ceil(frame.end/STEP).astype(np.int64)
        full_first = np.ceil(frame.start/STEP).astype(np.int64)
        full_last = np.maximum(np.floor(frame.end/STEP).astype(np.int64), full_first)
        prices, reference = [None]*len(frame), np.zeros(len(frame), bool)
        for name in sorted(set(zone)):
            members = np.flatnonzero(zone == name)
            left, right = first[members].min(), last[members].max()
            values, flags = self.prices.prices(name, int(left), int(right-left))
            for index in members:
                part = slice(first[index]-left, last[index]-left)
                prices[index] = values[part]
                reference[index] = flags[part].any()
        keys = [hashlib.sha256(repr((ENGINE_VERSION, mode, zone[i], float(frame.start[i]), float(frame.end[i]),
                                     round(float(energy[i]), 9), float(power[i]), float(discharge[i]),
                                     self.depth(mode), np.round(prices[i], 3).tolist())).encode()).hexdigest()[:32]
                for i in range(len(frame))]
        return Problems(keys, zone, frame.start, frame.end, energy, power, discharge, first, last,
                        full_first, full_last, prices, reference), sum(stand_in for _, stand_in in zones)

    # Solving --------------------------------------------------------------------------------
    def local_plans(self, problems, indices, mode):
        """The exact optimum computed here, per connection: cheapest first, or linear programmes with V2G."""
        plans = {index: np.zeros(len(problems.capacity(index))) for index in indices}
        if mode == "v2g":
            bidirectional = [index for index in indices if problems.full_last[index]-problems.full_first[index] >= 2]
            for chunk in range(0, len(bidirectional), LP_CHUNK):
                members = bidirectional[chunk:chunk+LP_CHUNK]
                whole = [problems.whole(index) for index in members]
                solved = v2g_lps([(problems.prices[index][part], problems.capacity(index)[part],
                                   problems.discharge[index]*STEP_HOURS, problems.whole_energy(index))
                                  for index, part in zip(members, whole)], self.settings.v2g_depth_kwh)
                for index, part, net in zip(members, whole, solved):
                    plans[index][part] = net
        return {index: cheapest_first(problems.prices[index], problems.capacity(index), problems.energy[index], plan)
                for index, plan in plans.items()}

    def local_plan(self, problems, index, mode):
        return self.local_plans(problems, [index], mode)[index]

    def reflex_request(self, problems, members, mode):
        """One ReFlex run for connections of one zone; returns the query and its first step."""
        left = int(problems.full_first[members].min())
        right = int(problems.full_last[members].max())
        stamp = lambda step: datetime.fromtimestamp(step*STEP, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        prices = np.full(right-left, np.nan)
        points = []
        for index in members:
            low, high = problems.full_first[index], problems.full_last[index]
            prices[low-left:high-left] = problems.prices[index][problems.whole(index)]
            energy = round(problems.whole_energy(index)*JOULE_PER_KWH)
            # One-way sessions end inclusively in ReFlex 0.3.0, V2X sessions exclusively
            session = {"startTime": stamp(low), "endTime": stamp(high if mode == "v2g" else high-1),
                       "energyToCharge": energy}
            point = {"id": problems.keys[index], "minChargePower": 0,
                     "maxChargePower": round(problems.power[index]*1000), "chargeSessions": [session]}
            if mode == "v2g":
                point.update(minDischargePower=0, maxDischargePower=round(problems.discharge[index]*1000))
                session.update(minEnergyToCharge=energy,
                               minEnergyDuringCharging=-round(self.settings.v2g_depth_kwh*JOULE_PER_KWH))
            points.append(point)
        # A step no connection of the run covers keeps the price before it: no device uses it, and
        # ReFlex allows no price target after a noTarget element
        prices = prices[np.maximum.accumulate(np.where(np.isfinite(prices), np.arange(len(prices)), 0))]
        query = {"runType": "singleRunConfig", "congestionPoints": [],
                 "globalTarget": {"start": stamp(left), "timeStepDuration": "PT10M",
                                  "elements": [{"targetType": "price", "value": float(value)} for value in prices]},
                 "assets": {"evChargePoints": points, "nonFlexibleAssets": []}}
        return query, left

    def accept(self, problems, index, values, left, mode):
        """(plan, kWh adjusted) from what ReFlex returned for one connection, or None if it breaks a limit."""
        low, high = problems.full_first[index], problems.full_last[index]
        try:
            joules = np.asarray(values, float)
        except (TypeError, ValueError):
            return None
        if joules.ndim != 1 or len(joules) < high-left or not np.isfinite(joules).all():
            return None
        energy = joules/JOULE_PER_KWH
        inside = np.zeros(len(energy), bool)
        inside[low-left:high-left] = True
        part, target, depth = energy[inside], problems.whole_energy(index), self.depth(mode)
        running = np.cumsum(part)
        charge, discharge = problems.power[index]*STEP_HOURS, problems.discharge[index]*STEP_HOURS
        if (np.abs(energy[~inside]).max(initial=0) > TOLERANCE_KWH or (part > charge+TOLERANCE_KWH).any()
                or (part < -discharge-TOLERANCE_KWH).any() or (running < -depth-TOLERANCE_KWH).any()
                or abs(running[-1]-target) > MAX_ADJUSTMENT*target+TOLERANCE_KWH):
            return None
        capacity, prices, whole = problems.capacity(index), problems.prices[index], problems.whole(index)
        settled = complete(part, prices[whole], capacity[whole], np.full(len(part), -discharge), target, depth)
        # The running energy may never pass what the vehicle leaves with (the battery is full there)
        if settled is None or (np.cumsum(settled) > target+1e-9).any():
            return None
        plan = np.zeros(len(capacity))
        plan[whole] = settled
        # Energy that did not fit the whole steps goes to the partly plugged edges, as do cheaper hours
        plan = cheapest_first(prices, capacity, problems.energy[index], plan)
        plan = use_edges(plan, prices, capacity, whole, problems.energy[index], depth)
        return plan, abs(target-running[-1])

    def reflex_able(self, problems, indices, mode):
        """The connections ReFlex can take: at least two whole intervals and something to do."""
        whole = problems.full_last-problems.full_first
        return [i for i in indices if whole[i] >= 2 and (mode == "v2g" or problems.energy[i] > 1e-6)]

    def solve(self, problems, indices, mode, counts, timeout=None):
        """Store plans for connections that have none: ReFlex for those it can take, locally for the rest."""
        sent = self.reflex_able(problems, indices, mode)
        local = sorted(set(indices)-set(sent))
        if local:
            plans = self.local_plans(problems, local, mode)
            self.store(problems, {problems.keys[i]: (plans[i], "local") for i in local})
        if not sent:
            return
        size = self.settings.v2g_batch_sessions if mode == "v2g" else self.settings.batch_sessions
        batches = []
        for name in sorted(set(problems.zone[sent])):
            members = sorted((i for i in sent if problems.zone[i] == name), key=lambda i: problems.full_first[i])
            batches += [members[chunk:chunk+size] for chunk in range(0, len(members), size)]
        requests = [self.reflex_request(problems, members, mode) for members in batches]

        def received(run, results):
            plans = results.get("devicePlans") if isinstance(results, dict) else None
            if not isinstance(plans, dict):
                raise ReflexError("ReFlex returned no devicePlans")
            done = {}
            for index in batches[run]:
                key = problems.keys[index]
                accepted = self.accept(problems, index, plans.get(key), requests[run][1], mode)
                if accepted is None:
                    done[key] = (self.local_plan(problems, index, mode), "local-fallback")
                    counts["replaced"] += 1
                else:
                    plan, adjustment = accepted
                    done[key] = (plan, "reflex-adjusted" if adjustment > TOLERANCE_KWH else "reflex")
                    counts["optimised"] += 1
            self.store(problems, done)

        client = self.client_factory()
        if timeout is not None and hasattr(client, "run_timeout"):
            client.run_timeout = timeout
        client.run_many([query for query, _ in requests], received, parallel=self.settings.parallel_runs)

    # Background queue ----------------------------------------------------------------------
    def enqueue(self, problems, indices, mode):
        """Queue connections for ReFlex unless already queued or recently failed; returns how many."""
        now = time.monotonic()
        with self.condition:
            fresh = [i for i in dict.fromkeys(indices) if (mode, problems.keys[i]) not in self.queued
                     and self.retry_after.get(problems.keys[i], 0) <= now]
            fresh = list({problems.keys[i]: i for i in fresh}.values())
            if not fresh:
                return 0
            self.waiting.append((mode, problems.subset(fresh)))
            self.queued.update((mode, problems.keys[i]) for i in fresh)
            if self.worker is None or not self.worker.is_alive():
                self.worker = threading.Thread(target=self._work, name="reflex-queue", daemon=True)
                self.worker.start()
            self.condition.notify_all()
        return len(fresh)

    def _work(self):
        while True:
            with self.condition:
                while not self.waiting:
                    self.condition.wait()
                mode = self.waiting[0][0]
                batch = [problems for queued_mode, problems in self.waiting if queued_mode == mode]
                self.waiting = [item for item in self.waiting if item[0] != mode]
                self.busy = True
            problems = Problems.concat(batch)
            try:
                # Another request or process may have stored ReFlex's plan meanwhile
                stored = self.plans.get_many(problems.keys)
                todo = [i for i, key in enumerate(problems.keys) if stored.get(key, (0, 0, PROVISIONAL))[2] == PROVISIONAL]
                if todo:
                    self.solve(problems, todo, mode, Counter(), timeout=self.settings.background_timeout)
            except Exception:  # noqa: BLE001 - the queue must survive any failure; it is logged
                LOG.exception("ReFlex background optimisation of %d connections failed", len(problems.keys))
                until = time.monotonic()+RETRY_SECONDS
                with self.condition:
                    self.retry_after.update((key, until) for key in problems.keys)
            finally:
                with self.condition:
                    self.queued.difference_update((mode, key) for key in problems.keys)
                    self.busy = False
                    self.condition.notify_all()

    def wait_idle(self, timeout=None):
        """Block until the background queue is empty (tests and scripts); True if it is."""
        deadline = None if timeout is None else time.monotonic()+timeout
        with self.condition:
            while self.waiting or self.busy:
                remaining = None if deadline is None else deadline-time.monotonic()
                if remaining is not None and remaining <= 0:
                    return False
                self.condition.wait(remaining)
        return True

    def store(self, problems, plans):
        position = {key: index for index, key in enumerate(problems.keys)}
        self.plans.put_many({key: (problems.first[position[key]], plan/STEP_HOURS, solver)
                             for key, (plan, solver) in plans.items()})

    # Profiles -------------------------------------------------------------------------------
    def profiles(self, chargers, draws, start, end, mode, *, background=False):
        """(load, up, down) in kW per window step for each draw, and what it took to get them.

        `draws` is a list of SessionFrames (or session records). Plans are read
        from the store; the missing ones are optimised together, once. With
        `background`, missing plans are the exact local optimum, stored as
        provisional and queued for ReFlex, so nothing waits on the service;
        otherwise ReFlex is awaited. Each connection is followed from its true
        arrival to its true departure and the window only crops its plan.
        """
        if mode not in MODES:
            raise ValueError("Unsupported cost strategy")
        frames = [as_frame(draw) for draw in draws]
        combined = frames[0] if len(frames) == 1 else type(frames[0]).concat(frames)
        count = int((end-start).total_seconds()/STEP)
        # Only connections that reach into the window, on selected points, are needed
        left, right = epoch(start), epoch(end)
        needed = ((combined.end > left) & (combined.start < right)
                  & ~np.isnan(point_powers(point_table(chargers), combined.cp_id)))
        kept = combined.select(needed)
        draw_of = np.repeat(np.arange(len(frames)), [len(frame) for frame in frames])[needed]
        problems, stand_ins = self.problems(chargers, kept, mode)
        stored = self.plans.get_many(problems.keys)
        counts = Counter()
        missing = {}
        for index, key in enumerate(problems.keys):
            # Waiting for ReFlex also replaces the provisional plans of earlier requests
            if key not in stored or (not background and stored[key][2] == PROVISIONAL):
                missing.setdefault(key, index)
        if missing and background:
            indices = list(missing.values())
            sendable = set(self.reflex_able(problems, indices, mode))
            plans = self.local_plans(problems, indices, mode)
            self.store(problems, {problems.keys[i]: (plans[i], PROVISIONAL if i in sendable else "local")
                                  for i in indices})
            stored.update(self.plans.get_many(missing))
        elif missing:
            self.solve(problems, list(missing.values()), mode, counts)
            stored.update(self.plans.get_many(missing))
        provisional = [i for i, key in enumerate(problems.keys) if stored[key][2] == PROVISIONAL]
        if provisional and background:
            self.enqueue(problems, provisional, mode)
        base = int(left//STEP)
        output = []
        for draw in range(len(frames)):
            members = np.flatnonzero(draw_of == draw)
            plans = [stored[problems.keys[index]] for index in members]
            steps = np.concatenate([np.arange(first, first+len(power)) for first, power, _ in plans]+[[]])-base
            values = np.concatenate([power for _, power, _ in plans]+[[]])
            inside = (steps >= 0) & (steps < count)
            load = np.bincount(steps[inside].astype(np.int64), values[inside], count)
            relative_start, relative_end = kept.start[members]-left, kept.end[members]-left
            available = bin_integrals(relative_start, relative_end, problems.power[members], count, STEP)
            returnable = bin_integrals(relative_start, relative_end, problems.discharge[members], count, STEP)
            # Instantaneous headroom around the schedule, not a firm flexibility offer
            output.append((load.tolist(), np.maximum(available-load, 0).tolist(), (-returnable-load).tolist()))
        unique = list(dict.fromkeys(problems.keys))
        solvers = Counter(stored[key][2] for key in unique)
        summary = dict(engine="DRIVE2X ReFlex", engine_version=ENGINE_VERSION, connections=len(unique),
                       from_store=len(unique)-len(missing), optimised_now=counts["optimised"],
                       by_reflex=solvers["reflex"]+solvers["reflex-adjusted"],
                       energy_adjusted=solvers["reflex-adjusted"], scheduled_locally=solvers["local"],
                       reflex_plans_replaced=solvers["local-fallback"], reflex_pending=solvers[PROVISIONAL],
                       price_zones=dict(Counter(problems.zone.tolist())), price_zone_stand_ins=int(stand_ins),
                       prices_use_reference=bool(problems.reference.any()))
        if mode == "v2g":
            summary["v2g_depth_kwh"] = self.settings.v2g_depth_kwh
        return output, summary


def cost_optimiser(app):
    """The application's optimiser, with its plan and price stores in the instance folder."""
    optimiser = app.extensions.get("cost_optimiser")
    if optimiser is None:
        instance = Path(app.instance_path)
        optimiser = CostOptimiser(
            PlanStore(app.config.get("REFLEX_PLAN_STORE", instance/"reflex_plans.sqlite")),
            PriceStore(app.config.get("DAY_AHEAD_PRICE_STORE", instance/"day_ahead_prices.sqlite")),
            CostSettings.from_config(app.config))
        app.extensions["cost_optimiser"] = optimiser
    return optimiser
