"""Reference episodes for the viewer: the DP optimum, greedy, threshold and a deliberately flawed plan on chosen
(point, date) days, written as gridsim.episode/v1 Episode JSON with a runs index.json.

Until gridsim_core lands this computes a placeholder optimum with its own small DP over the contract's physics.

usage: python scripts/reference_episodes.py --out results/runs/reference [--days HB_WEST:2024-04-30 ...]
"""

import argparse
import io
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BATTERY = {"archetype": "2h-c", "source": "archetype", "p_dis_mw": 100, "p_ch_mw": 100, "energy_mwh": 200,
           "unit_mwh": 25, "q_15": 6.25, "k_dis": 4, "k_ch": 4, "soc_levels": 8, "eta": 0.85, "c_deg": 4.0,
           "cycle_cap_units": 12, "s0": 4, "s_end_min": 4}
REGION = {"HB_WEST": "west", "LZ_WEST": "west", "HB_PAN": "panhandle", "HB_NORTH": "north", "LZ_NORTH": "north",
          "LZ_RAYBN": "north", "HB_HOUSTON": "houston", "LZ_HOUSTON": "houston", "HB_SOUTH": "south",
          "LZ_SOUTH": "south", "LZ_CPS": "south", "LZ_AEN": "central", "LZ_LCRA": "central", "HB_BUSAVG": "central",
          "HB_HUBAVG": "central"}
DAYS = ["HB_WEST:2024-04-30", "HB_HOUSTON:2024-05-08", "HB_NORTH:2024-08-20", "HB_PAN:2024-04-10",
        "HB_SOUTH:2024-05-24", "LZ_AEN:2024-08-06"]
P_FLOOR = 50.0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--out", type=Path, default=ROOT / "results" / "runs" / "reference")
    p.add_argument("--days", nargs="*", default=DAYS)
    args = p.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    for spec in args.days:
        point, day = spec.split(":")
        task = make_task(point, day, prices(point, day))
        for kind in ("opt", "greedy", "threshold", "flawed"):
            ep = episode(task, kind)
            (args.out / f"{ep['episode_id']}.json").write_text(json.dumps(ep, separators=(",", ":")))
            print(ep["episode_id"], ep["reward"], ep["profit_usd"])
    return 0


def prices(point: str, day: str) -> list[float]:
    year = day[:4]
    cache = ROOT / "cache" / "viewer" / f"dam_{year}.json"
    if not cache.exists():
        import openpyxl
        z = zipfile.ZipFile(ROOT / "cache" / "raw" / "ercot" / f"DAMLZHBSPP_{year}.zip")
        wb = openpyxl.load_workbook(io.BytesIO(z.read(z.namelist()[0])), read_only=True)
        days: dict = {}
        for ws in wb.worksheets:
            for d, he, rep, pt, price in (r[:5] for r in ws.iter_rows(min_row=2, values_only=True)):
                if rep == "Y" or d is None:
                    continue
                m, dd, y = d.split("/")
                days.setdefault(f"{y}-{m}-{dd}", {}).setdefault(pt, [None] * 24)[int(he.split(":")[0]) - 1] = price
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(days, separators=(",", ":")))
    return json.loads(cache.read_text())[day][point]


def make_task(point: str, day: str, p: list[float]) -> dict:
    t = {"task_id": f"dam-v1-{day}-{point}-{BATTERY['archetype']}", "date": day, "settlement_point": point,
         "point_kind": "hub" if point.startswith("HB_") else "load_zone", "region": REGION[point], "prices": p,
         "blind": None, "battery": dict(BATTERY)}
    opt_profit, opt = solve(t)
    t["refs"] = {"p_idle": simulate(t, [0] * 24)["profit_usd"], "p_opt": opt_profit, "opt": opt}
    return t


