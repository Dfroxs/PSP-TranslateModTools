# MULTI_GAME_NOTES.md — Adaptasi codebase ke game PSP lain

> **Kapan baca dokumen ini**: setelah project FFT WoTL selesai dirilis (Fase 8
> TODO_PLAN tuntas + ISO terjemahan ID dipublish lewat xdelta3 patch).
>
> **Tujuan**: kasih gambaran apa yang reusable, apa yang perlu rewrite, dan
> keputusan arsitektur yang harus diputuskan SEBELUM coding game ke-2.
>
> Status saat ditulis (2026-06-20): codebase pas-pasan untuk 1 game (FFT WoTL).
> Refactor Fase 0-5 sudah selesai → arsitektur sudah cukup bersih buat dijadikan
> base multi-game, asal invariant `cli.py` dispatcher + `paths.py` central
> dipertahankan.

---

## 1. Ringkasan eksekutif

Codebase ini ~30-40% reusable lintas game PSP. Sisanya FFT-specific karena
setiap game punya:

- **Container archive** sendiri (FFT pakai `fftpack.bin`; game lain bisa
  `.WAD` / `.PMP` / `.DAT` / plain extracted)
- **Encoding karakter custom** (FFT pakai byte→glyph 62 single-byte + multi-byte;
  game lain bisa Shift-JIS, UTF-16, tile-based encoding, atau encoding custom
  beda)
- **Format dialog/event** sendiri (FFT: `TEST.EVT` 231 chunks dengan bubble
  invariant `0xFE` di `byte_end-1`)
- **Font format** sendiri (FFT: 10×14 px 2bpp MSB 35 B/glyph 2223 glyphs;
  game lain bisa 8×8 1bpp, 16×16 4bpp, dst)
- **Proper nouns / lore** sendiri

Yang jadi infrastruktur (codec abstraction, CLI dispatcher, paths
centralization, regression test pattern) **reusable as-is**.

---

## 2. Apa yang reusable as-is (no change)

| Komponen | Kenapa generik |
|---|---|
| `psp_modtool/` (semua) | ISO 9660 / UMD itu standar — extract/scan/repack jalan di ISO PSP manapun |
| `psp_translate/codec/{decode,encode}.py` | Cuma butuh `char_table.json` yang sesuai — algoritmanya game-agnostic |
| `psp_translate/pack/iso.py` | Byte-patching ISO di offset known — universal |
| `psp_translate/revtools/explore.py` | Heuristik byte stats — buat triage file biner apa pun |
| `psp_translate/translate/gemini.py` (kode) | API wrapper — prompt-nya saja yang perlu ganti |
| `psp_translate/cli.py` dispatcher pattern | Arsitektur, bukan konten — tambah subcommand cuma 1 baris di `SUBCOMMANDS` |
| `psp_translate/paths.py` centralization | Pattern, bukan path konkret — keep invariant "no hardcoded paths in submodules" |
| `tests/test_stretch_path.py` pattern | Template buat regression test apa pun (behavior-preserving roundtrip) |
| `pyproject.toml` struktur | Cuma tambah entry_point baru per game |

---

## 3. Apa yang FFT-specific (perlu adaptasi/rewrite per game)

