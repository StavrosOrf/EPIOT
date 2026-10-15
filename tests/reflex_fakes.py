"""Stand-ins for ReFlex and Energy-Charts that behave like the real services, without a network."""

from datetime import datetime, timedelta, timezone
import math

import numpy as np

from backend.cost_charging import STEP_HOURS, CostOptimiser, CostSettings, PlanStore, v2g_lp
from backend.day_ahead_prices import PriceStore

UTC = timezone.utc


def parse(stamp):
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def price_at(unix):
    """A smooth daily price curve with an evening peak, in EUR/MWh."""
    hour = (unix % 86400)/3600
    return 60+50*math.sin((hour-11)/24*2*math.pi)+10*math.cos(unix/86400)


class PriceFeed:
    """Quarter-hourly prices up to and including `published`, like Energy-Charts; counts its calls."""

    def __init__(self, published=datetime(2026, 10, 16, tzinfo=UTC)):
        self.published = published
        self.calls = []

    def __call__(self, zone, start, end):
        self.calls.append((zone, start, end))
        stop = min(end, self.published+timedelta(days=1)-timedelta(minutes=1))
        first = int(start.timestamp())//900*900
        return [(unix, price_at(unix)) for unix in range(first, int(stop.timestamp())+1, 900)]


class FakeReflex:
    """Answers like ReFlex 0.3.0 does, measured against the service.

    One-way sessions charge the cheapest intervals from start to end inclusive;
    V2X sessions use start to end exclusive, get the exact optimum and end 3 %
    short of their energy. `distort(point, plan)` changes a plan before it is
    returned. Use the instance as the optimiser's client factory.
    """

    def __init__(self, distort=None, shortfall=0.03):
        self.distort = distort
        self.shortfall = shortfall
        self.queries = []

    def __call__(self):
        return self

    def run_many(self, queries, on_result, *, parallel=8):
        self.queries.extend(queries)
        for index, query in enumerate(queries):
            on_result(index, self.answer(query))

    def answer(self, query):
        target = query["globalTarget"]
        start = parse(target["start"])
        prices = np.array([element["value"] for element in target["elements"]])
        plans = {}
        for point in query["assets"]["evChargePoints"]:
            (session,) = point["chargeSessions"]
            v2x = "maxDischargePower" in point
            low = int((parse(session["startTime"])-start).total_seconds()//600)
            high = int((parse(session["endTime"])-start).total_seconds()//600)+(0 if v2x else 1)
            charge = point["maxChargePower"]*600
            plan = np.zeros(len(prices))
            if v2x:
                kwh = v2g_lp(prices[low:high], np.full(high-low, charge/3.6e6), point["maxDischargePower"]/1000*STEP_HOURS,
                             session["minEnergyToCharge"]/3.6e6, -session["minEnergyDuringCharging"]/3.6e6)
                plan[low:high] = np.round(kwh*3.6e6*(1-self.shortfall))
            else:
                need = session["energyToCharge"]
                for step in sorted(range(low, high), key=lambda step: (prices[step], step)):
                    plan[step] = min(charge, need)
                    need -= plan[step]
            if self.distort:
                plan = self.distort(point, plan)
            plans[point["id"]] = plan.tolist()
        return {"profileStart": target["start"], "timeStepSize": "PT10M", "devicePlans": plans}


def optimiser(tmp_path, reflex=None, feed=None, **settings):
    """A CostOptimiser on temporary stores, the fake price feed and a fake (or given) ReFlex."""
    prices = PriceStore(tmp_path/"prices.sqlite", fetch=feed or PriceFeed(),
                        clock=lambda: datetime(2026, 10, 15, 12, tzinfo=UTC).timestamp())
    return CostOptimiser(PlanStore(tmp_path/"plans.sqlite"), prices, CostSettings(**settings),
                         client_factory=reflex or FakeReflex())
