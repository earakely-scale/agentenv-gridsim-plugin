"""The training views from path-B episodes (gridsim.episode/v1 with `trained`): LEVEL UP, one held-out day replayed at
successive checkpoints, and the race, up to four models on that day. Copies the episodes they use into --out with
levelup.json and race.json, which the Space build and the viewer read.

The day is picked by rule: the largest base-to-trained gain in reward among the days where the trained model scores
at least DOES_WELL; when no day reaches it, the largest gain, and the manifest says so.

A run in several arms (arm 2, then the arm 2b continuation) is one arc: pass the arms' folders in training order. Each
GRPO frame carries its arm's label from that folder's summary.json.

usage: python scripts/train_views.py [--episodes results/train/episodes] [--summary results/train/summary.json]
       [--out results/runs/train] [--day TASK_ID --why TEXT [--label TEXT]]
       python scripts/train_views.py --episodes results/train/arm2 results/train/arm2b \
           --summary results/train/arm2b/summary.json  (arm 2 then arm 2b)
"""

import argparse
import json
import re
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOL = ("v1-board-sol-oneshot", "v1-board-sol-oneshot-amend", "v1-board-sol-full", "v1-board-sol-full-amend")
DOES_WELL = 0.85
PACKS = {"eval_iid": "eval_iid", "rtcb": "post-RTC+B"}
RULE = (f"the largest base-to-trained gain in reward among held-out days where the trained model scores at least "
        f"{DOES_WELL}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--episodes", type=Path, nargs="+", default=[ROOT / "results" / "train" / "episodes"],
                   help="The run's path-B episodes (.json or .jsonl), one folder per arm in training order; where two "
                        "hold the same day, stage, step and seed, the earlier folder's episode is kept.")
    p.add_argument("--summary", type=Path, default=ROOT / "results" / "train" / "summary.json",
                   help="The last arm's summary.json: the rules' mean reward and the paired gaps to them.")
    p.add_argument("--out", type=Path, default=ROOT / "results" / "runs" / "train")
    p.add_argument("--day", help="Override the rule with this task id (the manifest records the override).")
    p.add_argument("--why", help="Why --day overrides the rule; the views show it.")
    p.add_argument("--label", default="chosen by hand", help="How --day was chosen, the views' label for it.")
    p.add_argument("--decoding", choices=("sampled", "greedy"), default="sampled",
                   help="One decoding for every frame and lane; the checkpoints were evaluated sampled.")
    p.add_argument("--race-trained", type=Path,
                   help="A registered run's folder (its episodes and summary.json with the bars): its final model on "
                        "the day takes the race's trained lane, and the race states the run's registered verdict.")
    p.add_argument("--race-label", default="registered run", help="What the race calls --race-trained's model.")
    p.add_argument("--race-warm-start", metavar="LABEL",
                   help="Also race --race-trained's warm start (its SFT eval on the day, the summary row naming LABEL) "
                        "in place of the arms' SFT lane; the race's context is then that run's own.")
    p.add_argument("--race-earlier", type=Path, help="The registered run before --race-trained, for its verdict.")
    p.add_argument("--race-confirm", type=Path,
                   help="A pre-registered confirmatory eval of --race-warm-start on fresh packs (its summary.json "
                        "bars per pack); the verdict ends with its result.")
    args = p.parse_args(argv)
    first: dict[tuple, dict] = {}
    arm: dict[str, str | None] = {}
    for folder in args.episodes:
        name = json.loads(s.read_text()).get("label") if (s := folder / "summary.json").exists() else None
        for e in (e for f in sorted(folder.rglob("*.json*")) for e in read(f)):
            if first.setdefault((e["task_id"], e["trained"], e["checkpoint_step"], e.get("seed")), e) is e:
                arm.setdefault(e["episode_id"], name)
    eps = list(first.values())
    want = [e for e in eps if (e.get("seed") is not None) == (args.decoding == "sampled")]
    stages = {(e["task_id"], e["trained"], e["checkpoint_step"]) for e in want}
    eps = want + [e for e in eps if (e["task_id"], e["trained"], e["checkpoint_step"]) not in stages]
    days: dict[str, dict] = {}
    for e in eps:
        d = days.setdefault(e["task_id"], {"base": [], "sft": [], "grpo": []})
        d.setdefault(e["trained"], []).append(e)
    rows = []
    for tid, d in days.items():
        base, final = pick(d["base"]), final_of(d["grpo"])
        if base and final:
            rows.append((tid, r(final) - r(base), r(final), len({e["checkpoint_step"] for e in d["grpo"]})))
    if any(x[3] > 2 for x in rows):
        rows = [x for x in rows if x[3] > 2]
    if not rows:
        raise SystemExit(f"no day in {args.episodes} has both a base and a trained episode")
    good = [x for x in rows if x[2] >= DOES_WELL]
    tid = max(good or rows, key=lambda x: (x[1], x[3], x[2], x[0]))[0]
    note = None if good else (f"no held-out day reaches {DOES_WELL} for the trained model; this is the day with the "
                              "largest gain")
    if args.day:
        tid, note = args.day, f"day {args.label}, not by the rule, which picks {tid}"
    d = days[tid]
    frames = [e for e in (pick(d["base"]), pick(d["sft"])) if e]
    by_step: dict[int, list[dict]] = {}
    for e in d["grpo"]:
        by_step.setdefault(e["checkpoint_step"] if e["checkpoint_step"] is not None else 10**9, []).append(e)
    frames += [pick(by_step[s]) for s in sorted(by_step)]
    final = final_of(d["grpo"])
    raced, verdict, own = registered(args.race_trained, tid, args.decoding, args.race_label, args.race_warm_start,
                                     args.race_earlier) if args.race_trained else ([final], None, None)
    if args.race_confirm:
        verdict += confirmed(json.loads((args.race_confirm / "summary.json").read_text()), args.race_warm_start)
    lanes = [x for x in (pick(d["base"]), *([] if len(raced) > 1 else [pick(d["sft"])]), *raced) if x]
    if sol := sol_run(tid):
        lanes.append(sol)
    args.out.mkdir(parents=True, exist_ok=True)
    for old in args.out.glob("*.json"):
        old.unlink()
    for e in {e["episode_id"]: e for e in frames + lanes}.values():
        (args.out / f"{e['episode_id']}.json").write_text(json.dumps(e, separators=(",", ":")))
    steps = [e["checkpoint_step"] for e in d["grpo"] if e["checkpoint_step"] is not None]
    model = final.get("model") or "trained model"
    levelup = {"schema": "gridsim.levelup/v1", "task_id": tid, "model": model, "rule": RULE, "note": note,
               "why": args.why if args.day else None,
               "decoding": f"{args.decoding} for every frame where the run has it",
               "days": {"candidates": len(rows), "doing_well": len(good)},
               "context": context(args.summary, eps, arm, args.decoding, [
                   e for e in eps if e["trained"] == "grpo" and e is final_of(days[e["task_id"]]["grpo"])]),
               "total_steps": max(steps, default=None), "gain": round(r(final) - r(frames[0]), 6),
               "frames": [{"episode_id": e["episode_id"], "trained": e["trained"], "step": e["checkpoint_step"],
                           "reward": e.get("reward"), "arm": arm.get(e["episode_id"])} for e in frames]}
    race = {"schema": "gridsim.race/v1", "task_id": tid, "context": own[0] if own else levelup["context"],
            "lanes": [{"episode_id": e["episode_id"], "label": label(e, arm.get(e["episode_id"]))}
                      for e in lanes[-4:]]} | ({"verdict": verdict, "context_model": own[1] if own else model}
                                               if verdict else {})
    (args.out / "levelup.json").write_text(json.dumps(levelup, indent=1))
    (args.out / "race.json").write_text(json.dumps(race, indent=1))
    print(f"day {tid}: {len(frames)} frames, rewards {[round(r(e), 3) for e in frames]}; race {race['lanes']}"
          + (f"; NOTE {note}" if note else ""))
    return 0


