# TUTORIAL — Translasi FFT WoTL EN → ID (dari ISO original sampai selesai)

Panduan praktis langkah-demi-langkah untuk **Final Fantasy Tactics: The War of
the Lions (PSP)**. Ikuti dari atas ke bawah. Setiap langkah ada perintahnya,
apa yang harus muncul, dan cara mengatasi error umum.

Referensi terkait:
- `README.md` — ringkasan proyek & daftar tool.
- `CLAUDE.md` — catatan arsitektur + invariant penting (bubble, control code).
- `TODO_PLAN.md` — roadmap berfase.

---

## 0. Prasyarat

| Butuh | Untuk | Catatan |
|-------|-------|---------|
| Python ≥ 3.8 | semua tool | pure stdlib (kecuali Gemini) |
| ISO FFT WoTL (USA) original | sumber & target patch | taruh di `games/` |
| `GEMINI_API_KEY` | auto-translate | `export GEMINI_API_KEY="AIza..."` |
| `google-genai` (pip) | SDK Gemini | `pip install google-genai` |
| PPSSPP | test in-game | wajib sebelum rilis |
| `xdelta3` (opsional) | bikin patch distribusi | `brew install xdelta` |

Cek API key sudah terisi:
```bash
[ -n "$GEMINI_API_KEY" ] && echo "API key SET" || echo "API key BELUM diset"
```

---

## Peta alur

```
ISO original ─(1)extract─► extracted/ ─► fftpack.bin ─► EVENT/TEST.EVT
                                                  │
        [reverse-engineer: SEKALI saja, sudah ada di repo]
                                                  ▼
                    events_parsed.json + char_table.json
                                                  │
   (2)build_workspace ─► workspace/chapter_*.json (EN + block-id)
                                                  │
   (3)translate_gemini ─► chapter_*.out.json ─(4)review id_final
                                                  │
   (5)translate_pipeline: validate→repack EVT→patch fftpack→patch ISO
                                                  ▼
                      ISO terjemahan (ukuran SAMA)
                                                  │
              (6)test PPSSPP ─► (7)xdelta3 patch ─► SELESAI
```

---

## 1. Extract ISO

```bash
python main.py extract "games/Final Fantasy Tactics - The War of the Lions (USA).iso" ./extracted
```

**Harus muncul:**
- `extracted/PSP_GAME/USRDIR/fftpack.bin` (~220 MB)
- `extracted/FFTPACK_Extracted/EVENT/TEST.EVT` (dialog story)

Verifikasi cepat:
```bash
ls -la extracted/FFTPACK_Extracted/EVENT/TEST.EVT
```

> Langkah reverse-engineering (font, char_table, decode, parse →
> `tools/events_parsed.json`) **sudah selesai** dan ada di repo. Tidak perlu
> diulang kecuali mau menambah karakter ke `char_table.json`.

---

## 2. Bangun workspace

```bash
python tools/build_workspace.py tools/events_parsed.json workspace/ --filter-quality
```

**Hasil:** `workspace/chapter_01.json` … `chapter_91.json` + `index.json`
(±9.027 bubble dialog). `--filter-quality` membuang bubble yang isinya mostly
bytecode (tidak terbaca).

Penting: `id` tiap blok **sinkron** dengan repacker. Jangan ubah `id`.

Lihat isi chunk:
```bash
python -c "import json;d=json.load(open('workspace/chapter_01.json'));print(d['metadata']);[print(b['id'],b['en'][:60]) for b in d['blocks'][:8]]"
```
Catatan: chunk pertama mulai di id ≈ 76, dialog "asli" mulai sekitar id 83.

---

## 3. Auto-translate dengan Gemini

Lihat dulu prompt tanpa pakai kuota (disarankan pertama kali):
```bash
python tools/translate_gemini.py workspace/chapter_01.json /tmp/preview.json --dry-run
```

Translate slice kecil dulu untuk uji (mis. 20 blok pertama yang readable):
```bash
python tools/translate_gemini.py workspace/chapter_01.json workspace/chapter_01.out.json --start 83 --end 103 --batch 10
```

