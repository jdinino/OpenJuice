#!/usr/bin/env python3
"""Find and dump the endpoint-config block (and any URL key/value pairs) from an
APK entry containing a given marker. Reveals the legacy API endpoint map."""
import zipfile, sys, re

APK = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\jdinino\AI\Mobile+Link+Setup_1.0.2707_APKPure.apk"
MARK = (sys.argv[2] if len(sys.argv) > 2 else "LegacyGainspanApi").encode()

KV = re.compile(rb'"([A-Za-z0-9_]{3,40})"\s*:\s*"([^"]{3,200})"')
URLPAIR = re.compile(rb'"([A-Za-z0-9_]{2,50})"\s*:\s*"(https?://[^"]+|[0-9.]+/[^"]*|/[A-Za-z][^"]*)"')

z = zipfile.ZipFile(APK)
found = False
for n in z.namelist():
    try:
        b = z.read(n)
    except Exception:
        continue
    idx = b.find(MARK)
    if idx < 0:
        continue
    found = True
    print(f"=== marker {MARK!r} found in: {n} (size {len(b):,}) at offset {idx} ===")
    lo = max(0, idx - 1200)
    hi = min(len(b), idx + 1600)
    window = b[lo:hi]
    # keep printable
    printable = bytes(c if 32 <= c < 127 or c in (10, 13, 9) else 46 for c in window)
    print("\n--- context window ---")
    print(printable.decode("latin1"))

    print("\n--- URL-ish key/value pairs in this entry ---")
    seen = set()
    for m in URLPAIR.finditer(b):
        k = m.group(1).decode("latin1"); v = m.group(2).decode("latin1")
        if k not in seen:
            seen.add(k)
            print(f'  "{k}": "{v}"')
    # also endpoint-name -> path pairs referencing generac/gainspan/apparatus/api
    print("\n--- other endpoint-ish key/value pairs ---")
    seen2 = set()
    for m in KV.finditer(b):
        k = m.group(1).decode("latin1"); v = m.group(2).decode("latin1")
        if any(t in (k+v).lower() for t in ("gainspan","generac","apparatus",
               "api","endpoint","url","provision","mobilelink","azure","b2c",
               "config","wifi","network")) and k not in seen2:
            seen2.add(k)
            print(f'  "{k}": "{v}"')
    print("\n" + "=" * 70 + "\n")
    break

if not found:
    print(f"marker {MARK!r} not found in any entry")
