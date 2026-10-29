"""Pull ERCOT DAM settlement point prices (NP4-190-CD) for the v1 points through the public API.

usage: ercot_pull.py OUT_DIR DATE_FROM DATE_TO [POINT ...]. Credentials come from SSM inside this process and are
never printed; raw pages are saved as JSON (prices only). At most 10 requests a minute."""

import json
import sys
import time
from pathlib import Path

import boto3
import requests

TOKEN_URL = ("https://ercotb2c.b2clogin.com/ercotb2c.onmicrosoft.com/B2C_1_PUBAPI-ROPC-FLOW/oauth2/v2.0/token")
CLIENT = "fec253ea-0d06-4272-a5e6-b478baeecd70"
API = "https://api.ercot.com/api/public-reports/np4-190-cd/dam_stlmnt_pnt_prices"
POINTS = ["HB_HOUSTON", "HB_NORTH", "HB_PAN", "HB_SOUTH", "HB_WEST", "LZ_AEN", "LZ_CPS", "LZ_HOUSTON", "LZ_LCRA",
          "LZ_NORTH", "LZ_RAYBN", "LZ_SOUTH", "LZ_WEST", "HB_HUBAVG", "HB_BUSAVG"]
GAP_S = 6.5


def ssm(name: str) -> str:
    c = boto3.Session(profile_name="agent-environments-admin", region_name="us-west-2").client("ssm")
    return c.get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"]


def token() -> str:
    form = {"username": ssm("/gridsim/ercot-username"), "password": ssm("/gridsim/ercot-password"),
            "grant_type": "password", "scope": f"openid {CLIENT} offline_access", "client_id": CLIENT,
            "response_type": "id_token"}
    for attempt in (1, 2):
        r = requests.post(TOKEN_URL, data=form, timeout=60)
        if r.status_code == 200 and r.json().get("id_token"):
            print(f"login ok (attempt {attempt})", flush=True)
            return r.json()["id_token"]
        print(f"login failed (attempt {attempt}): HTTP {r.status_code}", flush=True)
        time.sleep(GAP_S)
    sys.exit("login failed twice: stopping")


def main():
    out, d0, d1 = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    points = sys.argv[4:] or POINTS
    out.mkdir(parents=True, exist_ok=True)
    head = {"Ocp-Apim-Subscription-Key": ssm("/gridsim/ercot-api-key"), "Authorization": f"Bearer {token()}"}
    last = time.monotonic()
    for p in points:
        page, rows, fields = 1, [], None
        while True:
            time.sleep(max(0.0, GAP_S - (time.monotonic() - last)))
            last = time.monotonic()
            r = requests.get(API, headers=head, timeout=120, params={
                "deliveryDateFrom": d0, "deliveryDateTo": d1, "settlementPoint": p, "size": 5000, "page": page})
            if r.status_code != 200:
                print(f"{p} page {page}: HTTP {r.status_code} {r.text[:200]}", flush=True)
                break
            j = r.json()
            fields = [f["name"] for f in j.get("fields", [])]
            rows += j.get("data", [])
            meta = j.get("_meta", {})
            if page >= int(meta.get("totalPages") or 1):
                break
            page += 1
        (out / f"{p}.json").write_text(json.dumps({"point": p, "from": d0, "to": d1, "fields": fields, "data": rows,
                                                   "fetched_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}))
        dates = sorted({str(x[fields.index("deliveryDate")]) for x in rows}) if fields and rows else []
        print(f"{p}: {len(rows)} rows, dates {dates[:1]}..{dates[-1:]}, fields {fields}", flush=True)


if __name__ == "__main__":
    main()