| File / Folder | Kenapa FFT-only | Effort game baru |
|---|---|---|
| `data/char_table.json` | Mapping byte→Unicode spesifik font FFT | **Reverse engineer ulang** (lihat workflow §5) |
| `data/fftpack_event_map.json` | Offset map `fftpack.bin` (container FFT) | Game lain butuh tool decoder/mapper baru |
| `data/proper_nouns.json` | 2,650 nama dari WORLD.LZW FFT | Extract dari sumber game baru (manual / scrape wiki) |
| `psp_translate/paths.py` (3 baris game-specific) | `ORIGINAL_TEST_EVT`, `ORIGINAL_FFTPACK`, `FFTPACK_ISO_OFFSET = 0x02c20000` | Ganti per game (atau hilangkan kalau jadi plugin) |
| `psp_translate/evt/` (4 file: header/parser/repack/budget) | Asumsi struktur `TEST.EVT` 231 event chunks + bubble invariant FFT | **Rewrite total** — game lain format dialog beda |
| `psp_translate/pack/fftpack.py` | Container `fftpack.bin` FFT-specific | Rewrite untuk container game baru |
| `psp_translate/lzw/extract.py` | Format `.LZW` FFT (128-byte header + 0xFE-terminated strings) | Rewrite kalau game pakai compressor lain |
| `psp_translate/revtools/font_render.py` | Hardcoded 10×14 px, 2bpp, MSB, 35 B/glyph, 2223 glyphs | Parametrize (font 8×8 / 16×16 / bit depth beda) |
| `psp_translate/revtools/proper_nouns.py` | Parse FFT WORLD.LZW | Rewrite per game |
| `docs/gemini_prompt_template.md` | Lore Ivalice, glossary FFT, character context | **Rewrite total** dengan lore game baru |
| Subcommand names `evt-*`, `fftpack` | Literal "evt"/"fftpack" di nama | Lihat keputusan arsitektur §6 |

---

## 4. Apa yang setengah reusable (perlu generalisasi minor)

| Komponen | Kondisi sekarang | Generalisasi yang dibutuhkan |
|---|---|---|
| `psp_translate/translate/workspace.py` | Asumsi block-id sinkron dengan `evt-repack` (kind ∈ {text, narration, speaker}) | Buat block-kind set bisa di-config per game |
| `psp_translate/translate/pipeline.py` | Hardwired chain: `evt-repack → fftpack → iso` | Buat pipeline definition per game (mungkin sebagai YAML / JSON config, atau Python module per game) |
| `validate_translation()` di pipeline.py | Validasi `<SPEAKER>`/`<f8>`/`<e0>` control codes FFT-specific | Buat control-code rule set per game |
| `data/gemini_prompt_template.md` | Template strict rules + abbreviation table | Pisah jadi `base_template.md` (struktur prompt) + `<game>_grounding.md` (lore+glossary) |

---

## 5. Workflow investigasi game baru (sebelum sentuh code)

Untuk setiap game PSP baru, fase investigasi dulu (mirror Fase 0-4 di
TODO_PLAN.md, biasanya **1-3 minggu per game** tergantung "exotic"-nya format):

1. **Extract ISO** — `psp-modtool extract <iso> ./extracted` (jalan as-is)
2. **Scan plain ASCII** — `psp-modtool scan ./extracted strings.json`.
   - Kalau ketemu banyak: game pakai ASCII biasa → **cukup `psp_modtool`**, nggak
     perlu `psp_translate` sama sekali. Edit `strings.json`, `psp-modtool apply`,
     `psp-modtool repack`. Selesai.
   - Kalau ASCII kosong / sedikit: game punya encoding custom (seperti FFT) →
     lanjut langkah 3
3. **Identifikasi struktur file:**
   - `psp-translate explore <folder>` — cari file biner yang bukan ASCII tapi
     terstruktur (printable %, top-N byte distribution)
   - Cari container archive (sesuai konvensi PSP: biasanya di `PSP_GAME/USRDIR/`)
   - Cari font file (`FONT.BIN`-equivalent atau di dalam archive)
   - Cari dialog file (biasanya `.EVT` / `.SCN` / `.DAT` / `.PAK`)
4. **Reverse engineer font:**
   - Coba render dengan parameter beragam (8×8 1bpp, 10×14 2bpp, 16×16 4bpp)
   - Visual identifikasi glyph A-Z, 0-9
5. **Bangun char_table:**
   - Mapping byte → glyph dengan freq analysis (English/Japanese letter freq)
   - Cari multi-byte sequence (prefix bytes yang sering dipasangkan)
6. **Reverse engineer dialog format:**
   - Pointer table? (offset list di header file)
   - Bubble delimiter? (FFT: `0xFE` di akhir bubble)
   - Control codes? (line break, speaker tag, color, placeholder name, dst)
   - Speaker tag format? (FFT: `<e3>08`)