def context(summary: Path, eps: list[dict], arm: dict, decoding: str, trained: list[dict]) -> dict:
    """What the run did over every held-out day: each stage's and arm's mean on the full eval set, the rules and the
    paired gaps to them from summary.json, and how the trained model's plans open."""
    full: dict[tuple, list[dict]] = {}
    for e in eps:
        full.setdefault((e["trained"], e["checkpoint_step"]), []).append(e)
    n = max(map(len, full.values()))
    full = {k: v for k, v in full.items() if len(v) == n}
    out = {"tasks": n} | {k[0]: mean(v) for k, v in full.items() if k[0] != "grpo"}
    out["arms"] = [{"label": arm.get(v[0]["episode_id"]), "step": k[1], "reward": mean(v)} for k, v in sorted(
        ((k, v) for k, v in full.items() if k[0] == "grpo"), key=lambda x: 10**9 if x[0][1] is None else x[0][1])]
    out["trained"] = out["arms"][-1]["reward"] if out["arms"] else None
    if summary.exists():
        s = json.loads(summary.read_text())
        out |= {x["model"].partition(":")[2]: x["reward_mean"] for x in s["rows"]
                if x["model"] in ("baseline:greedy", "baseline:threshold", "rule:greedy", "rule:threshold")}
        gaps = {k.rpartition("_minus_")[2]: v for k, v in s.get("paired", {}).items() if f"_{decoding}_minus_" in k}
        out["reading"] = " and ".join(versus(k, gaps[k]) for k in ("threshold", "greedy") if k in gaps) or None
    firsts = [next((h for h, a in enumerate(e.get("final_schedule") or []) if a), None) for e in trained]
    if hits := [h for h in firsts if h is not None]:
        h = max(set(hits), key=hits.count)
        acts = [e["final_schedule"][h] for e in trained if e.get("final_schedule") and e["final_schedule"][h]]
        out["opening"] = {"hour": h, "charge": all(a < 0 for a in acts), "share": [hits.count(h), len(trained)]}
    return out