Lalu seluruh chunk:
```bash
python tools/translate_gemini.py workspace/chapter_01.json workspace/chapter_01.out.json
```

**Output** `chapter_01.out.json`: tiap blok dapat `id_auto`, `flags`, `status`
(`auto` = lolos, `needs_review` = ada masalah control-code/proper-noun).
Tool ini **resumable** — jalankan ulang, blok yang sudah `auto`/`approved`
di-skip otomatis.

Prompt sudah otomatis:
- grounding lore FFT WoTL (anti-halusinasi),
- proper noun TIDAK ditranslate,
- control code dipertahankan,
- singkatan umum (`yg`, `dgn`, `utk`…) dipakai **hanya** kalau perlu muat byte.

---

## 4. Review blok ber-flag → isi `id_final`

Lihat blok yang perlu di-review:
```bash
python - <<'PY'
import json
d=json.load(open('workspace/chapter_01.out.json'))
for b in d['blocks']:
    if b['status']=='needs_review':
        print('#%d %s'%(b['id'],b['flags']))
        print('  EN:',b['en'])
        print('  ID:',b.get('id_auto'))
PY
```

Untuk tiap blok bermasalah, set field **`id_final`** dengan versi yang benar.
Aturan wajib:
- **Jumlah control code sama** dengan EN: tiap `<f8>`, `<e0>`, `<SPEAKER>`,
  `<e3>`, `<XX>` harus muncul sebanyak yang ada di EN, di posisi yang masuk akal.
- Bubble speaker harus diawali `<SPEAKER>`.
- Proper noun (Ramza, Ovelia, Order, Knight, dll) tetap English.
- `id_final` mengisi/menimpa `id_auto` saat repack (repack pakai
  `id_final or id_auto`).

> Tip: kalau Gemini sering membuang `<f8>` (line break), cek lagi posisi break
> di EN dan sisipkan `<f8>` di tempat yang sama.

---

## 5. Rakit jadi ISO modifikasi

```bash
python tools/translate_pipeline.py \
    --translations workspace/chapter_01.out.json \
    --original-iso "games/Final Fantasy Tactics - The War of the Lions (USA).iso" \
    --output-iso /tmp/FFT_ID.iso
```

Pipeline menjalankan berurutan:
1. **Validasi control-code** — kalau ada yang hilang → **ABORT** (override
   berisiko: `--ignore-control-errors`).
2. **repack_evt** — tulis ID ke byte range tiap bubble.
3. **repack_fftpack** — tanam TEST.EVT baru ke fftpack.bin (`@0x361800`).
4. **patch_iso** — tanam fftpack.bin ke ISO (`@0x02c20000`). Ukuran ISO tetap.

**Baca ringkasan stats:**
```
Applied (in-place) : N      ← berhasil masuk
Applied (stretched): N      ← masuk pakai trailing-zero buffer
Skipped (too long) : N      ← ID kepanjangan & tak ada room → tetap English
```

Default: `--allow-stretch` ON, `--allow-truncate` OFF (overflow di-skip, bukan
dipotong lossy). Untuk satu chunk pakai file `.out.json`; untuk semua chunk
arahkan ke folder: `--translations workspace/` (otomatis merge).

### Kalau ada blok "Skipped (too long)"

Artinya ID lebih panjang dari slot byte original dan tak ada buffer. Perpendek
`id_final`-nya pakai singkatan/phrasing ringkas, lalu jalankan ulang. Cek
overflow tiap blok:
```bash
python tools/repack_evt.py \
  extracted/FFTPACK_Extracted/EVENT/TEST.EVT \
  tools/events_parsed.json workspace/chapter_01.out.json tools/char_table.json \
  --output /tmp/_t.evt --report /tmp/_r.json --allow-stretch
python -c "import json;[print(d['id'],d['status'],'overflow',d.get('overflow')) for d in json.load(open('/tmp/_r.json'))['details'] if d['status']!='applied' and d['status']!='stretched']"
```

---