7. **Bangun encoder/decoder** untuk format game itu
8. **Bangun container patcher** (mirror `pack/fftpack.py` + `pack/iso.py`)
9. **Bangun regression test** (mirror `tests/test_stretch_path.py`) untuk
   verify behavior-preserving

Codebase ini **kasih kamu pola + infrastruktur**, bukan menggantikan reverse
engineering kerjaan.

---

## 6. Keputusan arsitektur SEKARANG (penting buat dipikir sebelum game ke-2)

Kalau game ke-2 = **1 game lain saja** → **fork repo per game** lebih simpel.

Kalau planning **≥3 game** → restruktur jadi plugin model akan bayar diri.

| Pendekatan | Kelebihan | Kekurangan | Cocok untuk |
|---|---|---|---|
| **A. Fork-per-game** | Simpel, isolation total, satu repo = satu game = satu mental model. Bug bisa di-fix tanpa concern game lain. | Bug fix common code harus disinkron manual antar fork. Code duplikasi. Tidak ada shared improvements. | 1-2 game terpisah |
| **B. Plugin model** | Common code 1 sumber. Tambah game baru cuma 1 folder (`games/<name>/`). Fix common code = fix semua game. | Refactor effort upfront (~3-5 hari kerja). CLI butuh game selector. Kompleksitas extra. | ≥3 game atau planning serius multi-game |
| **C. Library-only** | Maximum flexibility. Tiap game punya repo + CLI sendiri tapi import library common. | Hilangin convenience CLI shared. User end-game perlu nulis script. Distribusi PyPI butuh maintenance. | Akademik / framework distributable |

**Rekomendasi**: kalau ragu, **B (plugin)** lebih future-proof. Refactor 3-5 hari
sekali, jauh lebih murah daripada maintain N fork.

---

## 7. Bentuk plugin model (kalau pilih opsi B)

Target layout setelah refactor multi-game:

```
psp_translate/
├── codec/                       # GENERIK (decode/encode byte ↔ text via char_table)
├── pack/iso.py                  # GENERIK (ISO byte patching)
├── revtools/explore.py          # GENERIK (byte heuristic)
├── revtools/font_render.py      # GENERIK (parametrized — terima dimensi/bpp via arg)
├── translate/{gemini,workspace,pipeline}.py  # GENERIK (orchestrator + AI)
├── cli.py                       # dispatcher: `psp-translate <game> <sub> ...`
├── paths.py                     # GENERIK (DATA/BUILD/DOCS roots)
└── games/
    ├── __init__.py
    ├── _registry.py             # daftar game → plugin module
    ├── fft_wotl/                # eks evt/ + pack/fftpack.py + data/* sekarang
    │   ├── __init__.py
    │   ├── paths.py             # ORIGINAL_TEST_EVT, FFTPACK_ISO_OFFSET, dst
    │   ├── char_table.json
    │   ├── proper_nouns.json
    │   ├── container.py         # = psp_translate/pack/fftpack.py sekarang
    │   ├── dialog.py            # = psp_translate/evt/{header,parser,repack,budget}.py merged
    │   ├── lzw.py               # = psp_translate/lzw/extract.py
    │   ├── font_spec.py         # parameter font: 10×14, 2bpp, MSB, 35 B/glyph
    │   ├── prompt_grounding.md  # lore Ivalice
    │   ├── pipeline.py          # game-specific pipeline chain
    │   └── subcommands.py       # subcommand definitions: evt-header, evt-parse, ...
    └── <game_baru>/             # sama strukturnya
        ├── ...
        └── subcommands.py
```

**CLI berubah dari**: `psp-translate evt-repack ...`
**Menjadi**: `psp-translate fft_wotl evt-repack ...` atau `psp-translate kh_bbs repack ...`

`cli.py` dispatcher:
1. Parse `argv[1]` sebagai game name
2. Load plugin module dari `games/<name>/subcommands.py`
3. Dispatch ke subcommand sesuai plugin's own SUBCOMMANDS dict

Game baru = bikin folder `games/<name>/` + register di `_registry.py`. Setiap
game expose:
- `char_table.json`, `proper_nouns.json`
- `container.py` dengan API standar (extract/repack)
- `dialog.py` dengan API standar (decode/encode/repack bubble)
- `subcommands.py` dengan dict registrasi

