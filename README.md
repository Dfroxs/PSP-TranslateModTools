# PSP Mod Tool

Tool Python untuk **extract, scan, terjemahkan, dan repack** file ISO game PSP.
Berguna untuk lokalisasi bahasa game (misalnya English → Indonesia).

Proyek ini punya **dua lapis**:

1. **`psp_modtool/`** — CLI generik (pure stdlib, Python ≥ 3.8) untuk extract,
   scan, translate, dan repack ISO 9660 / UMD. Cocok untuk game yang dialog-nya
   tersimpan sebagai ASCII biasa.
2. **`psp_translate/`** — tool reverse-engineering & translasi khusus untuk
   **Final Fantasy Tactics: The War of the Lions (PSP)**. Scanner generik TIDAK
   bisa menemukan dialog FFT WoTL karena teksnya pakai *custom byte encoding* +
   font 2bpp custom + multi-byte sequences, jadi dibuat stack terpisah. Satu
   CLI: `psp-translate <subcommand>` (atau `python -m psp_translate <sub>`
   tanpa install).

> **Fokus aktif**: translasi EN → ID untuk FFT WoTL. **Mulai dari
> [`docs/TUTORIAL.md`](docs/TUTORIAL.md)** (panduan langkah-demi-langkah dari ISO original
> sampai ISO terjemahan jadi). Lihat juga `docs/TASK/TODO_PLAN.md` (roadmap berfase) dan
> `CLAUDE.md` (catatan arsitektur & temuan reverse engineering). Riset komunitas
> + temuan internal ada di `docs/DocumentOfComunity.md`.

---

## Struktur proyek

```
PspModTools/
├── psp_modtool/        # Bagian 1 — CLI generik ISO 9660 / UMD (pure stdlib)
├── psp_translate/      # Bagian 2 — FFT WoTL toolkit (20 subcommand `psp-translate`)
├── data/               # Source-of-truth versioned: char_table.json,
│                       #   fftpack_event_map.json, proper_nouns.json
├── build/              # Generated, gitignored: events_parsed.json,
│                       #   *.lzw extracts, font renders, decoded dumps
├── docs/               # TUTORIAL · DocumentOfComunity · gemini_prompt_template
│   ├── formats/        # EVT_FORMAT.md · LZW_FORMAT.md
│   └── TASK/           # TODO_PLAN.md · REFACTOR_PLAN.md
├── tests/              # Regression: test_stretch_path.py (`psp-translate verify`)
├── main.py             # Entry untuk psp_modtool generic CLI
└── pyproject.toml      # `pip install -e .` → memasang `psp-modtool` + `psp-translate`
```

---

## Bagian 1 — CLI generik (`psp_modtool`)

### Struktur

```
PspModTools/
├── main.py                  # Entry point
├── pyproject.toml           # Konfigurasi package
└── psp_modtool/             # Package utama
    ├── cli.py               # Antarmuka command-line
    ├── core/                # Logika inti
    │   ├── iso9660.py       # Parser/writer format ISO 9660
    │   ├── extractor.py     # Bongkar ISO → folder
    │   ├── scanner.py       # Deteksi teks dalam file
    │   ├── translator.py    # Terapkan terjemahan
    │   ├── repacker.py      # Folder → ISO
    │   ├── pipeline.py      # Alur lengkap interaktif
    │   └── inspector.py     # Heuristik kelayakan ISO (sebelum extract penuh)
    └── utils/               # Pendukung (constants, logger, text_detect)
```

### Cara pakai (per langkah)

```bash
# 1. Extract ISO ke folder
python main.py extract game.iso ./extracted

# 2. Scan teks → hasilkan strings.json
python main.py scan ./extracted strings.json

# 3. Edit strings.json (isi field "translation") di text editor

# 4. Terapkan terjemahan ke file game
python main.py apply ./extracted strings.json

# 5. Repack jadi ISO baru
python main.py repack ./extracted game_modded.iso
```

### Mode otomatis (interaktif)