def registered(folder: Path, tid: str, decoding: str, name: str, warm: str | None,
               earlier: Path | None) -> tuple[list[dict], str, tuple[dict, str] | None]:
    """The registered run's final model on the day (its final eval's episode, else its last checkpoint's), after its
    warm start's when `warm` names it; the verdict from summary.json's bars, comparisons and, given `earlier`, the run
    before it; and with `warm` the run's own context over the held-out days, for the race board."""
    eps = [e for f in sorted(folder.rglob("*.json*")) for e in read(f) if e["task_id"] == tid]
    eps = [e for e in eps if (e.get("seed") is not None) == (decoding == "sampled")] or eps
    final, start = final_of([e for e in eps if e["trained"] == "grpo"]), pick([e for e in eps if e["trained"] == "sft"])
    if final is None or (warm and start is None):
        raise SystemExit(f"{folder} has no trained or warm-start episode on {tid}")
    s = json.loads((folder / "summary.json").read_text())
    b, g = s["bars"]["sampled"], s["bars"].get("greedy") or {}
    rules = {x["model"].removeprefix("rule:"): x for x in s["rows"] if x["model"].startswith("rule:")}
    rule, gap = rules["greedy"], b["paired_minus_greedy"]
    over = round(b["greedy_rule_ci95"][1] - b["ci95"][0], 3)
    met = b["primary_met"] or b["secondary_met"]
    model = s["model"].split("/")[-1]
    n = int(m[1]) if (m := re.search(r"run (\d+)", s.get("label") or "")) else 1
    cmp = s.get("comparisons", {})
    text = (f"{model}, {name}: {f3(b['reward_mean'])} {ci(b['ci95'], '.3f')} sampled over all {s['n_tasks']} held-out "
            f"days" + (f", {f3(g['reward_mean'])} with greedy decoding" if g else "") + ". Its primary bar, beating "
            f"the greedy rule's {f3(rule['reward_mean'])} {ci(rule['ci95'], '.3f')} with the 95% intervals apart, "
            + ("is met" if b["primary_met"] else f"is not met: they overlap by {f3(over)}")
            + f"; its secondary, the paired gap {f3(gap['mean'], '+.3f')} {ci(gap['ci95'])} above 0, "
            + ("is met" if b["secondary_met"] else "is not met"))
    if earlier:
        e = json.loads((earlier / "summary.json").read_text())["bars"]["sampled"]
        held = e["primary_met"] or e["secondary_met"]
        text += (": the first registered training claim on GridSimEnv that holds" if met and not held else "") + "."
        text += f" Run {n - 1} scored {f3(e['reward_mean'])} and " + ("met a bar" if held else "missed both bars")
        if d := cmp.get(decoding, {}).get(f"run{n}_final_minus_run{n - 1}_final"):
            text += f"; run {n} is {f3(d['mean'], '+.3f')} {ci(d['ci95'])} above it" + (
                "" if d["ci95"][0] > 0 else ", not significant")
        text += "."
    else:
        text += ("" if met else ": it missed both bars" + (", narrowly" if over <= 0.03 and gap["ci95"][0] > -0.01
                                                           else "")) + (". It is the first pre-registered training "
                                                                        "claim on GridSimEnv; the 1.7B arms were "
                                                                        "exploratory.")
    rows = [x for x in s["rows"] if x.get("decoding") == decoding]
    sft = next((x for x in rows if x["checkpoint_step"] == 0 and warm in x["model"]), None) if warm else None
    if sft:
        key = f"run{n}_final_minus_run{n}_sft"
        on = [(cmp[k][key], w) for k, w in (("sampled", "sampled"), ("greedy", "with greedy decoding"))
              if key in cmp.get(k, {})]
        helped = bool(on) and on[0][0]["ci95"][0] > 0
        text += (f" {'' if helped else 'The warm start did the work: '}{warm} alone scores {f3(sft['reward_mean'])} "
                 f"{ci(sft['ci95'], '.3f')}")
        if on:
            text += f", and GRPO on top {'added' if helped else 'did not help'}: " + ", ".join(
                f"{f3(d['mean'], '+.3f')} {ci(d['ci95'])} {w}" for d, w in on)
        text += "."
    vs = next(((k, v) for k, v in s.get("paired", {}).items() if k.startswith(f"trained_{decoding}_minus_arm")), None)
    if vs:
        arm, _, size = vs[0].removeprefix(f"trained_{decoding}_minus_").partition("_")
        text += (f" It is {f3(vs[1]['mean'], '+.3f')} {ci(vs[1]['ci95'])} above the "
                 f"{size.upper()} {arm[:3]} {arm[3:]} on the same days.")
    lanes = [final | {"model_label": f"{model}, {name}"}]
    if not warm:
        return lanes, text, None
    base = next(x for x in rows if " base (zero-shot" in x["model"])
    own = {"tasks": s["n_tasks"], "base": base["reward_mean"], "sft": sft["reward_mean"],
           "trained": s["bars"][decoding]["reward_mean"], "greedy": rules["greedy"]["reward_mean"],
           "threshold": rules["threshold"]["reward_mean"]}
    return [start | {"model_label": f"{model} {warm}"}, *lanes], text, (own, s["model"])


