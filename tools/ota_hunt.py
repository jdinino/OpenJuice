#!/usr/bin/env python3
"""Hunt for OTA / firmware-update hosts + config across the 2.x Xamarin assemblies
and the 3.x Hermes bundle, so the firmware push can be pre-blocked at the router."""
import zipfile, struct, re

APK2 = r"C:\Users\jdinino\AI\Mobile+Link+for+Generators_2.28.0.47091_APKPure.apk"
APK3 = r"C:\Users\jdinino\AI\Mobile+Link+for+Generators_3.16.0_APKPure.apk"

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

def gather():
    blobs = []
    z2 = zipfile.ZipFile(APK2)
    blob = z2.read("assemblies/assemblies.blob")
    manifest = z2.read("assemblies/assemblies.manifest").decode("latin1", "replace")
    n2i = {}
    for ln in manifest.splitlines():
        p = ln.split()
        if len(p) >= 5 and p[-2].isdigit():
            n2i[p[-1]] = int(p[-2])
    for nm in [k for k in n2i if k.startswith("Generac")]:
        o = 20 + n2i[nm] * 24
        do, ds = struct.unpack("<6I", blob[o:o + 24])[:2]
        c = blob[do:do + ds]
        blobs.append((f"2.x/{nm}", lz4d(c[12:]) if c[:4] == b"XALZ" else c))
    z3 = zipfile.ZipFile(APK3)
    blobs.append(("3.x/index.android.bundle", z3.read("assets/index.android.bundle")))
    return blobs

PATS = ["otafu", "ota", "firmware", "\\.bin", "dfu", "blob.core", "azureedge",
        "cdn", "download", "WGM160P", "gecko", "update", "\\.dms", "zentri"]
HOST = re.compile(r"(?:https?://)?[a-z0-9][a-z0-9.-]{4,60}\.(?:com|net|io|azure-devices\.net|windows\.net)(?:/[^\s\"']{0,60})?", re.I)

def scan():
    hits = {}
    hosts = set()
    for name, data in gather():
        # utf8 + utf16 text
        text = data.decode("latin1", "ignore")
        text16 = data.decode("utf-16-le", "ignore")
        for label, t in ((name, text), (name, text16)):
            for pat in PATS:
                for m in re.finditer(r".{0,25}" + pat + r".{0,40}", t, re.I):
                    s = m.group().strip()
                    if s.isprintable() and 5 < len(s) < 90:
                        hits.setdefault(pat, set()).add(f"[{label}] {s}")
            for h in HOST.findall(t):
                if not any(x in h.lower() for x in ("schemas","w3.org","xamarin","microsoft.com/win",
                           "example.com","googleapis","github","newtonsoft","apache.org","nuget")):
                    hosts.add(h)
    print("### hosts referenced (filtered) ###")
    for h in sorted(hosts)[:60]:
        print("  ", h)
    print("\n### OTA / firmware keyword hits ###")
    for pat in PATS:
        if pat in hits:
            print(f"\n-- {pat} ({len(hits[pat])}) --")
            for s in sorted(hits[pat])[:12]:
                print("   ", s)

scan()
