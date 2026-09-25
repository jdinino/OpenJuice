# Research Index

The `research/` folder holds the raw material behind this project: device dumps, packet captures,
recovered firmware and archived vendor documentation. **It is git-ignored** — it is large (about
190 MB), some of it carries device credentials, and some has unclear redistribution rights. This
index records what is there, where it came from, and how to obtain it again, so the checked-in docs
can cite it without shipping it.

**Credentials.** `research/JuiceBox-Gen1-Pentest-RE.UNREDACTED.md` and the `*-live-config-*.txt`
dumps contain the home WiFi passkey and device identifiers. Keep them local. The redacted assessment
in `docs/juicebox/` is the shareable version.

**Licensing.** Recovered eMotorWerks firmware is GPL v3 and carries its headers. The
`vinay-emw/JuiceBoxTester` factory test firmware has **no license**, so it is referenced by URL and
commit only and is not redistributed. The Zentri SDK installer is a vendor binary, kept for
reference, not redistributed.

---

## Device dumps from the reference unit

| Path | What it is | How to reproduce |
|---|---|---|
| `juicebox-module-backup-2026-09-20/` | 97 files pulled from the module's flash over HTTP: energy logs, `index.html`, the CA cert, three system binaries | `for f in $(ls output); do curl http://<charger>/$f; done` after listing with `ls` |
| `amw006-live-config-2026-09-14.txt`, `-2026-09-19-postreboot.txt` | Full `get all` from the live module | `curl http://<charger>/command/get%20all` |
| `amw006-devboard-config-2026-02-28.txt` | `get all` from a **dev board**, not this charger; WiConnect era. Kept to show the AMW006/AMW106 difference | — |
| `evse-juicenet-capture-2026-02-27.pcap` | ~10 min capture, 1,478 packets, the original security assessment | router-side `tcpdump host <charger>` |
| `JuiceBox-Gen1-Pentest-RE.UNREDACTED.md` | The assessment with credentials intact | redacted copy is in `docs/juicebox/` |

The folder is named `amw006-*` for historical reasons; the part is **AMW106** (FSD §2.3).

## Recovered eMotorWerks firmware and hardware files

| Path | What it is | Source |
|---|---|---|
| `v810-hunt/community/` | JuiceBox firmware source ZIPs V8.9.1 through **V8.10.7**, extracted sketches, and `PROVENANCE.md` with per-file hashes | 2017 GitHub mirror `arsen3d/JuiceBox`; verified against its git tree and Software Heritage |
| `v810-hunt/archive-org/` | Directory listings and V8.9/V8.10-era build/cabling documents, with `PROVENANCE.md` | Wayback Machine captures of `emotorwerks.com/JuiceBox_Public/` |
| `emotorwerks-JuiceBox_Public/` | Mirror of the vendor's public file share: V8.6 schematic, board layouts, assembly manuals, hex images | Wayback Machine |
| `emotorwerks-archive-8.9/` | V8.9 board layout (`.rrb` and decompressed text) and stock hex images | as above |
| `vinay-emw-JuiceBoxTester/` | v8.12 factory board-test firmware, the source of the v8.12 pin map | GitHub `vinay-emw/JuiceBoxTester`; **no license**, reference by URL and commit only |
| `valerun-JB_V9.0/` | A V8.9.1 firmware variant with two-way serial | GitHub `valerun/JB_V9.0` |

## Archived vendor documentation and tooling

| Path | What it is | Source |
|---|---|---|
| `zentrios-wz-docs/` | ZentriOS-WZ 3.6 command and variable reference this unit runs | Wayback Machine captures of `docs.zentri.com` |
| `zentri-sdk/` | The ZentriOS SDK installer, 18.9 MB, with its sha256 | `resources.zentri.com`; vendor binary, not redistributed |

## Notes

- The reference unit's IP has changed over time; discover it from the UDP 55555 beacon rather than
  hardcoding it.
- Provenance files (`PROVENANCE.md`) inside `v810-hunt/` carry the exact source URL, capture
  timestamp, size and sha256 for each recovered file.