def confirmed(s: dict, warm: str) -> str:
    """One sentence on the confirmatory eval: the first pack's sampled result against the greedy rule with both bars,
    then what holds on the others."""
    (first, b), *rest = ((k, v["sampled"]) for k, v in s["bars"].items())
    return (f" A pre-registered confirmatory test then put {warm} on {s['packs'][first]['n_tasks']} fresh "
            f"{PACKS.get(first, first)} days: {f3(b['reward_mean'])} {ci(b['ci95'], '.3f')} against the greedy rule's "
            f"{f3(b['greedy_rule_mean'])} {ci(b['greedy_rule_ci95'], '.3f')}, paired "
            f"{f3(b['paired_minus_greedy']['mean'], '+.3f')} {ci(b['paired_minus_greedy']['ci95'])}: {held(b)}"
            + (", the first pre-registered claim that a trained small model beats the greedy rule outright"
               if b["primary_met"] else "")
            + "".join(f"; on {s['packs'][k]['n_tasks']} {PACKS.get(k, k)} days {held(x)}: "
                      f"{f3(x['paired_minus_greedy']['mean'], '+.3f')} {ci(x['paired_minus_greedy']['ci95'])}"
                      for k, x in rest) + ".")


def held(b: dict) -> str:
    return "both bars hold" if b["primary_met"] else "only the paired test holds" if b["secondary_met"] else (
        "neither bar holds")


