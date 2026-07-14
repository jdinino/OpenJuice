#!/usr/bin/env python3
"""Extract endpoint paths + provisioning method/type names from the Generac .NET
assemblies inside a Xamarin APK (1.x Installer / 2.x Mobile Link)."""
import zipfile, sys, re

APK = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\jdinino\AI\Mobile+Link+Setup_1.0.2707_APKPure.apk"
z = zipfile.ZipFile(APK)

# Generac assemblies stored individually?
gen = [n for n in z.namelist() if "generac" in n.lower() and n.lower().endswith(".dll")]
print(f"Generac assemblies found as individual entries: {gen or '(none — likely in assemblies.blob)'}")

blobs = []
for n in gen:
    blobs.append((n, z.read(n)))
if not blobs:
    # fall back to the whole blob
    for n in z.namelist():
        if n.endswith("assemblies.blob") or n.endswith(".dll"):
            blobs.append((n, z.read(n)))

STR = re.compile(rb"[\x20-\x7e]{3,}")
# interesting: gainspan paths, config/network/wifi/scan/connect verbs, api versions
PATHY = re.compile(r"^(?:[a-z][a-z0-9_]*/)+[a-z0-9_.]*$|gainspan|/system|api/|config/|network|wifi|scan|passphrase|ssid|provision|apparatus|exercise|enroll", re.I)
METHODY = re.compile(r"(Async$|Handler$|^get_|^set_|Endpoint|BasePath|Api$|Provision|Configure|Connect|Scan|Network)")

for name, blob in blobs:
    strings = sorted({m.group().decode("latin1") for m in STR.finditer(blob)})
    paths = sorted({s for s in strings if PATHY.search(s) and " " not in s and len(s) < 80
                    and not s.startswith(("System", "Microsoft", "android", "/support", "/google",
                                          "Landroid", "Lcom", "/android", "/core", "/annotation"))})
    methods = sorted({s for s in strings if METHODY.search(s) and " " not in s and len(s) < 60
                      and any(t in s for t in ("Gainspan","Gen","Network","Wifi","WiFi","Provision",
                              "Apparatus","Config","Connect","Scan","Ssid","Passphrase","Api","Endpoint"))})
    print(f"\n########## {name} ({len(blob):,} B, {len(strings)} strings) ##########")
    print(f"--- endpoint/path-like strings ({len(paths)}) ---")
    for p in paths[:80]:
        print(f"   {p}")
    print(f"--- provisioning/API method & type names ({len(methods)}) ---")
    for m in methods[:80]:
        print(f"   {m}")
