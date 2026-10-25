"""The v1 board: GPT-6.1 Sol's four pre-registered sweeps and their amendment, reported by `agent-env gridsim sweep
report` into results/eval-v1.json and results/board.md on the cross-version scale (docs/REWARD-SCALES.md: hindsight
capture C heads it, R second), with the board's own text around the tables: who ran it, the pre-registration, the
amendment, the hypotheses against what was measured, and a reading. Every number in it comes from the sweeps'
results, their Episode JSON and the packs.

usage: python scripts/board.py
"""

import json
import os
import re
import statistics
import textwrap
from collections import Counter
from datetime import datetime
from pathlib import Path

from agentenv_gridsim import sweep

ROOT = Path(__file__).resolve().parents[1]
PREREG = "docs/prereg/v1-board.md"
COLUMNS = {"A": "v1-board-sol-full", "B": "v1-board-sol-oneshot", "C": "v1-board-sol-blind", "D": "v1-board-sol-rtcb"}
SMOKES = ("smoke-a", "smoke-b", "smoke-c")
COMMIT = "1f0c24c"
AMENDMENT = (
    "The pre-registered per-episode cap of $0.10 (4× the smoke median, rounded up) collided with the agent's "
    "pessimistic pre-request cost guard. It estimates about $0.08-0.11 worst-case per request. So some episodes "
    "stopped as unscored \"cost_cap\" failures, all of them guard trips and none model failures: A 14, B 3, C 63, D 5. "
    "Retries at the same cap failed again. Those exact tasks were re-run once at a $0.40 episode cap, as sweeps "
    "`*-amend`. All "
    "scored. Both are reported: the pre-registered column (scored only) and the amended column (pre-reg scored + "
    "amend). The amended column is the headline, with this footnote, because dropping 21% of blind days biases toward "
    "easy days.")
HYPOTHESES = {"A": "~0.90-0.95", "B": "below full, by an amount not predicted", "greedy": "~0.78 (tuned to 0.75-0.80)",
              "threshold": "~0.62", "C": "no prior; first measurement"}
GUARD = re.compile(r"could cost \$([\d.]+)")


def main() -> None:
    os.chdir(ROOT)
    pre = [sweep.load(name) for name in COLUMNS.values()]
    amend = {name: sweep.load(f"{name}-amend") for name in COLUMNS.values()}
    c = sweep.report(pre, amend=amend, columns={v: k for k, v in COLUMNS.items()}, narrate=narrate)
    print(f"Wrote {sweep.CARD} and {sweep.BOARD}: " + ", ".join(
        f"{m['column']} {m['mean']:.4f} ({m['runs']}/{m['planned']})" for m in c["models"]))


def episodes(names: list[str]) -> list[dict]:
    return [json.loads(f.read_text()) for n in names for f in sorted((sweep.RUNS / n).glob("*.json"))]


def per_task(board: sweep.Board, cell, amended: bool = True) -> dict[str, float]:
    return {t: statistics.mean(r["reward"] for r in rs) for t, rs in board.scored(cell, amended).items()}


def reflow(text: str, width: int = 120) -> str:
    """Each paragraph, bullet and quote on lines of at most ``width``; headings and tables as they are."""
    out = []
    for block in text.split("\n\n"):
        if block.startswith(("|", "#")):
            out.append(block)
            continue
        lead = "> " if block.startswith(">") else ""
        out.append("\n".join(
            textwrap.fill(" ".join(item.removeprefix(">").split()), width, initial_indent=lead,
                          subsequent_indent=lead or ("  " if item.startswith("- ") else ""), break_long_words=False,
                          break_on_hyphens=False) for item in re.split(r"\n(?=- )", block)))
    return "\n\n".join(out)


def day(stamp: str) -> str:
    return datetime.fromisoformat(stamp[:10]).strftime("%-d %B %Y")


def money(x: float) -> str:
    return f"${x:,.2f}"


def pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def utc(stamp: str) -> str:
    return stamp[11:16]


