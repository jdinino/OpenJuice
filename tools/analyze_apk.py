#!/usr/bin/env python3
"""Framework detection + legacy-marker scan for a Mobile Link APK.
Detects native vs React-Native(JSC) vs React-Native(Hermes), then searches the
JS bundle, the DEX code, and resources for provisioning / legacy / cloud markers.
Usage: python analyze_apk.py <apk>
"""
import zipfile, sys, os

APK = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\jdinino\AI\Mobile+Link+for+Generators_2.28.0.47091_APKPure.apk"

MARKERS = [
    # current-gen SoftAP V2
    "192.168.51.1", "/Generac/api", "getConfig", "setConfig",
    "initializeSystemConfig", "wifi_enable",
    # legacy V1 / GainSpan
    "gainspan", "GainSpan", "/gainspan/system", "192.168.240.1",
    "192.168.3.1", "limited ap", "LimitedAP", "provisioning",
    # module / OS families
    "zentri", "Zentri", "gecko", "Gecko_OS", "WGM160P", "GS2011",
    # controllers (old designs)
    "Nexus", "Evolution", "PZ200", "RCM", "H-panel", "HPanel", "Diagnostic",
    # cloud APIs (old + new)
    "app.mobilelinkgen.com", "api.mobilelinkgen.com",
    "webservicecl", "mobilelink.generac.com", "/api/v1", "/api/v2",
    "/api/v3", "/api/v4", "/api/v5", "/Apparatus/",
    # azure / auth
    "azure-devices", "iothub", "b2clogin", "generacconnectivity",
    "GeneracTimeServerJWT",
]


def scan(blob, markers):
    hits = {}
    for m in markers:
        if m.encode("utf-8") in blob:
            hits[m] = True
    return hits


def main():
    print(f"=== {os.path.basename(APK)} ({os.path.getsize(APK):,} bytes) ===")
    z = zipfile.ZipFile(APK)
    names = z.namelist()
    dex = [n for n in names if n.endswith(".dex")]
    bundles = [n for n in names if n.endswith(".bundle")]
    print(f"entries: {len(names)}   dex files: {len(dex)}   bundles: {bundles}")

    # framework detection
    fw = "unknown"
    bundle_kind = None
    if bundles:
        data = z.read(bundles[0])
        if data[:8] == bytes.fromhex("c61fbc03c103191f"):
            fw, bundle_kind = "React Native (Hermes bytecode)", "hermes"
        elif data[:64].lstrip()[:3] in (b"var", b"(fu", b"!fu", b"//") or b"__d(" in data[:4096]:
            fw, bundle_kind = "React Native (JSC / plaintext JS)", "plainjs"
        else:
            fw, bundle_kind = "React Native (bundle, unknown format)", "other"
        print(f"framework: {fw}")
        print(f"bundle: {bundles[0]}  {len(data):,} bytes  first8={data[:8].hex()}")
    else:
        # native?
        alldex = b"".join(z.read(d) for d in dex) if dex else b""
        if b"com/facebook/react" in alldex:
            fw = "React Native (native libs, JS in .so/assets?)"
        else:
            fw = "Native Android (no JS bundle)"
        print(f"framework: {fw}")

    # gather searchable blobs by component
    comp = {}
    if bundles:
        comp["bundle"] = z.read(bundles[0])
    comp["dex"] = b"".join(z.read(d) for d in dex) if dex else b""
    resxml = [n for n in names if n.startswith("res/") and n.endswith(".xml")]
    comp["res"] = b"".join(z.read(n) for n in resxml[:2000])
    try:
        comp["res"] += z.read("AndroidManifest.xml")
    except KeyError:
        pass

    print("\nmarker matrix (which component contains each string):")
    print(f"  {'marker':<26} {'bundle':>7} {'dex':>5} {'res':>5}")
    any_hit = False
    for m in MARKERS:
        b = ("bundle" in comp) and (m.encode() in comp["bundle"])
        d = m.encode() in comp["dex"]
        r = m.encode() in comp["res"]
        if b or d or r:
            any_hit = True
            print(f"  {m:<26} {('Y' if b else '·'):>7} {('Y' if d else '·'):>5} {('Y' if r else '·'):>5}")
    if not any_hit:
        print("  (no markers matched)")


if __name__ == "__main__":
    main()
