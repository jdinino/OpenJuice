#!/usr/bin/env python3
"""Parse the .NET metadata #Strings heap from the decompressed Generac assemblies
to answer: what is SENT (request models/fields + PII), what is STORED, what can be
UNDONE. Focuses on the enrollment/registration path."""
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
    o = 20 + name2idx[name] * 24
    do, ds = struct.unpack("<6I", blob[o:o + 24])[:2]
    c = blob[do:do + ds]
    return lz4d(c[12:]) if c[:4] == b"XALZ" else c

def strings_heap(dll):
    """Return the ordered list of names from the .NET #Strings heap."""
    b = dll.find(b"BSJB")
    if b < 0:
        return []
    p = b + 4
    p += 8                                   # major,minor,reserved
    vlen = struct.unpack("<I", dll[p:p + 4])[0]; p += 4
    p += (vlen + 3) & ~3                      # version string padded
    p += 2                                    # flags
    nstreams = struct.unpack("<H", dll[p:p + 2])[0]; p += 2
    heaps = {}
    for _ in range(nstreams):
        off, size = struct.unpack("<II", dll[p:p + 8]); p += 8
        name = b""
        while dll[p] != 0:
            name += dll[p:p + 1]; p += 1
        p += 1
        p = (p + 3) & ~3
        heaps[name.decode()] = (b + off, size)
    if "#Strings" not in heaps:
        return []
    so, ss = heaps["#Strings"]
    raw = dll[so:so + ss]
    return [s.decode("utf-8", "replace") for s in raw.split(b"\x00") if s]


def analyze(name):
    dll = asm(name)
    names = strings_heap(dll)
    nameset = set(names)
    print(f"\n################ {name}  ({len(dll):,}B, {len(names)} metadata names) ################")

    # 1. request/response DTOs
    dtos = sorted({n for n in nameset if n.endswith(("Request", "Response")) and n[0].isupper()})
    print(f"\n[1] Request/Response DTOs ({len(dtos)}):")
    for d in dtos:
        print("   ", d)

    # 2. cluster around enrollment/register types (definition-order neighbours = likely fields)
    print("\n[2] #Strings neighbourhood of enrollment/register/device types:")
    targets = [n for n in names if re.search(r"(Enroll|Register|ValidateDevice|AddDevice|Provision)", n)
               and "Async" not in n and "<" not in n and "d__" not in n]
    seen_idx = set()
    for i, n in enumerate(names):
        if n in targets and i not in seen_idx:
            lo, hi = max(0, i - 1), min(len(names), i + 22)
            window = [names[j] for j in range(lo, hi)]
            seen_idx.update(range(lo, hi))
            print(f"   ~ {n}: {window}")

    # 3. PII / personal / payment fields anywhere
    PII = re.compile(r"^(Address|Street|City|State|Province|Zip|Postal|Country|Region|"
                     r"Latitude|Longitude|Lat|Lng|FirstName|LastName|MiddleName|FullName|"
                     r"Email|Phone|Mobile|PhoneNumber|DateOfBirth|Dob|Ssn|Social|"
                     r"CreditCard|Card|Cvv|Payment|BillingAddress|AccountHolder|"
                     r"Password|Pin|Token|Nickname|ContactInfo|Contact)$", re.I)
    pii = sorted({n for n in nameset if PII.match(n)})
    print(f"\n[3] PII / sensitive field names present ({len(pii)}):")
    print("   ", pii)

    # 4. undo surface
    undo = sorted({n for n in nameset if re.match(r"(Delete|Remove|Disable|Deregister|Unenroll|Unlink|Cancel|OptOut)", n)
                   and "Async" not in n and "<" not in n and n[0].isupper()})
    print(f"\n[4] delete/remove/disable operations ({len(undo)}):")
    for u in undo:
        print("   ", u)

    # 5. storage indicators
    store = sorted({n for n in nameset if re.search(r"(Keychain|SecureStorage|Sqlite|Database|Table|Cache|Preferences|Settings|Persist|Store)", n)
                    and "<" not in n and len(n) < 40})
    print(f"\n[5] storage-related types ({len(store)}):")
    print("   ", store[:40])


for a in ["Generac.Application.MobileLink.ApiClient",
          "Generac.Application.MobileLink.Mobile.Common"]:
    analyze(a)
