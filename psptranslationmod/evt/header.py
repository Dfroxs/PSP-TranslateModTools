"""Parser struktur file TEST.EVT (FFT WoTL PSP).

Hasil reverse engineering:
  - File terdiri dari N "event chunks" yang independen.
  - Setiap chunk dimulai dengan magic 4 byte `f2 f2 f2 f2`.
  - Posisi semua chunk selalu aligned pada batas 0x800 (2048 byte / 1 sektor).
  - Tidak ada tabel pointer global di awal file. Pointer table di awal file
    SEMU karena bytes setelah magic langsung berupa bytecode/script
    (banyak opcode `f1 XX 00`, `e5 XX 00`, dst).
  - Cara mendeteksi event = scan semua kemunculan magic `f2 f2 f2 f2` di posisi
    aligned 0x800. Ukuran event[i] = offset(event[i+1]) - offset(event[i])
    (atau file_size - offset(last) untuk event terakhir).
  - Setiap event punya "prologue" 0x800 byte yang sama (bytecode init/setup),
    diikuti konten unik. 201 dari 231 event memiliki prologue identik.

CLI:
    python tools/evt_header.py <file.evt> --output <struct.json>
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

SECTOR_SIZE = 0x800
MAGIC = b"\xf2\xf2\xf2\xf2"


def find_events(data: bytes) -> list[int]:
    """Return list of event start offsets (aligned to SECTOR_SIZE)."""
    positions = []
    for m in re.finditer(re.escape(MAGIC), data):
        off = m.start()
        if off % SECTOR_SIZE == 0:
            positions.append(off)
    return positions


def parse_structure(data: bytes) -> dict:
    n = len(data)
    if data[:4] != MAGIC:
        raise ValueError(
            f"Bad magic at offset 0: got {data[:4].hex()}, expected {MAGIC.hex()}"
        )

    positions = find_events(data)
    if not positions:
        raise ValueError("No event chunks found (magic f2f2f2f2 missing)")

    # Sanity: monotonic + all in range
    for i in range(1, len(positions)):
        assert positions[i] > positions[i - 1], "Positions not monotonic"
    assert positions[-1] < n, "Last event past EOF"

    # Reference prologue (first 0x800 of event 0)
    ref_prologue = data[: SECTOR_SIZE]
    prologue_match_count = sum(
        1 for p in positions if data[p : p + SECTOR_SIZE] == ref_prologue
    )

    events = []
    for i, off in enumerate(positions):
        end = positions[i + 1] if i + 1 < len(positions) else n
        size = end - off
        # Detect trailing zero padding length
        # (event payload often padded to SECTOR_SIZE boundary with 0x00)
        trail = 0
        j = end - 1
        while j >= off and data[j] == 0x00:
            trail += 1
            j -= 1
        events.append(
            {
                "index": i,
                "offset": off,
                "offset_hex": f"0x{off:06x}",
                "size": size,
                "size_hex": f"0x{size:x}",
                "trailing_padding": trail,
                "shares_common_prologue": data[off : off + SECTOR_SIZE]
                == ref_prologue,
            }
        )

    return {
        "format": "fft-wotl-psp-test-evt-v1",
        "file_size": n,
        "magic": MAGIC.hex(),
        "sector_size": SECTOR_SIZE,
        "num_events": len(events),
        "common_prologue_size": SECTOR_SIZE,
        "events_with_common_prologue": prologue_match_count,
        "events": events,
        "notes": [
            "Event chunks aligned to 0x800 (sector) boundaries.",
            "Each chunk = magic(4) + ~0x7fc bytes common bytecode prologue + unique script + 0x00 padding to next 0x800.",
            "No file-level pointer table; events located by scanning for magic at 0x800-aligned offsets.",
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    ap.add_argument("file", type=Path, help="TEST.EVT file path")
    ap.add_argument("--output", "-o", type=Path, required=True, help="Output JSON path")
    ap.add_argument(
        "--print-summary",
        action="store_true",
        help="Print short summary to stdout",
    )
    args = ap.parse_args()

    data = args.file.read_bytes()
    struct = parse_structure(data)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(struct, indent=2))

    print(f"Parsed {struct['num_events']} events from {args.file}")
    print(f"  File size: {struct['file_size']:,} bytes")
    print(f"  Events sharing common prologue: "
          f"{struct['events_with_common_prologue']}/{struct['num_events']}")
    print(f"  Output: {args.output}")

    if args.print_summary:
        print("\nFirst 10 events:")
        for ev in struct["events"][:10]:
            print(
                f"  evt[{ev['index']:3}] @{ev['offset_hex']} "
                f"size={ev['size_hex']} pad={ev['trailing_padding']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