def simulate(task: dict, actions: list[int]) -> dict:
    b, p = task["battery"], task["prices"]
    q, eta, n = b["unit_mwh"], b["eta"], b["soc_levels"]
    s, used, trunc, viol = b["s0"], 0, None, None
    executed, soc, cash, mwh, deg = [], [s], [], [], 0.0
    for h, a in enumerate(actions):
        if trunc is None:
            v = ("rate" if not -b["k_ch"] <= a <= b["k_dis"] else "soc_below_0" if s - a < 0 else
                 "soc_above_N" if s - a > n else "cycle_cap" if used + max(a, 0) > b["cycle_cap_units"] else None)
            if v:
                trunc, viol = h, v
        a = 0 if trunc is not None else a
        s -= a
        used += max(a, 0)
        g = q * a if a > 0 else q * a / eta
        d = b["c_deg"] * q * max(a, 0)
        executed.append(a), soc.append(s), mwh.append(round(g, 4)), cash.append(round(p[h] * g - d, 4))
        deg += d
    short = max(0, b["s_end_min"] - s)
    pen = short * q / eta * max(max(p), P_FLOOR)
    return {"feasible": trunc is None, "truncated_at": trunc, "violation": viol, "executed": executed,
            "soc_path": soc, "cashflow": cash, "mwh": mwh, "degradation_usd": deg, "end_shortfall_units": short,
            "penalty_usd": pen, "profit_usd": round(sum(cash) - pen, 4)}


def solve(task: dict) -> tuple[float, list[int]]:
    b, p = task["battery"], task["prices"]
    q, eta, n, cap = b["unit_mwh"], b["eta"], b["soc_levels"], b["cycle_cap_units"]
    pen = q / eta * max(max(p), P_FLOOR)
    V = {(s, d): -pen * max(0, b["s_end_min"] - s) for s in range(n + 1) for d in range(cap + 1)}
    policy = []
    for h in range(23, -1, -1):
        W, pol = {}, {}
        for s in range(n + 1):
            for d in range(cap + 1):
                best = None
                for a in sorted(range(-b["k_ch"], b["k_dis"] + 1), key=lambda x: (abs(x), x)):
                    if not 0 <= s - a <= n or d + max(a, 0) > cap:
                        continue
                    g = q * a if a > 0 else q * a / eta
                    v = p[h] * g - b["c_deg"] * q * max(a, 0) + V[(s - a, d + max(a, 0))]
                    if best is None or v > best[0] + 1e-9:
                        best = (v, a)
                W[(s, d)], pol[(s, d)] = best
        V = W
        policy.append(pol)
    policy.reverse()
    s, d, sched = b["s0"], 0, []
    for h in range(24):
        a = policy[h][(s, d)]
        sched.append(a)
        s, d = s - a, d + max(a, 0)
    return round(V[(b["s0"], 0)], 4), sched


def threshold(task: dict) -> list[int]:
    b, p = task["battery"], task["prices"]
    lo, hi = sorted(p)[6], sorted(p)[17]
    out, s, d = [], b["s0"], 0
    for h in range(24):
        a = -b["k_ch"] if p[h] <= lo else b["k_dis"] if p[h] >= hi else 0
        a = max(min(a, s, b["cycle_cap_units"] - d), s - b["soc_levels"])
        if h >= 20 and s - a < b["s_end_min"]:
            a = min(a, s - b["s_end_min"])
        out.append(a)
        s, d = s - a, d + max(a, 0)
    return out


def greedy(task: dict) -> list[int]:
    b, p = task["battery"], task["prices"]
    peak = max(range(24), key=lambda h: p[h])
    out = [0] * 24
    cheap = sorted(range(peak), key=lambda h: p[h])[:2]
    for h in cheap:
        out[h] = -b["k_ch"]
    out[peak] = b["k_dis"]
    nxt = max((h for h in range(24) if h != peak and h > max(cheap, default=0)), key=lambda h: p[h])
    out[nxt] = b["k_dis"]
    return out