## 6. Test di PPSSPP

Boot `/tmp/FFT_ID.iso`. Periksa:
- game tidak crash,
- teks ID muncul benar,
- nama speaker utuh, kalimat tidak ter-split / terpotong.

(Opsional) verifikasi byte-level tanpa PPSSPP — pastikan teks landing di ISO:
```bash
python - <<'PY'
import json,sys; from pathlib import Path
sys.path.insert(0,'tools'); from decode_evt import decode, load_table
m,mb=load_table(Path('tools/char_table.json'))
iso=open('/tmp/FFT_ID.iso','rb'); base=0x02c20000+0x00361800
ev=json.load(open('tools/events_parsed.json'))['events']
idx={};bid=0
for e in ev:
    for b in e.get('bubbles',[]):
        if b.get('kind') in {'text','narration','speaker'}: idx[bid]=b;bid+=1
cid=83; bs,be=idx[cid]['raw_byte_range']; iso.seek(base+bs)
print(repr(decode(iso.read(be-bs),m,mb)))
PY
```

Uji jalur stretch (otomatis, tanpa PPSSPP):
```bash
python tools/test_stretch_path.py
```

---

## 7. Distribusi (xdelta3 patch)

```bash
python tools/translate_pipeline.py \
    --translations workspace/ \
    --original-iso "games/Final Fantasy Tactics - The War of the Lions (USA).iso" \
    --output-iso /tmp/FFT_ID_full.iso \
    --xdelta-patch /tmp/FFT_ID.xdelta
```

Distribusi cukup file `.xdelta` (kecil). Pemain apply ke ISO legal mereka:
```bash
xdelta3 -d -s "ISO_original.iso" FFT_ID.xdelta "FFT_ID.iso"
```

---

## Full game (loop produksi)

1. `build_workspace.py` sekali (sudah menghasilkan 91 chunk).
2. Untuk tiap `chapter_NN.json`: `translate_gemini.py` → review `needs_review` →
   isi `id_final`.
3. Jalankan `translate_pipeline.py --translations workspace/` untuk merge semua
   chunk jadi satu ISO.
4. Test PPSSPP per chapter saat maju.

Prioritas (lihat TODO_PLAN Fase 8.2): story dialog dulu (TEST.EVT), baru UI/
menu (.LZW), lalu battle quotes & deskripsi.

---

## Glosarium control code (JANGAN diubah)

| Token | Arti |
|-------|------|
| `<SPEAKER>` | tag nama pembicara (bubble harus diawali ini) |
| `<f8>` | line break lembut di dalam bubble |
| `<e0>` | placeholder nama pemain (Ramza default) |
| `<e3>` | penanda mulai paragraf/dialog |
| `<XX>` | byte mentah (mis. `<e2>`, `<da>`) — pertahankan apa adanya |
| `0xFE` | terminator akhir bubble (satu saja, di posisi asli) |
| `0x95` | space — filler gap (BUKAN `0x00`) |

---

## Troubleshooting

| Gejala | Sebab | Solusi |
|--------|-------|--------|
| Pipeline ABORT "control code hilang" | Gemini buang `<f8>`/`<SPEAKER>` | Perbaiki `id_final` (samakan jumlah token), jalankan ulang |
| "Skipped (too long)" banyak | ID > slot byte | Perpendek dgn singkatan/phrasing ringkas |
| Teks muncul "0000" / "OOOO" | gap dipad `0x00` | Pakai pipeline resmi (pad `0x95`) — jangan edit manual |
| Dialog ter-split / nama speaker hilang | terminator `0xFE` ganda | Patuhi bubble invariant (satu `0xFE`) — repack resmi sudah benar |
| `GEMINI_API_KEY not set` | env var kosong | `export GEMINI_API_KEY="AIza..."` |
| Nama karakter ke-translate | proper noun bocor | Tambah ke daftar di `proper_nouns.json` / prompt, review |

---

*Selalu test di PPSSPP sebelum rilis. Simpan ISO original — semua patch
dibuat relatif terhadapnya.*
