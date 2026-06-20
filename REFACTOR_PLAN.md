# REFACTOR_PLAN.md — Penataan Ulang Struktur Proyek (MATANG / siap eksekusi)

> **Plan terpisah** dari `TODO_PLAN.md`. TODO_PLAN = roadmap fitur/translasi.
> Dokumen ini KHUSUS membenahi **struktur folder & kode**, tanpa mengubah
> perilaku pipeline yang sudah terverifikasi (commit `5524b89` + jalur stretch).
>
> **Status**: keputusan arah sudah final (lihat §2). Belum dieksekusi —
> dijalankan di sesi terpisah, fase-demi-fase, tiap fase lulus gerbang regresi.
>
> **Prinsip inviolable**: refactor ini *behavior-preserving*. Output byte ISO
> dan hasil decode/encode HARUS identik sebelum & sesudah tiap fase.

---

## 1. Masalah saat ini (hasil inventarisasi)

| # | Masalah | Bukti |
|---|---------|-------|
| M1 | `tools/` folder datar ~50 file campur aduk | 18 `.py` + 3 `.md` + data `.json` + 7 `lzw_*.json` + ~16 JSON artefak test + 2 `.txt` besar + `font_renders/` |
| M2 | Import antar-tool pakai `sys.path.insert(0, ...)` | `repack_evt`, `translation_budget`, `test_stretch_path` meng-import `encode_evt`/`decode_evt` lewat hack path |
| M3 | Artefak besar/generated ikut di-commit | `translation_budget.json` (8.4M), `lzw_*.json` (7), `events_parsed_evt1.json`, `evt_structure.json` |
| M4 | Data sumber vs generated tidak dipisah | `char_table.json` (sumber) sebaris dengan `translation_budget.json` (generated) |
| M5 | `__pycache__/*.pyc` ter-track | `tools/__pycache__/font_render.cpython-314.pyc` masuk `git ls-files` |
| M6 | Docs tersebar di root & `tools/` | `EVT_FORMAT.md`, `LZW_FORMAT.md`, `gemini_prompt_template.md` di `tools/`; sisanya di root |
| M7 | Path di-hardcode | `translate_pipeline.py` pakai `ROOT/'tools'/...` untuk EVT, char_table, dll |
| M8 | Tidak ada folder `tests/` & entrypoint tunggal | tiap tool dijalankan `python tools/<x>.py ...` |

---

## 2. Keputusan (FINAL — dikunci oleh user 2026-06-20)

| # | Topik | Keputusan |
|---|-------|-----------|
| 1 | Nama package | Brand proyek **PSPTRANSLATIONMOD**. Folder package Python = **`psp_translate/`** (lowercase, supaya valid & importable: `from psp_translate.codec import encode`). Nama distribusi di `pyproject.toml` boleh `psp_translate`. |
| 2 | Docs | `CLAUDE.md` **tetap di root** (konvensi Claude Code). Semua **dokumen PLAN** (`TODO_PLAN.md`, `REFACTOR_PLAN.md`) pindah ke **`docs/TASK/`**. Docs lain (`TUTORIAL.md`, `DocumentOfComunity.md`, format spec, prompt template) ke `docs/`. |
| 3 | `events_parsed.json` (9.3M) | Diperlakukan **generated** → pindah `build/`, gitignored (regenerable via `evt_parser`). |
| 4 | File legacy & artefak dev | **Hapus** `translation_workspace.py` (digantikan `build_workspace.py`) + semua JSON artefak dev (`*_trans.json`, `*_test.json`, `identity_*.json`, `single_test.json`, dll). |
| 5 | Lingkup sesi ini | **Matangkan plan saja**. Eksekusi 0–5 di sesi terpisah. |