```bash
python main.py all game.iso ./workdir
```

Menjalankan semua langkah dan berhenti di tengah agar kamu bisa mengisi
terjemahan, lalu lanjut otomatis.

### Sebagai package terpasang

```bash
pip install -e .
# Memasang DUA console script sekaligus (dari pyproject.toml):
psp-modtool   extract game.iso ./extracted       # Bagian 1 — generic ISO
psp-translate verify                              # Bagian 2 — FFT WoTL toolkit
```

### Format strings.json

```json
{
  "files": [
    {
      "path": "DATA/MENU.BIN",
      "type": "binary",
      "strings": [
        { "offset": 1024, "original": "Start Game", "translation": "Mulai Permainan" }
      ]
    }
  ]
}
```

Isi field `translation`. Kosongkan untuk string yang tidak ingin diubah.

---

## Bagian 2 — FFT WoTL translation pipeline (`psp_translate/`)

### Status

- **Pipeline teks END-TO-END terverifikasi in-game** (PPSSPP): decode → encode →
  repack EVT → patch fftpack → patch ISO + validasi control-code semuanya jalan.
  Scene pembuka Orbonne (doa + dialog event 1) tampil benar (commit `5524b89`
  memperbaiki *bubble invariant* repacker).
- **Jalur `--allow-stretch` terverifikasi** secara otomatis lewat
  `tests/test_stretch_path.py` (ukuran file tetap, hanya region target berubah,
  tepat satu terminator `0xFE`, bubble tetangga byte-identik).
- **Auto-translation Gemini** sudah grounded dengan konteks lore FFT WoTL
  (anti-halusinasi) + aturan singkatan umum ID untuk menghemat byte.

### Alur translasi (end-to-end)

> Panduan lengkap + troubleshooting: lihat **[`docs/TUTORIAL.md`](docs/TUTORIAL.md)**.

```bash
# 1. Bangun workspace (chunk dialog, block-id sinkron dengan repack)
python -m psp_translate workspace build/events_parsed.json workspace/ --filter-quality

# 2. Auto-translate satu chunk dengan Gemini (butuh GEMINI_API_KEY)
python -m psp_translate gemini workspace/chapter_01.json workspace/chapter_01.out.json [--start N --end M]

# 3. Auto-apply precedent proper-noun + approve block yang tinggal precedent
python -m psp_translate review-apply workspace/chapter_01.out.json

# 4. (opsional) recover dialog yang ter-skip + cross-check vs wiki script
python -m psp_translate script-check workspace/chapter_01.out.json

# 5. Review sisa block ber-flag (byte overflow + proper-noun BARU), isi id_final,
#    lalu rakit jadi ISO modifikasi
python -m psp_translate pipeline \
    --translations workspace/chapter_01.out.json \
    --original-iso "games/FFT WoTL.iso" \
    --output-iso /tmp/FFT_ID.iso
```

