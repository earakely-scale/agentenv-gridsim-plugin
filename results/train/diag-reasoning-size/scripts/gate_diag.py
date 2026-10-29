"""Pipeline check: SFT-10k thinking off inside run 2's CI with valid >= 98%, and the 4B base in its sanity band."""

import json
import sys
from pathlib import Path


def summary(label):
    return json.loads((Path(sys.argv[1]) / f"eval_{label}.json").read_text())["runs"][0]["summary"]


sft, base = summary("sft-off512"), summary("q4b-off512")
ok = 0.802 <= sft["reward_mean"] <= 0.877 and sft["valid_rate"] >= 0.98 and 0.03 <= base["reward_mean"] <= 0.09
print(f"sft {sft['reward_mean']} valid {sft['valid_rate']}; base {base['reward_mean']} valid {base['valid_rate']}; "
      f"{'PASS' if ok else 'FAIL'}")
sys.exit(0 if ok else 1)