> Catatan casing (keputusan #1): Python meng-import modul lewat nama folder.
> `PSPTRANSLATIONMOD` (huruf besar) sah secara teknis tapi melanggar PEP 8 dan
> rawan bikin bingung di sistem file case-insensitive (macOS). Karena itu folder
> importable dibuat `psp_translate/`. Kalau user tetap mau folder huruf
> besar persis, ganti semua `psp_translate` → `PSPTRANSLATIONMOD` di §3–§5.

---

## 3. Prinsip target

1. **Pisahkan 4 kelas file**: `code` (source) · `data` (sumber, kecil, versioned)
   · `build/` (generated, gitignored) · `docs/`.
2. **`tools/` jadi package nyata** (`psp_translate/`) dengan import antar-modul
   yang benar (`from psp_translate.codec import encode`), buang `sys.path.insert`.
3. **Satu CLI** (`psp_translate <subcommand>`) menggantikan belasan script lepas;
   script lama tetap bisa dipanggil via thin wrapper selama transisi.
4. **Nol artefak generated di git**; semua regenerable lewat perintah.
5. **Behavior-preserving**: tidak ada perubahan logika di fase mana pun.

---

## 4. Struktur target

```
PspModTools/
├── README.md                      # tetap di root
├── CLAUDE.md                      # tetap di root (konvensi Claude Code)
├── pyproject.toml                 # tambah entry_points: psp-modtool, psp_translate
├── main.py                        # entry CLI generik (tetap)
│
├── docs/
│   ├── TUTORIAL.md
│   ├── DocumentOfComunity.md
│   ├── gemini_prompt_template.md
│   ├── formats/
│   │   ├── EVT_FORMAT.md
│   │   └── LZW_FORMAT.md
│   └── TASK/                      # ← semua dokumen PLAN
│       ├── TODO_PLAN.md
│       └── REFACTOR_PLAN.md
│
├── psp_modtool/                   # CLI generik — SUDAH rapi, minim sentuh
│   ├── cli.py
│   ├── core/ (extractor, scanner, translator, repacker, iso9660,
│   │          pipeline, inspector)   # NOTE: inspector.py belum terdokumentasi
│   └── utils/ (constants, logger, text_detect)
│
├── psp_translate/             # eks-`tools/*.py` jadi package (PSPTRANSLATIONMOD)
│   ├── __init__.py
│   ├── cli.py                     # entrypoint: psp_translate <cmd>
│   ├── paths.py                   # SATU sumber path (ganti hardcode M7)
│   ├── codec/
│   │   ├── __init__.py
│   │   ├── char_table.py          # ← char_table.py
│   │   ├── decode.py              # ← decode_evt.py
│   │   └── encode.py              # ← encode_evt.py
│   ├── evt/
│   │   ├── __init__.py
│   │   ├── header.py              # ← evt_header.py
│   │   ├── parser.py              # ← evt_parser.py
│   │   ├── repack.py              # ← repack_evt.py
│   │   └── budget.py              # ← translation_budget.py
│   ├── pack/
│   │   ├── __init__.py
│   │   ├── fftpack.py             # ← repack_fftpack.py
│   │   └── iso.py                 # ← patch_iso.py
│   ├── translate/
│   │   ├── __init__.py
│   │   ├── workspace.py           # ← build_workspace.py
│   │   ├── gemini.py              # ← translate_gemini.py
│   │   └── pipeline.py            # ← translate_pipeline.py
│   ├── lzw/
│   │   ├── __init__.py
│   │   └── extract.py             # ← lzw_extract.py
│   └── revtools/
│       ├── __init__.py
│       ├── explore.py             # ← explore.py
│       ├── font_render.py         # ← font_render.py
│       └── proper_nouns.py        # ← extract_proper_nouns.py
│
├── data/                          # SUMBER kebenaran (kecil, di-commit)
│   ├── char_table.json
│   ├── fftpack_event_map.json
│   └── proper_nouns.json
│
├── tests/
│   ├── __init__.py
│   └── test_stretch_path.py       # ← tools/test_stretch_path.py
│
├── build/                         # GENERATED (gitignored) — regenerable
│   ├── events_parsed.json
│   ├── evt_structure.json
│   ├── events_parsed_evt1.json
│   ├── translation_budget.json
│   ├── lzw_*.json
│   ├── TEST_EVT_decoded.txt
│   ├── TEST_EVT_dialog_only.txt
│   └── font_renders/
│
├── workspace/   (gitignored)
├── games/       (gitignored)
└── extracted/   (gitignored)
```

---

## 5. Pemetaan migrasi (lengkap)

### Kode (`tools/*.py` → `psp_translate/`)
| Dari | Ke |
|------|----|
| `tools/char_table.py` | `psp_translate/codec/char_table.py` |
| `tools/decode_evt.py` | `psp_translate/codec/decode.py` |
| `tools/encode_evt.py` | `psp_translate/codec/encode.py` |
| `tools/evt_header.py` | `psp_translate/evt/header.py` |
| `tools/evt_parser.py` | `psp_translate/evt/parser.py` |
| `tools/repack_evt.py` | `psp_translate/evt/repack.py` |
| `tools/translation_budget.py` | `psp_translate/evt/budget.py` |
| `tools/repack_fftpack.py` | `psp_translate/pack/fftpack.py` |
| `tools/patch_iso.py` | `psp_translate/pack/iso.py` |
| `tools/build_workspace.py` | `psp_translate/translate/workspace.py` |
| `tools/translate_gemini.py` | `psp_translate/translate/gemini.py` |
| `tools/translate_pipeline.py` | `psp_translate/translate/pipeline.py` |
| `tools/lzw_extract.py` | `psp_translate/lzw/extract.py` |
| `tools/explore.py` | `psp_translate/revtools/explore.py` |
| `tools/font_render.py` | `psp_translate/revtools/font_render.py` |
| `tools/extract_proper_nouns.py` | `psp_translate/revtools/proper_nouns.py` |
| `tools/test_stretch_path.py` | `tests/test_stretch_path.py` |

### Data sumber (`tools/*.json` → `data/`)
`char_table.json`, `fftpack_event_map.json`, `proper_nouns.json`

### Generated (`tools/...` → `build/`, gitignored)
`events_parsed.json`, `events_parsed_evt1.json`, `evt_structure.json`,
`translation_budget.json`, `lzw_*.json` (7), `TEST_EVT_decoded.txt`,
`TEST_EVT_dialog_only.txt`, `font_renders/`

### Docs
| Dari | Ke |
|------|----|
| `tools/gemini_prompt_template.md` | `docs/gemini_prompt_template.md` |
| `tools/EVT_FORMAT.md` | `docs/formats/EVT_FORMAT.md` |
| `tools/LZW_FORMAT.md` | `docs/formats/LZW_FORMAT.md` |
| `DocumentOfComunity.md` | `docs/DocumentOfComunity.md` |
| `TUTORIAL.md` | `docs/TUTORIAL.md` |
| `TODO_PLAN.md` | `docs/TASK/TODO_PLAN.md` |
| `REFACTOR_PLAN.md` | `docs/TASK/REFACTOR_PLAN.md` |

### Hapus (keputusan #4)
`tools/translation_workspace.py`, `tools/e2e_trans.json`,
`tools/empty_trans.json`, `tools/identity_full.json`, `tools/identity_trans.json`,
`tools/multi_trans.json`, `tools/prayer_trans.json`, `tools/progress_test.json`,
`tools/retest_dialog.json`, `tools/retest_prayer.json`,
`tools/sample_translation.json`, `tools/single_test.json`,
`tools/stretch_test.json`, `tools/test_translation.json`,
`tools/__pycache__/` (semua `.pyc` ter-track)

---

## 6. `paths.py` terpusat (mengganti hardcode M7)

Buat `psp_translate/paths.py` sebagai satu sumber kebenaran path. Sketsa:

```python
from pathlib import Path
ROOT       = Path(__file__).resolve().parent.parent
DATA       = ROOT / "data"
BUILD      = ROOT / "build"
DOCS       = ROOT / "docs"
EXTRACTED  = ROOT / "extracted"
GAMES      = ROOT / "games"
WORKSPACE  = ROOT / "workspace"

# data sumber
CHAR_TABLE      = DATA / "char_table.json"
FFTPACK_MAP     = DATA / "fftpack_event_map.json"
PROPER_NOUNS    = DATA / "proper_nouns.json"
# generated
EVENTS_PARSED   = BUILD / "events_parsed.json"
TRANS_BUDGET    = BUILD / "translation_budget.json"
# input game
ORIGINAL_TEST_EVT = EXTRACTED / "FFTPACK_Extracted" / "EVENT" / "TEST.EVT"
ORIGINAL_FFTPACK  = EXTRACTED / "PSP_GAME" / "USRDIR" / "fftpack.bin"
PROMPT_TEMPLATE   = DOCS / "gemini_prompt_template.md"
FFTPACK_ISO_OFFSET = 0x02c20000
```

Semua modul `import` dari sini, tidak ada literal path/`sys.path.insert` lagi.

---

## 7. Fase eksekusi (urut; tiap fase = 1 commit; lulus gerbang regresi)

**Gerbang regresi (jalankan setelah SETIAP fase):**
```bash
# 1. stretch path (sesuaikan path script per fase)
python tests/test_stretch_path.py        # Fase ≥2
# 2. identity roundtrip: repack TEST.EVT dgn teksnya sendiri → byte-identik
#    (encode→repack→bandingkan == original)
```
Jika salah satu gagal → **stop**, perbaiki, jangan lanjut fase berikut.

### Fase 0 — Kebersihan cepat (risiko nol)
```bash
git rm -r --cached tools/__pycache__ psp_modtool/__pycache__ 2>/dev/null || true
git rm tools/e2e_trans.json tools/empty_trans.json tools/identity_full.json \
       tools/identity_trans.json tools/multi_trans.json tools/prayer_trans.json \
       tools/progress_test.json tools/retest_dialog.json tools/retest_prayer.json \
       tools/sample_translation.json tools/single_test.json tools/stretch_test.json \
       tools/test_translation.json 2>/dev/null || true
git rm tools/translation_workspace.py
# .gitignore: tambah  build/  dan  *.pyc sudah ada
```
Commit: `chore: remove tracked pycache + dev artifacts + legacy workspace tool`.

### Fase 1 — Pisahkan data & generated (belum sentuh logika)
```bash
mkdir -p data build
git mv tools/char_table.json tools/fftpack_event_map.json tools/proper_nouns.json data/
# generated → build (lalu gitignore build/)
mkdir -p build/font_renders
git mv tools/events_parsed_evt1.json tools/evt_structure.json build/ 2>/dev/null || true
mv tools/events_parsed.json tools/translation_budget.json build/ 2>/dev/null || true
mv tools/lzw_*.json tools/TEST_EVT_decoded.txt tools/TEST_EVT_dialog_only.txt build/ 2>/dev/null || true
git mv tools/font_renders/* build/font_renders/ 2>/dev/null || true
```
Update sementara path lama di script agar menunjuk `data/` & `build/`.
Gerbang regresi. Commit: `refactor: split data/ (source) and build/ (generated)`.

### Fase 2 — Bentuk package `psp_translate/` (tanpa ubah logika)
- `mkdir` struktur + `__init__.py` tiap subfolder.
- `git mv` tiap `.py` sesuai §5 (pertahankan history).
- Ganti **semua** `sys.path.insert(...)` + `from encode_evt import ...` /
  `from decode_evt import ...` jadi import package:
  `from psp_translate.codec.encode import encode_string, load_table`.
- Buat `psp_translate/paths.py` (§6); ganti semua path hardcode.
- Tambah **thin wrapper** sementara di `tools/<lama>.py`:
  ```python
  from psp_translate.evt.repack import main  # contoh
  raise SystemExit(main())
  ```
  agar perintah & TUTORIAL lama tetap jalan selama transisi.
- Pindah `test_stretch_path.py` → `tests/`, update import.
Gerbang regresi. Commit: `refactor: move tools into psp_translate package`.

### Fase 3 — CLI tunggal + entry points
- `psp_translate/cli.py`: subcommand `parse`, `budget`, `workspace`,
  `translate`, `repack`, `pipeline`, `verify`, `lzw`, `font`.
- `pyproject.toml`: `[project.scripts]` → `psp_translate = "psp_translate.cli:main"`
  (pertahankan `psp-modtool`).
Gerbang regresi (`psp_translate verify`). Commit: `feat: unified psp_translate CLI`.

### Fase 4 — Pindah docs & rapikan referensi
```bash
mkdir -p docs/formats docs/TASK
git mv TUTORIAL.md DocumentOfComunity.md docs/
git mv tools/gemini_prompt_template.md docs/
git mv tools/EVT_FORMAT.md tools/LZW_FORMAT.md docs/formats/
git mv TODO_PLAN.md REFACTOR_PLAN.md docs/TASK/
```
- Update `PROMPT_TEMPLATE` di `paths.py` → `docs/gemini_prompt_template.md`.
- Update link di `README.md`, `CLAUDE.md`, `docs/TUTORIAL.md`.
- Periksa `.gitignore`: aturan `/DocumentOfComunity.md` & ignore `TODO_PLAN.md`
  perlu disesuaikan ke path baru (`docs/...`) — **putuskan**: tetap private
  (tambah pattern baru) atau mulai di-track. (Sub-keputusan, lihat §9.)
Gerbang regresi (prompt parse + `--dry-run`). Commit: `docs: reorganize into docs/ and docs/TASK/`.

### Fase 5 — Bersih-bersih final
- Hapus thin wrapper `tools/` setelah TUTORIAL/README dimigrasi penuh ke CLI baru.
- Hapus folder `tools/` kalau sudah kosong.
- Tambah runner test sederhana (`python -m tests` atau `pytest`).
- Update `CLAUDE.md` & `README.md` ke struktur final.
Gerbang regresi. Commit: `refactor: drop legacy tools/ wrappers; finalize structure`.

---

## 8. Risiko & mitigasi

| Risiko | Dampak | Mitigasi |
|--------|--------|----------|
| Pipeline rusak karena path berubah | Tinggi | `paths.py` terpusat; gerbang regresi tiap fase; commit per fase; `git mv` (revert mudah) |
| Perintah di TUTORIAL/README jadi salah | Sedang | Thin wrapper di Fase 2; update docs di Fase 4; hapus wrapper di Fase 5 |
| Import melingkar saat pisah modul | Rendah | Layer satu arah: `codec` ⟵ `evt` ⟵ `pack`/`translate`; `paths` paling bawah |
| `data/`-vs-`build/` salah klasifikasi | Sedang | Aturan: di-commit hanya kalau TIDAK regenerable (char_table, map, proper_nouns) |
| macOS case-insensitive (folder huruf besar) | Rendah | Pakai `psp_translate` lowercase (keputusan #1) |

---

## 9. Sub-keputusan tersisa (kecil, bisa diputuskan saat eksekusi)

1. **Privasi docs**: ~~`TODO_PLAN.md` & `DocumentOfComunity.md` saat ini gitignored.~~
   **RESOLVED (user 2026-06-20): keduanya DI-TRACK** setelah pindah ke `docs/`.
   Saat Fase 4: hapus entri `/DocumentOfComunity.md` dari `.gitignore` dan
   pastikan `TODO_PLAN.md`/`docs/TASK/` TIDAK di-ignore, lalu `git add` keduanya.
2. **`pytest`** dijadikan dependency dev, atau cukup runner stdlib?
3. **Nama subcommand CLI** final (§ Fase 3) — boleh disesuaikan saat coding.

---

## 10. Checklist eksekusi (untuk sesi mendatang)

- [ ] Fase 0: untrack pycache + hapus artefak dev + hapus `translation_workspace.py`
- [ ] Fase 1: `data/` + `build/` + `.gitignore build/` + path sementara → regresi
- [ ] Fase 2: package `psp_translate/` + buang sys.path + `paths.py` + wrapper → regresi
- [ ] Fase 3: CLI tunggal + entry_points → regresi
- [ ] Fase 4: pindah docs + `docs/TASK/` + update semua link → regresi
- [ ] Fase 5: hapus wrapper + finalize docs → regresi
- [ ] Update `CLAUDE.md` & `README.md` ke struktur final

---

*PLAN MATANG — siap dieksekusi di sesi terpisah. Jangan gabung dua fase dalam
satu commit. Jangan lanjut kalau gerbang regresi gagal.*
