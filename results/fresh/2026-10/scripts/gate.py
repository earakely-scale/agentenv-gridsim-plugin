"""gate.py EVAL_JSON LO HI: exit 0 when the first run's mean R lies in [LO, HI] with >= 98% valid."""

import json
import sys

s = json.load(open(sys.argv[1]))["runs"][0]["summary"]
ok = float(sys.argv[2]) <= s["reward_mean"] <= float(sys.argv[3]) and s["valid_rate"] >= 0.98
print(f"GATE {'PASS' if ok else 'FAIL'} {sys.argv[1]} mean {s['reward_mean']} valid {s['valid_rate']}", flush=True)
sys.exit(0 if ok else 1)
