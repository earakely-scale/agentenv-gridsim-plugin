"""The desk price forecast hook (contract 8.4): P10/P50/P90 vintages of DAM and RT SPP, as issued, never ahead of now.

`SeriesForecaster` reads the data lane's `desk_forecast` vintages; `NaiveForecaster` is the labelled fallback built only
from posted prices. Both give dense views on the episode grid (DAM hourly, RT 15-minute) through `views`."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from gridsim_core.desk import clock
from gridsim_core.desk.ancillary import RT_DA_RATIO
from gridsim_core.desk.data import Series, Vintage, posted_part

QS = ("p10", "p50", "p90")
MIN_SPREAD = 5.0


@dataclass
class View:
    """One market's P10/P50/P90 on the episode grid; `posted[i]` marks slots that are real posted prices and
    `source[i]` the issue time of the vintage that priced slot i (None: the naive fallback)."""

    market: str
    step_min: int
    p10: list[float]
    p50: list[float]
    p90: list[float]
    posted: list[bool]
    issued_at: int | None
    model: str
    source: list = field(default_factory=list)

    def q(self, name: str) -> list[float]:
        return getattr(self, name)


class DeskForecaster(Protocol):
    name: str

    def vintage(self, market: str, now: int) -> Vintage | None: ...


def _latest(vs: list[Vintage], market: str, now: int) -> Vintage | None:
    best = None
    for v in vs:
        if v.kind == market and v.issued_at <= now:
            best = v
    return best


def _hist_days(ser: Series, now: int) -> list[list[float]]:
    days = [ser.history_dam[d] for d in sorted(ser.history_dam)]
    return days + [ser.dam_spp[24 * j:24 * j + 24] for j in range(ser.days) if ser.dam_posted[j] <= now]


def naive_dam(ser: Series, now: int) -> tuple[list[float], list[float]]:
    """(P50, spread) per hour of day from posted DAM days only: the latest posted day and the mean absolute deviation."""
    days = _hist_days(ser, now)
    if not days:
        return [40.0] * 24, [20.0] * 24
    p50 = list(days[-1])
    spread = [max(sum(abs(d[h] - p50[h]) for d in days) / len(days), MIN_SPREAD) for h in range(24)]
    return p50, spread


def naive_basis(ser: Series, now: float) -> list[float]:
    """Mean |RT SPP - DAM SPP| per hour of day over the posted intervals of history days that have both."""
    sums, counts = [0.0] * 24, [0] * 24
    for d in ser.history_rt:
        if d not in ser.history_dam:
            continue
        dam = ser.history_dam[d]
        for i, p in enumerate(posted_part(ser.history_rt[d], d, ser.d0, 15, 2, now)):
            sums[i // 4] += abs(p - dam[i // 4])
            counts[i // 4] += 1
    return [max(sums[h] / counts[h] if counts[h] else MIN_SPREAD, MIN_SPREAD) for h in range(24)]


class SeriesForecaster:
    name = "series"

    def __init__(self, ser: Series):
        self.ser = ser

    def vintage(self, market: str, now: int) -> Vintage | None:
        return _latest(self.ser.desk_forecast, market, now)


class NaiveForecaster:
    """Fallback desk forecast, labelled `naive`: no vintages, computed on demand from posted data."""

    name = "naive"

    def __init__(self, ser: Series):
        self.ser = ser

    def vintage(self, market: str, now: int) -> Vintage | None:
        return None


def issued(fc: DeskForecaster, market: str, now: int) -> list[Vintage]:
    """Every vintage of `market` issued by `now`, oldest first, so later issues overwrite the hours they cover (a
    multi-day episode has one DAM vintage per operating day)."""
    ser = getattr(fc, "ser", None)
    if ser is None or isinstance(fc, NaiveForecaster):
        v = fc.vintage(market, now)
        return [v] if v else []
    return [v for v in ser.desk_forecast if v.kind == market and v.issued_at <= now]


def forecaster_for(ser: Series) -> DeskForecaster:
    return SeriesForecaster(ser) if ser.desk_forecast else NaiveForecaster(ser)


def _fill(v: Vintage | None, slots: int, step: int, base: list[list[float]]) -> tuple[list[list[float]], list[bool]]:
    """Overlay a vintage on per-slot base quantiles; returns the three paths and which slots the vintage covered."""
    out = [list(b) for b in base]
    covered = [False] * slots
    if v is None:
        return out, covered
    for i in range(slots):
        t = i * step
        j = int((t - v.start) // v.step_min)
        if 0 <= j and all(j < len(v.values.get(q, [])) for q in QS):
            for n, q in enumerate(QS):
                out[n][i] = float(v.values[q][j])
            covered[i] = True
    return out, covered


def views(ser: Series, fc: DeskForecaster, now: int) -> dict[str, View]:
    """The desk's DAM (hourly) and RT (15-minute) views at `now`: posted prices where posted, else the forecast."""
    H, NI = 24 * ser.days, 96 * ser.days
    p50, spread = naive_dam(ser, now)
    base = [[p50[h % 24] - spread[h % 24] for h in range(H)], [p50[h % 24] for h in range(H)],
            [p50[h % 24] + spread[h % 24] for h in range(H)]]
    vd = fc.vintage("dam", now)
    dam = base
    dsrc: list = [None] * H
    for v in issued(fc, "dam", now):
        dam, cov = _fill(v, H, 60, dam)
        dsrc = [v.issued_at if c else x for c, x in zip(cov, dsrc, strict=True)]
    posted = [False] * H
    for j in range(ser.days):
        if ser.dam_posted[j] <= now:
            for h in range(24 * j, 24 * j + 24):
                for q in dam:
                    q[h] = ser.dam_spp[h]
                posted[h] = True
    basis = naive_basis(ser, now)
    rbase = [[dam[1][i // 4] - basis[(i // 4) % 24] for i in range(NI)], [dam[1][i // 4] for i in range(NI)],
             [dam[1][i // 4] + basis[(i // 4) % 24] for i in range(NI)]]
    vr = fc.vintage("rt", now)
    rt = rbase
    rsrc: list = [None] * NI
    for v in issued(fc, "rt", now):
        rt, cov = _fill(v, NI, 15, rt)
        rsrc = [v.issued_at if c else x for c, x in zip(cov, rsrc, strict=True)]
    rposted = [False] * NI
    for i in range(NI):
        if 15 * i + 15 + 2 <= now:
            for q in rt:
                q[i] = ser.rt_spp[i]
            rposted[i] = True
    for q in (dam, rt):
        for i in range(len(q[0])):
            lo, mid, hi = sorted((q[0][i], q[1][i], q[2][i]))
            q[0][i], q[1][i], q[2][i] = lo, mid, hi
    name = fc.name if fc.name != "series" else (vd.model if vd else vr.model if vr else "series")
    return {"dam": View("dam", 60, *dam, posted, vd.issued_at if vd else None, name if vd else "naive", dsrc),
            "rt": View("rt", 15, *rt, rposted, vr.issued_at if vr else None, name if vr else "naive", rsrc)}


def label(fc_model: str) -> str:
    return "modelled desk forecast" + (" (naive fallback: posted prices only)" if fc_model == "naive" else "")


def issued_label(v: View, d0: str) -> str | None:
    return clock.label(v.issued_at, d0) if v.issued_at is not None else None


def _latest_as(ser: Series, market: str, product: str, now: int) -> Vintage | None:
    best = None
    for v in ser.desk_forecast:
        if v.kind == market and v.product == product and v.issued_at <= now:
            best = v
    return best


def as_views(ser: Series, fc: DeskForecaster, now: int, rtcb: bool) -> dict:
    """The desk's AS price views at `now` per price key, on the hourly episode grid: DAM MCPC (posted where posted,
    else the desk vintage, else the latest posted day +-50%, labelled naive) and post-RTC+B RT MCPC (the desk vintage,
    else the DAM view times the history RT/DA ratio, else IMM 2025's ratio; desk-research.md §7)."""
    H = 24 * ser.days
    posted_days = [ser.history_mcpc[d] for d in sorted(ser.history_mcpc)]
    posted_days += [{k: v[24 * j:24 * j + 24] for k, v in ser.dam_mcpc.items()} for j in range(ser.days)
                    if ser.dam_posted[j] <= now and ser.dam_mcpc]
    keys = list(ser.dam_mcpc) or (list(posted_days[-1]) if posted_days else [])
    out = {}
    for market in ("dam", "rt"):
        q = {"p10": {}, "p50": {}, "p90": {}}
        model = "naive"
        for k in keys:
            if market == "dam":
                base = (posted_days[-1].get(k) if posted_days else None) or [0.0] * 24
                p50 = [float(base[h % 24] or 0.0) for h in range(H)]
                lo, hi = [x * 0.5 for x in p50], [x * 1.5 for x in p50]
                v = _latest_as(ser, "as_dam", k, now)
            else:
                ratio = _rt_ratio(ser, k, now)
                p50 = [x * ratio for x in out["dam"]["p50"][k]]
                lo, hi = [x * 0.3 for x in p50], [x * 3.0 for x in p50]
                v = _latest_as(ser, "as_rt", k, now)
            if v is not None:
                model = v.model or "series"
                for i in range(H):
                    jj = int((60 * i - v.start) // v.step_min)
                    if 0 <= jj < len(v.values.get("p50", [])):
                        lo[i], p50[i], hi[i] = (float(v.values[n][jj]) for n in QS)
            if market == "dam":
                for j in range(ser.days):
                    if ser.dam_posted[j] <= now and k in ser.dam_mcpc:
                        for h in range(24 * j, 24 * j + 24):
                            lo[h] = p50[h] = hi[h] = ser.dam_mcpc[k][h]
            q["p10"][k], q["p50"][k], q["p90"][k] = lo, p50, hi
        out[market] = {"market": f"as_{market}", "model": model, **q}
    if not rtcb:
        out["rt"] = {"market": "as_rt", "model": "none", "p10": {k: [0.0] * H for k in keys},
                     "p50": {k: [0.0] * H for k in keys}, "p90": {k: [0.0] * H for k in keys}}
    return out


def _rt_ratio(ser: Series, key: str, now: float) -> float:
    pairs = []
    for d in ser.history_rt_mcpc:
        if d in ser.history_mcpc and key in ser.history_mcpc[d] and key in ser.history_rt_mcpc[d]:
            rt = posted_part(ser.history_rt_mcpc[d][key], d, ser.d0, 15, 2, now)
            if rt:
                da = ser.history_mcpc[d][key][:len(rt) // 4 or 1]
                pairs.append((sum(da) / len(da), sum(rt) / len(rt)))
    da = sum(a for a, _ in pairs)
    if pairs and da > 0:
        return sum(b for _, b in pairs) / da
    return RT_DA_RATIO.get(key, 0.3)
