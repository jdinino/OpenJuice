# firmware/

> 🛑 **Nothing in this folder is safe to flash to a real charger yet.** Both files encode the
> **PCB V8.9** pin map. Later boards changed the relay, current-sensing and GFI test pins. See
> [../docs/STATUS.md](../docs/STATUS.md).

| File | What it is |
|---|---|
| `openevse-juicebox-gen1.patch` | Patch against upstream [OpenEVSE](https://github.com/OpenEVSE/open_evse) adding a `JUICEBOX_GEN1` build target: pin remap, GFI D-latch reset, pilot thresholds, PlatformIO environment. Pin block is **V8.9 only**. |
| `juicebox_gen1_v0.1_V8.9-pinmap.hex` | The v0.1 build of that patch, committed 2026-02-27. 12,450 bytes of code. Kept as a build reference only; it predates every correction since, including the missing GFI self-test. |

## Provenance (researched 2026-09-25)

| Question | Answer | Evidence |
|---|---|---|
| Who wrote it | This project, 2026-02-27, in an AI-assisted session: commit `bfe2ef1`, co-authored by Claude Opus 4.6 | git history |
| Copied from elsewhere? | No. GitHub code search finds `JUICEBOX_GEN1` and `GFI_LATCH_RESET_PIN` nowhere else | code search, 0 hits |
| Upstream base | **OpenEVSE 8.2.3**, `OpenEVSE/open_evse` master at `8e492981fa` (2025-01-07) or `944537dcc1` (2026-02-03); the five patched files are identical in both | the patch's `index` pre-image hashes match those upstream blobs exactly |
| Was the base current? | No. Upstream had already changed three of the five files by 2026-02-20, a week before the patch; the local checkout was stale | upstream file history |
| Pin map source | eMotorWerks' V8.9 firmware; matches the V8.9 branch of eMotorWerks' V8.10.7 source exactly | source comparison |
| The hex | A build of this patch on 8.2.3: embeds `8.2.3.OJ` and OpenEVSE's RAPI version `5.2.1`; 12,450 bytes of code, matching the commit's build stats | string extraction |

**Upstream has moved on.** OpenEVSE is at 9.0.0, 72 commits and 300 files past the patch's base,
including safety-relevant fixes: GFI retry-count handling, a watchdog pat during the GFI self-test,
relay zero-cross switching and a bounded current-zero wait. The patch does not apply cleanly to
current master, since three of its five files have changed. **Rebase onto current OpenEVSE in
Phase 4** rather than building on 8.2.3.

## Known state of the patch

- **Pin map:** V8.9. It matches eMotorWerks' own V8.9 branch exactly, so it is a correct V8.9
  port, not a port for this unit's board. The per-revision comparison is in the FSD.
- **Upload:** `upload_protocol = arduino`, `upload_speed = 57600`, and no chip erase. A chip erase
  would destroy the bootloader and the stock EEPROM.
- **GFI self-test:** off. It is disabled as a side effect of excluding `UL_COMPLIANT`. Ground-fault
  *detection* stays on.
- **Current sensing:** reads a current transformer on an analog pin, as V8.9 and V8.10 do. Boards
  from v8.12 use an ATM90E26 metering chip over serial instead, which needs a new driver.

## Order of operations before any flash

1. Read the board revision from the side sticker.
2. Dump the stock flash and EEPROM, twice, and confirm the dumps match and are not blank.
3. Establish every safety-critical pin electrically: relay, pilot PWM and sense, GFI sense, test and
   latch reset, current and voltage sensing.
4. Edit the `JUICEBOX_GEN1` pin block to match, rebuild, and rehearse on a spare board first.

The full procedure, with the reasoning behind each gate, is Stage B in
[../docs/STATUS.md](../docs/STATUS.md).