def ci(x: list[float], fmt: str = "+.3f") -> str:
    return f"[{f3(x[0], fmt)}, {f3(x[1], fmt)}]"


def f3(x: float, fmt: str = ".3f") -> str:
    """Half-up, as the results READMEs print the stored four-decimal values (0.8795 is 0.880)."""
    return format(Decimal(str(x)).quantize(Decimal("0.001"), ROUND_HALF_UP), fmt)


def mean(eps: list[dict]) -> float:
    return round(sum(map(r, eps)) / len(eps), 4)


def versus(rule: str, gap: dict) -> str:
    """The final model against a rule by the paired bootstrap: above or below only when the CI excludes 0."""
    lo, hi = gap["ci95"]
    where = "above" if lo > 0 else "below" if hi < 0 else "level with"
    return f"{where} the {rule} rule (paired {gap['mean']:+.2f} [{lo:+.2f}, {hi:+.2f}])"


def read(f: Path) -> list[dict]:
    """The path-B episodes in a .json file or a .jsonl of them."""
    try:
        text = f.read_text()
        rows = [json.loads(x) for x in text.splitlines() if x.strip()] if f.suffix == ".jsonl" else [json.loads(text)]
    except (OSError, json.JSONDecodeError):
        return []
    return [e | {"trained": str(e["trained"]).lower()} for e in rows
            if isinstance(e, dict) and e.get("schema") == "gridsim.episode/v1" and e.get("trained")]


def r(e: dict) -> float:
    return e.get("reward") or 0.0


def pick(eps: list[dict]) -> dict | None:
    """The greedy (unseeded) episode when there is one, else the lowest seed."""
    return min(eps, key=lambda e: (e.get("seed") is not None, e.get("seed") or 0, e["episode_id"]), default=None)


def final_of(grpo: list[dict]) -> dict | None:
    """The final trained model: the unnumbered final eval when present, else the last checkpoint."""
    if not grpo:
        return None
    last = max(10**9 if e["checkpoint_step"] is None else e["checkpoint_step"] for e in grpo)
    return pick([e for e in grpo if (10**9 if e["checkpoint_step"] is None else e["checkpoint_step"]) == last])


def sol_run(tid: str) -> dict | None:
    for sweep in SOL:
        for f in sorted((ROOT / "results" / "runs" / sweep).glob(f"{tid}-*.json")):
            return json.loads(f.read_text()) | {"model_label": "GPT-6.1 Sol"}
    return None


def label(e: dict, arm: str | None) -> str:
    if e.get("model_label"):
        return e["model_label"]
    name = (e.get("model") or "model").split("/")[-1]
    return {"base": f"{name} base", "sft": f"{name} SFT warm start"}.get(e["trained"], f"{name} {arm or 'GRPO'}")


if __name__ == "__main__":
    sys.exit(main())