---

## 8. Action items KALAU decide multi-game (preview)

Saat eksekusi refactor jadi plugin model, urut fase (mirror REFACTOR_PLAN pattern):

- [ ] **Fase A**: Buat `psp_translate/games/fft_wotl/` skeleton (kosong dulu)
- [ ] **Fase B**: Pindahkan code FFT-specific ke `games/fft_wotl/`:
   - `evt/*.py` → `games/fft_wotl/dialog.py`
   - `pack/fftpack.py` → `games/fft_wotl/container.py`
   - `lzw/extract.py` → `games/fft_wotl/lzw.py`
   - `data/{char_table,fftpack_event_map,proper_nouns}.json` → `games/fft_wotl/`
   - 3 path konstanta FFT-specific di `paths.py` → `games/fft_wotl/paths.py`
   - `revtools/proper_nouns.py` → `games/fft_wotl/extract_nouns.py`
   - `docs/gemini_prompt_template.md` → `games/fft_wotl/prompt_grounding.md`
- [ ] **Fase C**: Generalize `revtools/font_render.py` jadi parameterized
- [ ] **Fase D**: Generalize `translate/workspace.py` (block kinds via config)
- [ ] **Fase E**: Generalize `translate/pipeline.py` (chain via plugin definition)
- [ ] **Fase F**: Update `cli.py` jadi 2-level dispatcher: `psp-translate <game> <sub>`
- [ ] **Fase G**: Update gerbang regresi: `psp-translate fft_wotl verify` (gate
      per game)
- [ ] **Fase H**: Update docs (CLAUDE.md, README.md, TUTORIAL.md untuk multi-game)
- [ ] **Fase I**: Stub `games/<game_baru>/` dengan TODO checklist

Estimasi: 3-5 hari kalau scope tetap behavior-preserving (mirror Phase 2-5
refactor sebelumnya).

---

## 9. Yang JANGAN dilakukan sekarang (anti-pattern preview)

Saat coding sisa Fase 8 FFT WoTL, hindari:

1. **Hardcode path baru di submodule** — selalu lewat `paths.py`. Ini invariant
   Phase 2 yang menghemat banyak rewrite nanti.
2. **Tambah subcommand tanpa register di `cli.py`** — bikin shadow CLI yang
   bypass dispatcher = nanti susah dimigrasi jadi plugin.
3. **Mix data sumber + data generated di folder yang sama** — tetap pegang
   invariant Phase 1: `data/` = source, `build/` = generated.
4. **Tambah dependency baru di `pyproject.toml` tanpa pertimbangan** — sekarang
   masih pure-stdlib (kecuali Gemini SDK). Multi-game akan stress test ini.
5. **Asumsi semua game punya bubble invariant seperti FFT** — `0xFE` terminator,
   `<SPEAKER>` tag, dst itu FFT-specific. Saat dokumentasi, hati-hati kasih
   konteks "FFT-specific" supaya nggak salah copy ke game lain.

---

## 10. Rangkuman: keputusan sekarang vs nanti

**Sekarang (saat FFT WoTL belum selesai)**:
- Lanjut fokus Fase 8 (bulk translation). JANGAN mulai multi-game refactor.
- Pertahankan invariant arsitektur (`cli.py`, `paths.py`, `data/` vs `build/`,
  zero-`sys.path.insert`).
- Tambah code FFT-baru di lokasi sekarang (`psp_translate/evt/` dst.) — TIDAK
  perlu nyiapin "buat plugin" sekarang.

**Nanti (setelah FFT WoTL rilis)**:
- Putuskan: fork-per-game atau plugin model (lihat §6)
- Kalau plugin: jalankan Fase A-I (§8). Mulai dari Fase A skeleton dulu, test
  behavior preservation FFT WoTL setiap fase (mirror REFACTOR_PLAN pattern).
- Game ke-2 mulai fase reverse engineering (§5).

---

*Created: 2026-06-20 (after refactor Phase 0-5 done, before bulk translation
Fase 8). Re-read setelah FFT WoTL rilis.*
