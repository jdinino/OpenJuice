#!/usr/bin/env python3
"""Extract + LZ4-decompress the Generac .NET assemblies from the Xamarin XABA
store, then mine them for endpoints, auth flow, and telemetry models."""
import zipfile, struct, re, sys

APK = r"C:\Users\jdinino\AI\Mobile+Link+for+Generators_2.28.0.47091_APKPure.apk"
z = zipfile.ZipFile(APK)
blob = z.read("assemblies/assemblies.blob")
manifest = z.read("assemblies/assemblies.manifest").decode("latin1", "replace")

# name -> blob index from manifest
name2idx = {}
for ln in manifest.splitlines():
    parts = ln.split()
    if len(parts) >= 5 and parts[-2].isdigit():
        name2idx[parts[-1]] = int(parts[-2])

magic, version, local_cnt, global_cnt, store_id = struct.unpack("<5I", blob[:20])

def descriptor(i):
    off = 20 + i * 24
    return struct.unpack("<6I", blob[off:off + 24])  # data_off,size, dbg..., cfg...


def lz4_block_decompress(src):
    out = bytearray(); i = 0; n = len(src)
    while i < n:
        tok = src[i]; i += 1
        litlen = tok >> 4
        if litlen == 15:
            while True:
                b = src[i]; i += 1; litlen += b
                if b != 255: break
        out += src[i:i + litlen]; i += litlen
        if i >= n: break
        offset = src[i] | (src[i + 1] << 8); i += 2
        mlen = (tok & 15) + 4
        if (tok & 15) == 15:
            while True:
                b = src[i]; i += 1; mlen += b
                if b != 255: break
        start = len(out) - offset
        for j in range(mlen):
            out.append(out[start + j])
    return bytes(out)


def get_assembly(name):
    idx = name2idx[name]
    do, ds = descriptor(idx)[:2]
    chunk = blob[do:do + ds]
    if chunk[:4] == b"XALZ":
        _, xidx, usize = struct.unpack("<4sII", chunk[:12])
        return lz4_block_decompress(chunk[12:])
    return chunk


U8  = re.compile(rb"[\x20-\x7e]{4,}")
U16 = re.compile(rb"(?:[\x20-\x7e]\x00){4,}")

def strings_of(dll):
    s = set()
    for m in U8.finditer(dll):
        s.add(m.group().decode("latin1"))
    for m in U16.finditer(dll):
        s.add(m.group().decode("utf-16-le"))
    return s

URL   = re.compile(r"^https?://")
ROUTE = re.compile(r"(api/|/?Apparatus|gainspan|enrollment|/v\d|exercise|telemetry|maintenance|specifications|/Users|/Dealer|subscription)", re.I)
AUTH  = re.compile(r"(b2clogin|onmicrosoft|client_id|clientId|\bscope\b|authority|Bearer|Ocp-Apim|Subscription-Key|grant_type|redirect|tenant|policy|B2C_1|access_token|refresh_token|id_token)", re.I)
TELEM = re.compile(r"(batter|fuel|runHour|signalStrength|rssi|apparatusStatus|deviceState|serialNumber|apparatusId|deviceId|weather|voltage|exercise|maintenance|schedule)", re.I)
METH  = re.compile(r"(Async$|^Get[A-Z]|^Post[A-Z]|^Put[A-Z]|^Delete[A-Z]|Endpoint|BaseUrl|BasePath|Provision|Enroll|Authenticat|Token|Login|Refresh)")


def report(name):
    dll = get_assembly(name)
    ss = strings_of(dll)
    print(f"\n############### {name}  ({len(dll):,} B decompressed, {len(ss)} strings) ###############")
    def group(title, items, cap=50):
        items = sorted(set(items))
        print(f"\n--- {title} ({len(items)}) ---")
        for x in items[:cap]:
            print(f"   {x}")
    group("URLs", [s for s in ss if URL.match(s)])
    group("route/endpoint-ish", [s for s in ss if ROUTE.search(s) and len(s) < 90
                                 and not s.startswith(("System", "Microsoft", "Xamarin",
                                 "/System", "get_", "set_")) and " " not in s])
    group("auth / B2C / headers", [s for s in ss if AUTH.search(s) and len(s) < 120])
    group("telemetry model fields", [s for s in ss if TELEM.search(s) and len(s) < 60 and " " not in s])
    group("API method / client names", [s for s in ss if METH.search(s) and len(s) < 60
                                        and " " not in s and any(t in s for t in
                                        ("Apparatus","Exercise","Config","Network","Telemetry",
                                         "Enroll","Auth","Token","Login","Api","Endpoint","Provision",
                                         "Maintenance","Dealer","User","Refresh","Base"))])


for asm in ["Generac.Application.MobileLink.ApiClient",
            "Apparatus",
            "Generac.Application.MobileLink.Mobile.Common"]:
    try:
        report(asm)
    except Exception as e:
        print(f"\n!!! {asm}: {e}")