> Langkah 3-5 (review) bisa juga lewat **web UI**: `python -m psp_translate webui`
> lalu buka `http://127.0.0.1:8000`. Lihat [bagian Review web UI](#review-web-ui-psp-translate-webui).

`psp-translate pipeline` menjalankan: validasi control-code (FATAL kalau ada
`<SPEAKER>`/`<f8>`/dll hilang) → repack EVT → patch fftpack.bin → patch ISO
(ukuran preserved, tanpa rebuild penuh). Default `--allow-stretch` aktif,
`--allow-truncate` mati (overflow → di-skip, bukan lossy).

### GEMINI_API_KEY

Translator membaca env var `GEMINI_API_KEY`:

```bash
export GEMINI_API_KEY="AIza..."     # sesi sementara
# atau simpan permanen di ~/.zshrc (jangan commit ke git)
```

Gunakan `--dry-run` untuk melihat prompt tanpa memakai kuota API.

### Review web UI (`psp-translate webui`)

Workbench browser lokal untuk menerjemahkan / preview / edit / review chapter —
**stdlib `http.server` saja** (tanpa pip/npm). Butuh `GEMINI_API_KEY` untuk
fitur translate + chat.

```bash
python -m psp_translate webui [--host 127.0.0.1] [--port 8000]
# lalu buka http://127.0.0.1:8000
```

Single-page app (`psp_translate/webui/static/index.html`) + backend
`psp_translate/webui/server.py`. Membungkus subcommand yang ada sebagai job
subprocess dengan live-log via SSE:

- **Full Translate** → `gemini`
- **Script Check** → `script-check`

Per-block editor menampilkan pratinjau dialog ala FFT, byte budget real
(`codec.encode`), dan menulis `id_final`/`status` balik ke
`chapter_NN.out.json`. Tab filter memetakan status → bucket: `approved`→Done;
`auto`/`needs_review`/`pending`→Review; `error`→Error; `skip`→Skip. Chat Gemini
in-app (reuse `google.genai`).

### Sebagai package terpasang

`pip install -e .` (dari Bagian 1) sudah memasang **dua** console script.
Setelah install, `python -m psp_translate <sub>` boleh disingkat jadi
`psp-translate <sub>`:

```bash
psp-translate                                 # daftar 20 subcommand
psp-translate verify                          # regression gate (stretch + roundtrip)
psp-translate decode <evt> data/char_table.json --search "Father"
psp-translate pipeline \
    --translations workspace/chapter_01.out.json \
    --original-iso "games/FFT WoTL.iso" \
    --output-iso /tmp/FFT_ID.iso
```

### Reverse engineering tools

```bash
# Heuristic byte stats untuk file biner apa pun
python -m psp_translate explore <folder-or-file> [--min-len N]

# Render FONT.BIN ke PGM (10x14 px @ 2bpp)
python -m psp_translate font-render <FONT.BIN> <out.pgm> [--scale 4]

# Kelola tabel karakter (byte → Unicode)
python -m psp_translate char-table {init|dump|set|stats} ...

# Decode TEST.EVT ke English
python -m psp_translate decode <file.evt> data/char_table.json [--search "Father" | --full]

# Encode text → bytes (lossless, roundtrip terverifikasi)
python -m psp_translate encode <input.txt> data/char_table.json [--output out.bin]

# Hitung byte budget per bubble (referensi constraint translator)
python -m psp_translate budget <TEST.EVT> build/events_parsed.json data/char_table.json --output build/translation_budget.json

# Verifikasi jalur stretch repacker (otomatis, tanpa PPSSPP)
python -m psp_translate verify
```

---

## Catatan & Keterbatasan

- **Constraint panjang**: untuk substitusi in-place, teks ID harus ≤ panjang
  byte original. Hanya ~2,3% bubble FFT WoTL punya *adjacent zero buffer* untuk
  di-*stretch*; sisanya wajib muat in-place (atau di-skip). Strategi: phrasing
  ID ringkas + singkatan umum (`yang`→`yg`, `dengan`→`dgn`, dst) — sudah
  di-encode di prompt Gemini. Pointer rewriter (true expansion) masih ditunda.
- **Bubble invariant (FFT WoTL)**: tiap bubble dibatasi SATU `0xFE` di
  `byte_end-1`. Gap diisi space `0x95` (bukan `0x00` — itu glyph '0', bug "OOOO").
  Lihat `CLAUDE.md`.
- **Control codes wajib preserved**: setiap token `<...>` (`<SPEAKER>`, `<f8>`,
  `<e0>`, dll) harus muncul dengan jumlah sama di terjemahan, atau pipeline abort.
- **Proper nouns tidak ditranslate**: nama karakter/tempat/item/spell/job/
  organisasi + honorifik (Lord, Lady, Ser, dll) tetap English.
- **File biner generik**: terjemahan tidak boleh lebih panjang dari teks asli
  (otomatis dipotong/di-pad); `.bak` dibuat otomatis.
- **Encoding Jepang (Shift-JIS)** tidak di-handle pipeline generik.
- Selalu **test di PPSSPP** setelah repack.

## Lisensi

MIT