def flawed(task: dict) -> list[int]:
    out = list(task["refs"]["opt"])
    peak = max(range(24), key=lambda h: task["prices"][h])
    for h in range(peak, 24):
        if out[h] > 0:
            out[h] += 2
            break
    return out


def episode(task: dict, kind: str) -> dict:
    sched = {"opt": task["refs"]["opt"], "greedy": greedy(task), "threshold": threshold(task),
             "flawed": flawed(task)}[kind]
    sim = simulate(task, sched)
    refs = task["refs"]
    span = refs["p_opt"] - refs["p_idle"]
    reward = round(min(1, max(0, 0.2 + 0.8 * (sim["profit_usd"] - refs["p_idle"]) / span)), 6)
    base = {k: {"schedule": f(task), "profit": simulate(task, f(task))["profit_usd"]}
            for k, f in (("greedy", greedy), ("threshold", threshold))}
    for v in base.values():
        v["reward"] = round(min(1, max(0, 0.2 + 0.8 * (v["profit"] - refs["p_idle"]) / span)), 6)
    hourly = [{"he": h + 1, "price": task["prices"][h], "action": sim["executed"][h], "mwh": sim["mwh"][h],
               "cash": sim["cashflow"][h],
               "degradation": task["battery"]["c_deg"] * task["battery"]["unit_mwh"] * max(sim["executed"][h], 0),
               "soc": sim["soc_path"][h + 1]} for h in range(24)]
    steps = []
    if kind == "flawed":
        practice = list(refs["opt"])
        practice[practice.index(max(practice))] -= 1
        steps.append({"t": 0, "tool": "check_schedule", "args": {"actions": practice},
                      "output": {**{k: v for k, v in simulate(task, practice).items() if k in (
                          "feasible", "truncated_at", "violation", "soc_path", "end_shortfall_units", "profit_usd")},
                          "checks_left": 2}})
    steps.append({"t": len(steps), "tool": "submit_schedule", "args": {"actions": sched},
                  "output": {"submitted": True, **{k: sim[k] for k in (
                      "feasible", "truncated_at", "violation", "soc_path", "profit_usd")}}})
    model = {"opt": "reference/dp-optimum", "greedy": "reference/greedy", "threshold": "reference/threshold",
             "flawed": "reference/flawed-plan"}[kind]
    message = {"opt": "The exact optimum by dynamic programming over every state of charge.",
               "greedy": "Charge in the two cheapest hours before the day's peak, sell at the peak and the next-best "
                         "hour after.",
               "threshold": "Charge flat out in the 7 cheapest hours and sell flat out in the 7 dearest, within "
                            "the battery's limits.",
               "flawed": "I'll follow the cheap midday hours down and push harder into the evening peak: two extra "
                         "units at the top hour should capture more of the spike."}[kind]
    return {"schema": "gridsim.episode/v1", "episode_id": f"{task['task_id']}-{kind}", "env": "gridsim",
            "version": "v1", "task_id": task["task_id"], "tier": "foresight", "bundle": "reference", "path": "ref",
            "model": model, "trained": None, "checkpoint_step": None, "seed": None,
            "situation": {"date": task["date"], "settlement_point": task["settlement_point"],
                          "prices": task["prices"], "battery": task["battery"]},
            "task": {k: task[k] for k in ("date", "settlement_point", "point_kind", "region", "battery", "prices",
                                          "blind")},
            "steps": steps, "final_schedule": sched, "soc_path": sim["soc_path"], "hourly": hourly,
            "truncated_at": sim["truncated_at"], "violation": sim["violation"],
            "end_shortfall_units": sim["end_shortfall_units"], "profit_usd": sim["profit_usd"], "reward": reward,
            "r_opt": reward, "references": {"p_opt": refs["p_opt"], "p_idle": refs["p_idle"], "p_lp": None,
                                            "opt": refs["opt"], **base, "clock": None, "blind": None},
            "messages": [{"role": "assistant", "content": message}], "usage": None, "wall_seconds": None}


if __name__ == "__main__":
    sys.exit(main())