def narrate(c: dict, board: sweep.Board) -> tuple[dict, str, str]:
    m = {x["column"]: x for x in c["models"]}
    cells = {x["column"]: next(k for k in board.cells if board.cells[k][0].name == COLUMNS[x["column"]])
             for x in c["models"]}
    pre_rows = [r for s in board.sweeps for r in board.rows[s.name]]
    amend_rows = [r for a in board.amend.values() for r in board.rows[a.name]]
    every = pre_rows + amend_rows
    spend = sum(r["cost_usd"] or 0.0 for r in every)
    stops = [r for r in pre_rows if r["error_code"] == "cost_cap"]
    guard = [float(GUARD.search(r["error"]).group(1)) for r in stops]
    eps = episodes([*COLUMNS.values(), *(a.name for a in board.amend.values())])
    calls = Counter(s["tool"] for e in eps for s in e["steps"])
    checked = [e for e in eps if any(s["tool"] == "check_schedule" for s in e["steps"])]
    same = sum(json.dumps([s for s in e["steps"] if s["tool"] == "check_schedule"][-1]["args"])
               == json.dumps([s for s in e["steps"] if s["tool"] == "submit_schedule"][-1]["args"]) for e in checked)
    smokes = {n: sweep.results(sweep.RUNS / n / "raw") for n in SMOKES}
    medians = {n: statistics.median(r["cost_usd"] for r in rows) for n, rows in smokes.items()}
    a_r, b_r = per_task(board, cells["A"]), per_task(board, cells["B"])
    diff = [b_r[t] - a_r[t] for t in a_r]
    c_pre = board.scored(cells["C"], amended=False)
    c_new = {t: rs for t, rs in board.scored(cells["C"]).items() if t not in c_pre}
    mean_of = lambda by, k: statistics.mean(r[k] for rs in by.values() for r in rs)  # noqa: E731
    cap_of = lambda by: statistics.mean(board.run_capture(r, "blind") for rs in by.values() for r in rs)  # noqa: E731
    c_one = statistics.mean(float(board.run_capture(r, "blind") >= 1 - 1e-9)
                            for rs in board.scored(cells["C"]).values() for r in rs)
    stopped = Counter(r["sweep"] for r in stops)
    low_a = sorted(v for v in a_r.values() if v < sweep.OPTIMAL)
    cb = m["C"]["baselines"]
    pd = m["C"]["refs"]["persistence_dp"]["delta"]
    days = m["C"]["by_day"]
    neg = days["negative_prices"]
    fore = [r for r in amend_rows if r["tier"] == "foresight"]
    fore_n, fore_mean = len(fore), statistics.mean(r["reward"] for r in fore)
    below_idle = sum(r["reward"] < 0.2 for rs in board.scored(cells["C"]).values() for r in rs)
    amend_caps = sorted({a.episode_cap_usd for a in board.amend.values()})
    pre_caps = sorted({s.episode_cap_usd for s in board.sweeps})

    extra = {"prereg": PREREG, "commit": COMMIT,
             "amendment": {"text": AMENDMENT, "headline": "amended",
                           "sweeps": {s: a.name for s, a in board.amend.items()},
                           "episode_cap_usd": {"prereg": pre_caps[0], "amended": amend_caps[0]},
                           "stopped": {k: stopped[COLUMNS[k]] for k in COLUMNS}},
             "spend_usd": round(spend, 4),
             "hypotheses": [
                 {"row": "Sol, full, foresight", "hypothesis": HYPOTHESES["A"], "measured": m["A"]["mean"]},
                 {"row": "Sol, oneshot, foresight", "hypothesis": HYPOTHESES["B"], "measured": m["B"]["mean"],
                  "minus_full": round(statistics.mean(diff), 4)},
                 {"row": "Greedy (filtered pack)", "hypothesis": HYPOTHESES["greedy"],
                  "measured": m["A"]["baselines"]["greedy"]["reward"]},
                 {"row": "Threshold", "hypothesis": HYPOTHESES["threshold"],
                  "measured": m["A"]["baselines"]["threshold"]["reward"]},
                 {"row": "Sol, blind", "hypothesis": HYPOTHESES["C"], "measured": m["C"]["mean"],
                  "capture": m["C"]["capture"]["mean"], "anchor_capture": m["C"]["anchor_capture"],
                  "delta": m["C"]["delta"], "beats_anchor": m["C"]["beats_anchor"]}]}

    start, end = min(r["started_utc"] for r in pre_rows), max(r["started_utc"] for r in pre_rows)
    a_start, a_end = min(r["started_utc"] for r in amend_rows), max(r["started_utc"] for r in amend_rows)
    scored = sum(r["outcome"] == "scored" for r in every)
    effort = m["A"]["effort"]
    intro = f"""On {day(start)} GPT-6.1 Sol (`openai/gpt-6.1-sol`, reasoning effort `{effort}`, through LiteLLM)
played the v1 board once per battery-day, as [pre-registered]({'../' + PREREG}) before the first episode: column **A**,
the `full` harness (3 checks) at the foresight tier, on the {m['A']['planned']} held-out days of January to November
2025 (`ercot-dam-v1-eval`); **B**, the `oneshot` harness (submit only, the training prompt) on the same
{m['B']['planned']}; **C**, `full` at the blind tier on that pack's {m['C']['planned']} blind days; and the optional
**D**, `full` at the foresight tier on the {m['D']['planned']} days of `ercot-dam-v1-rtcb`, after ERCOT's real-time
co-optimization went live. The overnight v1 build ran the four sweeps for Edgar Arakelyan with `agent-env gridsim sweep
run` on one Linux cloud box, the env and agent as local containers, from {utc(start)} to {utc(end)} UTC (first
attempts' starts), and the amendment's four re-run sweeps from {utc(a_start)} to {utc(a_end)} UTC. The run files don't
record the commit: main's head when the sweeps started was `{COMMIT}`, and gridsim_core, the env, the verifier and the
agent are the same from it to the commit that publishes this board. The model spend was {money(spend)} over
{len(every):,} attempts, {scored:,} of them scored.

Every scored run replays: `agent-env gridsim episodes` played each of the {sum(calls.values()):,} recorded tool calls
of the {len(eps):,} scored runs ({calls['submit_schedule']:,} submits, {calls['check_schedule']:,} checks,
{calls['get_situation']} `get_situation`) again on a fresh env and got the recorded output every time, and every
reward equals both the verifier's and gridsim_core's grade of the schedule (within 1e-6). No run mismatched. The runs
are in the dataset's `v1_episodes` config with their transcripts and replay in 3D in the Space ([links](#links)).

**Headline: the amended columns,** on the cross-version scale ([docs/REWARD-SCALES.md](../docs/REWARD-SCALES.md)):
hindsight capture C = (P − P_idle)/(P_opt − P_idle) with the anchor's own C and the paired gap Δ, then R. At the
foresight tier the anchor is the hindsight, so C = (R − 0.2)/0.8 and the tier reads as solved: C
{m['A']['capture']['mean']:.3f} on A ({pct(m['A']['r_one'])} of days at C = 1), {m['B']['capture']['mean']:.3f} on B
and {m['D']['capture']['mean']:.3f} on D, with no rule broken in any of the {len(eps):,} scored runs. The blind tier
separates: C {m['C']['capture']['mean']:.3f} ({m['C']['capture']['ci95'][0]:.3f} to
{m['C']['capture']['ci95'][1]:.3f}) against the blind anchor's own {m['C']['anchor_capture']:.3f} on the same days, Δ
{m['C']['delta']['mean']:+.3f} ({m['C']['delta']['ci95'][0]:+.3f} to {m['C']['delta']['ci95'][1]:+.3f}): level with
the anchor. Second, R {m['C']['mean']:.4f} ({m['C']['ci95'][0]:.3f} to {m['C']['ci95'][1]:.3f}), at R = 1 on
{pct(m['C']['r_one'])} of the days, above the anchor on {pct(m['C']['beats_anchor'])}. The r_opt this board printed
before (0.2 + 0.8 C) is replaced by C.

## The amendment

The board ran under one amendment, made after the sweeps and before this report, recorded as the main session wrote
it:

> {AMENDMENT}

What the files show:

- **The cap.** The smoke sweeps (`smoke-a`, `-b`, `-c`: 10 train days each at full/foresight, oneshot/foresight and
  full/blind, all {sum(len(r) for r in smokes.values())} scored) had median episodes of
  {', '.join(f'${v:.4f}' for v in medians.values())}; 4× the largest is ${4 * max(medians.values()):.4f}, rounded up
  to the registered ${pre_caps[0]:.2f}.
- **The stops.** {len(stops)} pre-registered runs stopped with `cost_cap` (A {stopped[COLUMNS['A']]}, B
  {stopped[COLUMNS['B']]}, C {stopped[COLUMNS['C']]}, D {stopped[COLUMNS['D']]}), each after
  {min(r['turns'] for r in stops)} or {max(r['turns'] for r in stops)} turns and
  ${min(r['cost_usd'] for r in stops):.4f} to ${max(r['cost_usd'] for r in stops):.4f} of spend, when the agent's
  guard put its next request's worst case at ${min(guard):.4f} to ${max(guard):.4f}, past the cap. None had
  submitted. Each has one attempt in its sweep's `results.jsonl`: `sweep run` counts a cost-cap stop as final, so the
  same-cap retries are not in these files.
- **The re-runs.** The `-amend` sweeps re-ran exactly those {len(amend_rows)} tasks once each at a
  ${amend_caps[0]:.2f} episode cap; all {sum(r['outcome'] == 'scored' for r in amend_rows)} scored, for
  {money(sum(r['cost_usd'] or 0.0 for r in amend_rows))}, the dearest episode
  ${max(r['cost_usd'] or 0.0 for r in amend_rows):.4f}.
- **The bias.** The stops fell on the days that make Sol work hardest: column C's {len(c_new)} re-run days capture
  {cap_of(c_new):.3f} (R {mean_of(c_new, 'reward'):.4f}) against {cap_of(c_pre):.3f} ({mean_of(c_pre, 'reward'):.4f})
  on the {len(c_pre)} that scored under the cap, so the pre-registered column (C
  {m['C']['prereg']['capture']['mean']:.3f}, R {m['C']['prereg']['mean']:.4f}) overstates the full one (C
  {m['C']['capture']['mean']:.3f}, R {m['C']['mean']:.4f}). The {fore_n} stopped foresight runs (A, B and D) scored R
  {fore_mean:.4f} on average on their re-runs."""

    hyp = [("Sol, full, foresight (A)", HYPOTHESES["A"],
            f"{m['A']['mean']:.4f} ({m['A']['ci95'][0]:.4f} to {m['A']['ci95'][1]:.4f})", "above the range"),
           ("Sol, oneshot, foresight (B)", HYPOTHESES["B"],
            f"{m['B']['mean']:.4f}; B − A {statistics.mean(diff):+.4f} over the {len(diff)} days (B lower on "
            f"{sum(x < 0 for x in diff)}, higher on {sum(x > 0 for x in diff)})", "not below: no difference"),
           ("Greedy (filtered pack)", HYPOTHESES["greedy"],
            f"{m['A']['baselines']['greedy']['reward']:.3f} on A's days", "in the tuned band, under 0.78"),
           ("Threshold", HYPOTHESES["threshold"], f"{m['A']['baselines']['threshold']['reward']:.3f} on A's days",
            "near"),
           ("Sol, blind (C)", HYPOTHESES["C"],
            f"R {m['C']['mean']:.4f} ({m['C']['ci95'][0]:.4f} to {m['C']['ci95'][1]:.4f}); C "
            f"{m['C']['capture']['mean']:.3f} against the anchor's {m['C']['anchor_capture']:.3f}, Δ "
            f"{m['C']['delta']['mean']:+.3f}; beats the anchor on {pct(m['C']['beats_anchor'])}",
            "first measurement")]
    outro = "\n".join([
        "## Hypotheses", "",
        "The pre-registration's hypotheses, from the spec before any run, against the amended columns. They were "
        "registered on R, so R is what they are read on.", "",
        "| Row | Hypothesis | Measured | Reading |", "|---|---|---|---|",
        *(f"| {a} | {b} | {x} | {y} |" for a, b, x, y in hyp), "",
        "## Reading", "",
        f"- **Foresight is solved for Sol,** as the design expected for a frontier model: A's C is "
        f"{m['A']['capture']['mean']:.3f} (R {m['A']['mean']:.4f}), {pct(m['A']['optimal'])} of its "
        f"{m['A']['runs']} days score R ≥ 0.99 (the {len(low_a)} others {', '.join(f'{v:.3f}' for v in low_a)}), B "
        f"matches A, and D's {m['D']['runs']} post-RTC+B days average C {m['D']['capture']['mean']:.3f}. Every "
        "submitted schedule was valid: no overfill, no "
        "sell-before-charge, no rate or cycle-cap break, no end-of-day shortfall and no all-idle day in any column. "
        "With 24 prices in view, Sol finds the DP's optimum; the foresight tier stays the training headline for small "
        "models and the check that the harness works, not a way to rank frontier models.",
        f"- **The blind tier carries the discrimination.** Sol's C is {m['C']['capture']['mean']:.3f} against the "
        f"blind anchor's own {m['C']['anchor_capture']:.3f} on the same {m['C']['planned']} days, Δ "
        f"{m['C']['delta']['mean']:+.3f} ({m['C']['delta']['ci95'][0]:+.3f} to {m['C']['delta']['ci95'][1]:+.3f}); "
        f"persistence-DP captures {cb['persistence_dp']['capture']:.3f} (Sol − it {pd['mean']:+.3f}, "
        f"{pd['ci95'][0]:+.3f} to {pd['ci95'][1]:+.3f}) and ridge-DP {cb['ridge_dp']['capture']:.3f}: "
        "Sol sits above persistence-DP and level with the better of the two forecasters, which a desk can build from "
        f"the same inputs. It out-earns its anchor on {pct(m['C']['beats_anchor'])} of the days and ties or beats it "
        f"(R = 1) on {pct(m['C']['r_one'])}, where R − R_anchor reads a deficit by construction; C reaches 1 on "
        f"{pct(c_one)}. It does worst on days with negative-price hours (C {neg['capture']:.3f} on {neg['n']} days, "
        f"against {days['neither']['capture']:.3f} on the {days['neither']['n']} days with neither negative prices "
        f"nor a spike), and {below_idle} blind day{'' if below_idle == 1 else 's'} scored below idle.",
        f"- **Checking: one check, almost always.** Sol used exactly one of its three checks on "
        f"{m['A']['checks'].get('1', 0)} of A's {m['A']['runs']} runs, {m['C']['checks'].get('1', 0)} of C's "
        f"{m['C']['runs']} and {m['D']['checks'].get('1', 0)} of D's {m['D']['runs']}, never three; on {same:,} of the "
        f"{len(checked):,} runs that checked, the last schedule checked is the one it submitted. B, with no checks, "
        "scores the same as A, so at the foresight tier the check confirms rather than repairs.",
        f"- **Cost.** {money(spend)} on the model for the whole board, the amendment included: "
        + ", ".join(f"{k} ${m[k]['usd_per_episode']:.4f}" for k in COLUMNS) + " a scored episode on average; the "
        "median episode took " + ", ".join(f"{m[k]['wall_seconds']['median']:.0f} s ({k})" for k in COLUMNS)
        + " from container start to grade.", "",
        "## Links", "",
        f"- Every run with its transcript: the dataset's [`v1_episodes`]({sweep.LINKS['runs']}).",
        f"- The replays in 3D: the [Space]({sweep.LINKS['replays']}).",
        f"- The code: [agentenv-gridsim-plugin]({sweep.LINKS['code']}); the eval card: [`eval-v1.json`](eval-v1.json).",
    ])
    return extra, reflow(intro), reflow(outro)


if __name__ == "__main__":
    main()
