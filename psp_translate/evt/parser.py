"""Parser per-event TEST.EVT — ekstrak dialog bubbles + bytecode regions.

Memakai struktur yang dihasilkan oleh `evt_header.py` dan char_table.json.

Heuristik bubble:
  - Cari pattern `e3 08` (SPEAKER tag start) → diikuti bytes nama speaker
    sampai `f8 e3` (line break + dialog start). Dialog berlanjut sampai byte
    terminator `fe` (end-of-string).
  - Untuk dialog non-speaker (mis. prayer dengan `e2 02`), bubble tetap
    dideteksi sebagai run text yang berakhir di `fe`.
  - Region di antara bubble (yang banyak mengandung `f1`, `e5`, `d1`, dll.)
    di-tag sebagai bytecode.

Skema control codes yang TERIDENTIFIKASI sejauh ini (lihat tools/EVT_FORMAT.md
untuk dokumentasi lengkap):
  fe         = end-of-string / end-of-bubble
  f8         = soft line break dalam bubble
  e3 08      = SPEAKER tag start (diikuti nama, lalu `f8 e3` ke dialog)
  e2 02      = paragraph marker (prayer / narration)
  e2 06      = paragraph sub-marker (mis. setelah comma)
  e0         = placeholder nama player (Ramza)
  f1 XX 00   = opcode 3 byte (parameter LE16, sering dipakai di script)
  e5 XX 00   = opcode 3 byte (event/flag marker)
  d1 XX      = 2-byte text/code prefix (XX = sub-glyph atau opcode)
  d2-d9 XX   = prefix kelompok lain (multi-byte glyph atau opcode)
  da XX      = punctuation/special char prefix (cth: da 74 = ',')

CLI:
    python tools/evt_parser.py <file.evt> <struct.json> --output <out.json>
    python tools/evt_parser.py <file.evt> <struct.json> --output <out.json> --event-id 1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from psp_translate.codec.decode import decode, load_table
from psp_translate import paths

# Markers
BYTE_EOS = 0xFE
BYTE_SOFT_LB = 0xF8
TAG_SPEAKER = b"\xe3\x08"
TAG_DIALOG_AFTER_SPEAKER = b"\xf8\xe3"
TAG_PRAYER = b"\xe2\x02"
TAG_PARAGRAPH_SUB = b"\xe2\x06"


def _classify_chunk(chunk: bytes) -> tuple[str, int]:
    """Klasifikasi sebuah chunk yang diakhiri 0xFE.

    Return (kind, text_start_offset_within_chunk).
    kind ∈ {"speaker", "narration", "untranslated", "text"}.
      - "speaker": chunk berisi pola `e3 08 ... f8 e3` di awal.
      - "narration": chunk mengandung `e2 02` (prayer/narration paragraph).
      - "untranslated": density byte d1-d9 (kemungkinan glyph kanji/kana
        yang belum di-map) ≥ 30% dari body.
      - "text": chunk ASCII English biasa tanpa marker khusus.
    """
    if chunk.startswith(TAG_SPEAKER):
        sep = chunk.find(TAG_DIALOG_AFTER_SPEAKER, 2)
        if sep != -1:
            return "speaker", sep + 2
    if TAG_PRAYER in chunk:
        # contains a paragraph/prayer marker somewhere
        return "narration", 0
    body = chunk[:-1] if chunk.endswith(b"\xfe") else chunk
    if body:
        n_prefix = sum(1 for b in body if 0xD1 <= b <= 0xD9)
        if n_prefix * 10 >= len(body) * 3:  # >= 30%
            return "untranslated", 0
    return "text", 0


def find_bubbles(
    data: bytes,
    base: int,
    end: int,
    mapping: dict[int, str],
    multibyte: dict[bytes, str],
) -> list[dict]:
    """Scan [base, end) untuk semua bubble (chunk berakhir di 0xFE).

    Bubble dideteksi dengan split berdasarkan terminator `0xFE`. Tiap chunk
    diklasifikasi (speaker / narration / untranslated / text). Speaker name
    diekstrak kalau ada pola `e3 08 ... f8 e3`.
    """
    bubbles = []
    i = base
    chunk_start = base
    while i < end:
        if data[i] == BYTE_EOS:
            chunk_end = i + 1
            chunk = data[chunk_start:chunk_end]
            # Trim leading zero padding inside chunk (rare)
            lead_zeros = 0
            while lead_zeros < len(chunk) and chunk[lead_zeros] == 0x00:
                lead_zeros += 1
            real_start = chunk_start + lead_zeros
            real_chunk = chunk[lead_zeros:]
            if real_chunk and len(real_chunk) > 1:
                kind, text_off = _classify_chunk(real_chunk)
                speaker = None
                if kind == "speaker":
                    # Extract speaker name (bytes 2..text_off-2)
                    name_bytes = real_chunk[2 : text_off - 2]
                    speaker = decode(
                        name_bytes, mapping, multibyte, annotate_unknown=True
                    ).strip()
                # IMPORTANT: skip_padding=False supaya byte 0x00 di tengah text
                # (yang part of encoding) tetap muncul sebagai <00> dan bisa
                # di-roundtrip perfectly via encode_evt.py.
                text = decode(
                    real_chunk[:-1], mapping, multibyte,
                    skip_padding=False, annotate_unknown=True
                )
                bubbles.append(
                    {
                        "kind": kind,
                        "speaker": speaker,
                        "text": text,
                        "raw_byte_range": [real_start, chunk_end],
                    }
                )
            chunk_start = chunk_end
        i += 1
    return bubbles


def classify_bytecode_regions(
    bubble_ranges: list[tuple[int, int]],
    base: int,
    end: int,
) -> list[tuple[int, int]]:
    """Return list of (start, end) for non-bubble (bytecode) regions."""
    sorted_b = sorted(bubble_ranges)
    regions = []
    cursor = base
    for bs, be in sorted_b:
        if bs > cursor:
            regions.append((cursor, bs))
        cursor = max(cursor, be)
    if cursor < end:
        regions.append((cursor, end))
    return regions


def parse_event(
    data: bytes,
    event: dict,
    mapping: dict[int, str],
    multibyte: dict[bytes, str],
    include_bytecode_hex: bool = True,
    max_bytecode_hex_per_region: int = 256,
) -> dict:
    base = event["offset"]
    size = event["size"]
    # Strip trailing zero padding from search range
    end = base + size - event.get("trailing_padding", 0)
    # Skip the constant prologue (0x800) if present
    scan_start = base + 0x800 if event.get("shares_common_prologue") else base + 4

    bubbles = find_bubbles(data, scan_start, end, mapping, multibyte)
    bubble_ranges = [tuple(b["raw_byte_range"]) for b in bubbles]
    bc_regions = classify_bytecode_regions(bubble_ranges, scan_start, end)

    bytecode_summary = []
    for bs, be in bc_regions:
        region = {
            "start": bs,
            "end": be,
            "length": be - bs,
        }
        if include_bytecode_hex:
            chunk = data[bs:be]
            if len(chunk) > max_bytecode_hex_per_region:
                region["hex_preview"] = (
                    chunk[:max_bytecode_hex_per_region].hex(" ")
                    + f" ... (+{len(chunk) - max_bytecode_hex_per_region} bytes)"
                )
            else:
                region["hex_preview"] = chunk.hex(" ")
        bytecode_summary.append(region)

    return {
        "event_id": event["index"],
        "offset": base,
        "offset_hex": f"0x{base:06x}",
        "size": size,
        "size_hex": f"0x{size:x}",
        "scan_start": scan_start,
        "scan_end": end,
        "num_bubbles": len(bubbles),
        "bubbles": bubbles,
        "bytecode_regions": bytecode_summary,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    ap.add_argument("file", type=Path, help="TEST.EVT path")
    ap.add_argument("struct", type=Path, help="evt_structure.json from evt_header.py")
    ap.add_argument(
        "--output", "-o", type=Path, required=True, help="Output JSON path"
    )
    ap.add_argument(
        "--table",
        type=Path,
        default=paths.CHAR_TABLE,
        help="char_table.json path (default: data/char_table.json)",
    )
    ap.add_argument(
        "--event-id",
        type=int,
        default=None,
        help="Only parse one event by index (default: all)",
    )
    ap.add_argument(
        "--no-bytecode-hex",
        action="store_true",
        help="Omit hex previews of bytecode regions (smaller JSON)",
    )
    args = ap.parse_args()

    data = args.file.read_bytes()
    struct = json.loads(args.struct.read_text())
    mapping, multibyte = load_table(args.table)

    events_in = struct["events"]
    if args.event_id is not None:
        events_in = [e for e in events_in if e["index"] == args.event_id]
        if not events_in:
            print(f"event-id {args.event_id} not found", file=sys.stderr)
            return 2

    results = []
    for ev in events_in:
        results.append(
            parse_event(
                data,
                ev,
                mapping,
                multibyte,
                include_bytecode_hex=not args.no_bytecode_hex,
            )
        )

    out = {
        "source_file": str(args.file),
        "num_events_parsed": len(results),
        "events": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, indent=2, ensure_ascii=False))

    total_bubbles = sum(r["num_bubbles"] for r in results)
    print(f"Parsed {len(results)} event(s), {total_bubbles} bubble(s) total")
    print(f"Output: {args.output}")
    if args.event_id is not None and results:
        r = results[0]
        print(f"\nEvent {r['event_id']} @ {r['offset_hex']} ({r['num_bubbles']} bubbles):")
        for b in r["bubbles"][:5]:
            spk = b.get("speaker") or f"({b.get('kind', 'text')})"
            preview = b["text"][:80].replace("\n", " ")
            print(f"  [{spk}] {preview}")
        if r["num_bubbles"] > 5:
            print(f"  ... +{r['num_bubbles'] - 5} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
