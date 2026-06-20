"""Automated verification of the repack_evt.py --allow-stretch path.

Konteks: jalur stretch (ID lebih PANJANG dari original → extend ke trailing
zero buffer) belum pernah diverifikasi (lihat TODO_PLAN.md Fase 7). Bahaya yang
didokumentasikan: "bisa menggeser posisi terminator" → dialog ke-split / nama
speaker hilang (regresi yang sama yang diperbaiki di commit 5524b89).

Test ini membuktikan secara PROGRAMATIS (tanpa booting PPSSPP) bahwa stretch:
  1. Tidak mengubah ukuran file.
  2. HANYA mengubah byte di dalam region bubble target (tidak menyentuh
     bubble tetangga / event berikutnya).
  3. Menulis PERSIS SATU terminator 0xFE, di posisi akhir teks baru.
  4. Region setelah terminator baru tetap zero (buffer tidak rusak).
  5. Bubble target decode kembali ke teks ID yang diminta (roundtrip).
  6. Semua bubble lain decode IDENTIK dengan original.
Plus kontrol negatif: tanpa --allow-stretch, translasi yang sama di-SKIP dan
output byte-identik dengan original (tidak ada perubahan diam-diam).

Pakai:
    python tools/test_stretch_path.py
    python tools/test_stretch_path.py --emit-translations /tmp/stretch_trans.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow `python tests/test_stretch_path.py` (script mode); `-m tests.test_stretch_path` works without this.
if __name__ == '__main__' and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from psp_translate.evt.repack import repack, count_trailing_zeros, BYTE_EOS
from psp_translate.codec.encode import encode_string, load_table as load_encode_table
from psp_translate.codec.decode import decode, load_table as load_decode_table
from psp_translate import paths

TEST_EVT = paths.ORIGINAL_TEST_EVT
EVENTS_PARSED = paths.EVENTS_PARSED
CHAR_TABLE = paths.CHAR_TABLE

TRANSLATABLE_KINDS = {'text', 'narration', 'speaker'}

# Berapa target stretch yang diuji, di event berbeda-beda.
MIN_EXTRA_BYTES = 12   # paksa ID minimal sekian byte lebih panjang dari original
MAX_TARGETS = 8


class Fail(Exception):
    pass


def build_bubbles_by_id(events: list[dict]) -> dict[int, dict]:
    """Replika persis logika indexing di repack_evt.repack()."""
    bubbles_by_id: dict[int, dict] = {}
    block_id = 0
    for event in events:
        for bubble in event.get('bubbles', []):
            if bubble.get('kind') in TRANSLATABLE_KINDS:
                bubbles_by_id[block_id] = bubble
                block_id += 1
    return bubbles_by_id


def bubble_range(bubble: dict) -> tuple[int, int] | None:
    br = bubble.get('raw_byte_range') or bubble.get('byte_range')
    if br:
        return br[0], br[1]
    bs, be = bubble.get('byte_start'), bubble.get('byte_end')
    if bs is None or be is None:
        return None
    return bs, be


def select_targets(data: bytes, bubbles_by_id: dict[int, dict],
                   enc_tables) -> list[dict]:
    """Pilih bubble yang punya adjacent zero buffer cukup besar, dari banyak event."""
    char_to_byte, char_to_multibyte, name_to_bytes = enc_tables
    seen_events: set = set()
    targets: list[dict] = []
    for tid, bubble in bubbles_by_id.items():
        rng = bubble_range(bubble)
        if not rng:
            continue
        bs, be = rng
        orig_len = be - bs
        if orig_len < 2:
            continue
        text = bubble.get('text', '')
        # hanya teks yang encode-nya tepat == orig_len (roundtrip bersih) supaya
        # perhitungan overflow deterministik.
        enc = encode_string(text, char_to_byte, char_to_multibyte, name_to_bytes)
        if not enc.endswith(b'\xfe'):
            enc = enc + b'\xfe'
        if len(enc) != orig_len:
            continue
        buffer = count_trailing_zeros(data, be)
        if buffer < MIN_EXTRA_BYTES + 4:
            continue
        ev = bubble.get('_event_id')
        # satu target per event biar tersebar
        key = ev
        if key in seen_events:
            continue
        seen_events.add(key)
        targets.append({'id': tid, 'bubble': bubble, 'byte_start': bs,
                        'byte_end': be, 'orig_len': orig_len, 'buffer': buffer,
                        'en_text': text})
        if len(targets) >= MAX_TARGETS:
            break
    return targets


def make_stretched_text(en_text: str, extra: int) -> str:
    """Bangun teks ID yang preserve semua control token original + tambah `extra`
    byte plain (huruf/spasi = 1 byte/char) supaya melewati panjang original."""
    suffix = ' ' + 'X' * (extra - 1) if extra >= 1 else ''
    return en_text + suffix


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--emit-translations', type=Path,
                    help='Tulis translations.json (untuk dipakai translate_pipeline)')
    args = ap.parse_args()

    for p in (TEST_EVT, EVENTS_PARSED, CHAR_TABLE):
        if not p.exists():
            print(f'error: required file missing: {p}', file=sys.stderr)
            return 2

    data = TEST_EVT.read_bytes()
    events = json.loads(EVENTS_PARSED.read_text())
    events = events.get('events', events) if isinstance(events, dict) else events
    enc_tables = load_encode_table(CHAR_TABLE)
    dec_mapping, dec_multibyte = load_decode_table(CHAR_TABLE)

    # annotate event id ke tiap bubble (untuk distribusi target)
    for ev in events:
        for b in ev.get('bubbles', []):
            b['_event_id'] = ev.get('event_id')

    bubbles_by_id = build_bubbles_by_id(events)
    print(f'Total translatable bubbles: {len(bubbles_by_id)}')

    targets = select_targets(data, bubbles_by_id, enc_tables)
    if not targets:
        print('error: tidak ada target stretch yang cocok ditemukan', file=sys.stderr)
        return 2

    print(f'\nDipilih {len(targets)} target stretch (1 per event):')
    translations: dict[int, str] = {}
    expected: dict[int, dict] = {}
    for t in targets:
        extra = MIN_EXTRA_BYTES
        id_text = make_stretched_text(t['en_text'], extra)
        enc = encode_string(id_text, *enc_tables)
        if not enc.endswith(b'\xfe'):
            enc = enc + b'\xfe'
        translations[t['id']] = id_text
        expected[t['id']] = {
            'encoded': enc,
            'new_len': len(enc),
            'byte_start': t['byte_start'],
            'byte_end': t['byte_end'],
            'orig_len': t['orig_len'],
            'buffer': t['buffer'],
        }
        ev = t['bubble'].get('_event_id')
        print(f"  id={t['id']:>5} evt={ev:>3} orig_len={t['orig_len']:>4} "
              f"new_len={len(enc):>4} overflow={len(enc)-t['orig_len']:>3} "
              f"buffer={t['buffer']:>5}  en={t['en_text'][:34]!r}")

    failures: list[str] = []

    # ---- POSITIVE: with --allow-stretch ----
    out, stats = repack(data, events, dict(translations), CHAR_TABLE,
                        allow_truncate=False, allow_stretch=True)

    def check(cond: bool, msg: str):
        if not cond:
            failures.append(msg)

    check(len(out) == len(data),
          f'[A1] size berubah: {len(out)} != {len(data)}')
    check(stats['applied_stretched'] == len(targets),
          f"[A2] applied_stretched={stats['applied_stretched']} != {len(targets)}")
    check(stats['skipped_too_long'] == 0,
          f"[A2] skipped_too_long={stats['skipped_too_long']} (harus 0)")
    check(stats['truncated'] == 0,
          f"[A2] truncated={stats['truncated']} (harus 0)")
    check(stats['applied'] == 0,
          f"[A2] applied(in-place)={stats['applied']} (harus 0, semua stretch)")

    # Region byte yang berubah harus 100% di dalam region target.
    allowed = bytearray(len(data))  # 1 = boleh berubah
    for tid, e in expected.items():
        for i in range(e['byte_start'], e['byte_start'] + e['new_len']):
            allowed[i] = 1
    changed_outside = []
    out_b = out
    for i in range(len(data)):
        if out_b[i] != data[i] and not allowed[i]:
            changed_outside.append(i)
            if len(changed_outside) > 5:
                break
    check(not changed_outside,
          f'[A3] {len(changed_outside)} byte berubah DI LUAR region target '
          f'(contoh offset: {changed_outside[:5]}) → bubble tetangga rusak!')

    # Per-target: tepat satu 0xFE di posisi akhir; sisa buffer tetap zero;
    # roundtrip decode == teks yang ditulis.
    for tid, e in expected.items():
        bs, new_len, orig_len, buf = (e['byte_start'], e['new_len'],
                                      e['orig_len'], e['buffer'])
        region = out_b[bs:bs + new_len]
        # 6a. bytes ditulis == encoded yang diharapkan
        check(bytes(region) == e['encoded'],
              f'[B id={tid}] bytes region != encoded yang diharapkan')
        # 6b. tepat satu 0xFE, di byte terakhir region
        fe_positions = [j for j, bb in enumerate(region) if bb == BYTE_EOS]
        check(fe_positions == [new_len - 1],
              f'[B id={tid}] posisi 0xFE = {fe_positions}, '
              f'harus tepat satu di {new_len - 1}')
        # 6c. buffer setelah terminator baru tetap zero (sampai akhir buffer asli)
        old_end = bs + orig_len            # = byte_end original
        buf_end = old_end + buf            # akhir zero buffer asli
        new_end = bs + new_len             # akhir teks baru (terminator)
        zero_tail = out_b[new_end:buf_end]
        check(all(z == 0 for z in zero_tail),
              f'[B id={tid}] zero buffer rusak setelah terminator baru '
              f'(ada non-zero di {new_end}..{buf_end})')
        # 6d. roundtrip decode region == decode dari encoded yang diminta
        dec_region = decode(bytes(region), dec_mapping, dec_multibyte)
        dec_expected = decode(e['encoded'], dec_mapping, dec_multibyte)
        check(dec_region == dec_expected,
              f'[B id={tid}] decode region != decode expected')

    # 7. Semua bubble NON-target decode identik (cek eksplisit bubble setelah tiap target)
    target_ids = set(expected)
    sample_checks = 0
    for tid in sorted(target_ids):
        for follow in range(tid + 1, tid + 6):
            b = bubbles_by_id.get(follow)
            if not b:
                continue
            rng = bubble_range(b)
            if not rng:
                continue
            fs, fe = rng
            before = decode(data[fs:fe], dec_mapping, dec_multibyte)
            after = decode(out_b[fs:fe], dec_mapping, dec_multibyte)
            check(before == after,
                  f'[C] bubble#{follow} (setelah target {tid}) decode BERUBAH:\n'
                  f'    before={before[:60]!r}\n    after ={after[:60]!r}')
            sample_checks += 1

    # ---- NEGATIVE control: tanpa --allow-stretch ----
    out_neg, stats_neg = repack(data, events, dict(translations), CHAR_TABLE,
                                allow_truncate=False, allow_stretch=False)
    check(stats_neg['skipped_too_long'] == len(targets),
          f"[N1] tanpa stretch: skipped_too_long={stats_neg['skipped_too_long']} "
          f'!= {len(targets)}')
    check(stats_neg['applied_stretched'] == 0,
          f"[N1] tanpa stretch: applied_stretched={stats_neg['applied_stretched']} != 0")
    check(bytes(out_neg) == data,
          '[N2] tanpa stretch output TIDAK byte-identik dengan original '
          '(ada perubahan diam-diam!)')

    # ---- Report ----
    print(f'\n--- Assertions ---')
    print(f'  region target di-stretch : {len(targets)}')
    print(f'  bubble tetangga dicek    : {sample_checks}')
    print(f'  byte berubah di luar region target: {len(changed_outside)}')
    if failures:
        print(f'\n❌ FAIL ({len(failures)} masalah):')
        for f in failures:
            print(f'  - {f}')
        return 1

    print('\n✅ PASS — jalur stretch terbukti aman secara programatis:')
    print('   • ukuran file tetap, hanya region target berubah')
    print('   • tepat satu 0xFE per bubble, zero buffer utuh')
    print('   • bubble target roundtrip benar, bubble lain identik')
    print('   • kontrol negatif: tanpa --allow-stretch tidak ada perubahan')

    if args.emit_translations:
        # format blocks untuk translate_pipeline / repack_evt CLI
        blocks = [{'id': tid, 'en': expected_en, 'id_final': translations[tid]}
                  for tid, expected_en in
                  ((t['id'], t['en_text']) for t in targets)]
        payload = {'blocks': blocks,
                   'metadata': {'purpose': 'stretch-path in-game verification',
                                'note': 'each id_final = en + appended bytes to force stretch'}}
        args.emit_translations.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        print(f'\nTranslations untuk ISO test ditulis: {args.emit_translations}')

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
