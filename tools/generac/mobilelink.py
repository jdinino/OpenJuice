#!/usr/bin/env python3
"""Minimal stdlib client for the Generac Mobile Link cloud API (api/v5).

Auth = a Bearer token captured from a logged-in app.mobilelinkgen.com session
(DevTools -> Network -> any api/v5 request -> copy the Authorization header, or
read it from MSAL storage). Optionally self-renew with a captured refresh token.

Reads are safe. Enrollment is staged: `check` and `validate` only inspect; the
binding writes require an explicit --commit. Nothing hits the network without a
token you supply.

Commands:
  list                              GET Apparatus/list  (find your apparatusId)
  check <serial>                    GET Apparatus/isRegistered/{serial}
  validate <serial>                 POST enrollment/validate/serialNumber/{serial}
  details <apparatusId>             GET Apparatus/details/{id}  (raw JSON)
  poll <apparatusId> [--interval N] [--influx]   telemetry loop -> stdout/Influx
  enroll <serial> --commit          run the enrollment sequence (WRITE)
  remove <org> <apparatusId> --commit            DELETE (de-register)

Token source: --token | env MLG_TOKEN | ./mlg_token.txt (first line).
Self-renew:   --refresh-token + --client-id  (B2C refresh_token grant).
"""
import sys, os, json, time, argparse, urllib.request, urllib.parse, urllib.error

BASE = "https://app.mobilelinkgen.com/api/v5"
B2C_TOKEN = ("https://generacconnectivity.b2clogin.com/generacconnectivity.onmicrosoft.com/"
             "B2C_1A_MobileLink_SignIn/oauth2/v2.0/token")
SCOPE = ("https://generacconnectivity.onmicrosoft.com/"
         "cf3e2bfb-2d0c-47dd-8067-bf59a6f88ed7/client openid offline_access")

# telemetry fields recovered from ApparatusDetails (camelCase JSON guesses);
# `details` prints the raw JSON so we can correct these against real output.
TELEM_KEYS = ["apparatusStatus", "apparatusRunHours", "batteryVoltage", "batteryLevel",
              "fuelLevel", "fuelLevelPercent", "signalStrength", "rssi", "isConnected"]


def http(method, path, token, body=None):
    url = path if path.startswith("http") else f"{BASE}/{path.lstrip('/')}"
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Authorization", "Bearer " + token)
    r.add_header("Accept", "application/json")
    if data:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except urllib.error.URLError as e:
        return 0, str(e)


def get_token(a):
    if getattr(a, "token", None):
        return a.token
    if os.environ.get("MLG_TOKEN"):
        return os.environ["MLG_TOKEN"]
    p = os.path.join(os.getcwd(), "mlg_token.txt")
    if os.path.exists(p):
        return open(p, encoding="utf-8").read().strip().splitlines()[0]
    sys.exit("No token: use --token, env MLG_TOKEN, or put it in ./mlg_token.txt")


def refresh_token(rt, client_id):
    data = urllib.parse.urlencode({
        "grant_type": "refresh_token", "client_id": client_id,
        "scope": SCOPE, "refresh_token": rt}).encode()
    req = urllib.request.Request(B2C_TOKEN, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        j = json.loads(resp.read())
        return j["access_token"], j.get("refresh_token", rt)


def show(status, body):
    print(f"[{status}]")
    print(json.dumps(body, indent=2) if isinstance(body, (dict, list)) else body)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--token")
    p.add_argument("--refresh-token"); p.add_argument("--client-id")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sp = sub.add_parser("check");    sp.add_argument("serial")
    sp = sub.add_parser("validate"); sp.add_argument("serial")
    sp = sub.add_parser("details");  sp.add_argument("apparatus_id")
    sp = sub.add_parser("poll");     sp.add_argument("apparatus_id")
    sp.add_argument("--interval", type=int, default=60); sp.add_argument("--influx", action="store_true")
    sp = sub.add_parser("enroll");   sp.add_argument("serial"); sp.add_argument("--commit", action="store_true")
    sp = sub.add_parser("remove");   sp.add_argument("org"); sp.add_argument("apparatus_id"); sp.add_argument("--commit", action="store_true")
    a = p.parse_args()

    if a.refresh_token and a.client_id:
        tok, _ = refresh_token(a.refresh_token, a.client_id)
        print("[auth] minted access token via refresh grant")
    else:
        tok = get_token(a)

    if a.cmd == "list":
        show(*http("GET", "Apparatus/list", tok))

    elif a.cmd == "check":
        show(*http("GET", f"Apparatus/isRegistered/{a.serial}", tok))

    elif a.cmd == "validate":
        show(*http("POST", f"Apparatus/enrollment/validate/serialNumber/{a.serial}", tok))

    elif a.cmd == "details":
        show(*http("GET", f"Apparatus/details/{a.apparatus_id}", tok))

    elif a.cmd == "poll":
        while True:
            st, body = http("GET", f"Apparatus/details/{a.apparatus_id}", tok)
            if isinstance(body, dict):
                flat = json.dumps(body)
                vals = {k: body.get(k) for k in TELEM_KEYS if k in body}
                if a.influx:
                    fields = ",".join(f"{k}={v}" for k, v in vals.items()
                                      if isinstance(v, (int, float)))
                    print(f"generac,apparatus={a.apparatus_id} {fields}")
                else:
                    print(f"[{st}] {vals or '(fields not matched — run `details` to see raw keys)'}")
            else:
                print(f"[{st}] {body}")
            time.sleep(a.interval)

    elif a.cmd == "enroll":
        # staged: always show validation first
        for step in (f"Apparatus/isRegistered/{a.serial}",):
            print(f"--- GET {step}"); show(*http("GET", step, tok))
        print(f"--- POST Apparatus/enrollment/validate/serialNumber/{a.serial}")
        show(*http("POST", f"Apparatus/enrollment/validate/serialNumber/{a.serial}", tok))
        if not a.commit:
            print("\n(validation only — re-run with --commit to perform the binding writes.\n"
                  " Exact enrollment/device + enrollment bodies will be filled in from the\n"
                  " validate responses before committing.)")
            return
        print("\n!!! --commit set: this WRITES to your Generac account. "
              "Bodies must be confirmed first. Aborting as a safety stop.")

    elif a.cmd == "remove":
        if not a.commit:
            print("Dry run. Add --commit to DELETE (de-register).")
            return
        show(*http("DELETE", f"Apparatus/remove/{a.org}/{a.apparatus_id}", tok))


if __name__ == "__main__":
    main()
