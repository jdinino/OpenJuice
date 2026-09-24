#!/usr/bin/env python3
"""Pull literal REST route templates + base URLs + B2C/auth config values out of
the decompressed Generac .NET assemblies."""
import zipfile, struct, re

APK = r"C:\Users\jdinino\AI\Mobile+Link+for+Generators_2.28.0.47091_APKPure.apk"
z = zipfile.ZipFile(APK)
blob = z.read("assemblies/assemblies.blob")
manifest = z.read("assemblies/assemblies.manifest").decode("latin1", "replace")
name2idx = {}
for ln in manifest.splitlines():
    p = ln.split()
    if len(p) >= 5 and p[-2].isdigit():
        name2idx[p[-1]] = int(p[-2])

def lz4d(src):
    out = bytearray(); i = 0; n = len(src)
    while i < n:
        tok = src[i]; i += 1
        ll = tok >> 4
        if ll == 15:
            while True:
                b = src[i]; i += 1; ll += b
                if b != 255: break
        out += src[i:i + ll]; i += ll
        if i >= n: break
        off = src[i] | (src[i + 1] << 8); i += 2
        ml = (tok & 15) + 4
        if (tok & 15) == 15:
            while True:
                b = src[i]; i += 1; ml += b
                if b != 255: break
        st = len(out) - off
        for j in range(ml):
            out.append(out[st + j])
    return bytes(out)

def asm(name):
    do, ds = struct.unpack("<6I", blob[20 + name2idx[name] * 24: 20 + name2idx[name] * 24 + 24])[:2]
    c = blob[do:do + ds]
    return lz4d(c[12:]) if c[:4] == b"XALZ" else c

U8  = re.compile(rb"[\x20-\x7e]{3,}")
U16 = re.compile(rb"(?:[\x20-\x7e]\x00){3,}")
def strs(d):
    s = set()
    for m in U8.finditer(d): s.add(m.group().decode("latin1"))
    for m in U16.finditer(d): s.add(m.group().decode("utf-16-le"))
    return s

apiclient = asm("Generac.Application.MobileLink.ApiClient")
common    = asm("Generac.Application.MobileLink.Mobile.Common")

print("### REST route templates in ApiClient (path-like literals) ###")
ROUTE = re.compile(r"^[A-Za-z][A-Za-z0-9]*(?:/[A-Za-z0-9{}._-]+)+/?$")
routes = sorted({s for s in strs(apiclient)
                 if ROUTE.match(s) and ("{" in s or any(t in s for t in
                    ("Apparatus","apparatus","Dealer","User","Enroll","Fuel","Maintenance",
                     "Exercise","Telemetry","Device","Serial","Register","Notification")))
                 and not s.startswith(("System","Microsoft","Xamarin","Newtonsoft"))
                 and len(s) < 80})
for r in routes[:80]:
    print("  ", r)

print("\n### base URLs / hosts ###")
for d, nm in ((apiclient, "ApiClient"), (common, "Common")):
    for s in sorted(strs(d)):
        if "mobilelink" in s.lower() or re.search(r"https?://[a-z]", s) or ".azure" in s.lower() \
           or "b2clogin" in s.lower() or ".onmicrosoft" in s.lower():
            if len(s) < 120 and "schemas" not in s and "w3.org" not in s:
                print(f"  [{nm}] {s}")

print("\n### embedded config JSON (search common/apiclient for a config block) ###")
for d, nm in ((common, "Common"), (apiclient, "ApiClient")):
    for key in (b"BasePaths", b"PolicySignIn", b"ClientId\x00", b"b2clogin"):
        i = d.find(key)
        if i > 0:
            lo, hi = max(0, i - 400), min(len(d), i + 900)
            win = bytes(c if 32 <= c < 127 or c in (10, 13) else 46 for c in d[lo:hi])
            print(f"\n--- [{nm}] near {key!r} ---")
            print(win.decode("latin1"))
            break
