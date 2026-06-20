# PSP Mod Tool

Tool Python untuk **extract, scan, terjemahkan, dan repack** file ISO game PSP.
Berguna untuk lokalisasi bahasa game (misalnya English → Indonesia).

Proyek ini punya **dua lapis**:

1. **`psp_modtool/`** — CLI generik (pure stdlib, Python ≥ 3.8) untuk extract,
   scan, translate, dan repack ISO 9660 / UMD. Cocok untuk game yang dialog-nya
   tersimpan sebagai ASCII biasa.
2. **`tools/`** — tool reverse-engineering & translasi khusus untuk
   **Final Fantasy Tactics: The War of the Lions (PSP)**. Scanner generik TIDAK
   bisa menemukan dialog FFT WoTL karena teksnya pakai *custom byte encoding* +
   font 2bpp custom + multi-byte sequences, jadi dibuat stack terpisah.

> **Fokus aktif**: translasi EN → ID untuk FFT WoTL. **Mulai dari
> [`docs/TUTORIAL.md`](docs/TUTORIAL.md)** (panduan langkah-demi-langkah dari ISO original
> sampai ISO terjemahan jadi). Lihat juga `docs/TASK/TODO_PLAN.md` (roadmap berfase) dan
> `CLAUDE.md` (catatan arsitektur & temuan reverse engineering). Riset komunitas
> + temuan internal ada di `docs/DocumentOfComunity.md`.

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
    │   └── pipeline.py      # Alur lengkap interaktif
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
psp-modtool extract game.iso ./extracted
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

## Bagian 2 — FFT WoTL translation pipeline (`tools/`)

### Status

- **Pipeline teks END-TO-END terverifikasi in-game** (PPSSPP): decode → encode →
  repack EVT → patch fftpack → patch ISO + validasi control-code semuanya jalan.
  Scene pembuka Orbonne (doa + dialog event 1) tampil benar (commit `5524b89`
  memperbaiki *bubble invariant* repacker).
- **Jalur `--allow-stretch` terverifikasi** secara otomatis lewat
  `tools/test_stretch_path.py` (ukuran file tetap, hanya region target berubah,
  tepat satu terminator `0xFE`, bubble tetangga byte-identik).
- **Auto-translation Gemini** sudah grounded dengan konteks lore FFT WoTL
  (anti-halusinasi) + aturan singkatan umum ID untuk menghemat byte.

### Alur translasi (end-to-end)

> Panduan lengkap + troubleshooting: lihat **[`docs/TUTORIAL.md`](docs/TUTORIAL.md)**.

```bash
# 1. Bangun workspace (chunk dialog, block-id sinkron dengan repack)
python tools/build_workspace.py tools/events_parsed.json workspace/ --filter-quality

# 2. Auto-translate satu chunk dengan Gemini (butuh GEMINI_API_KEY)
python tools/translate_gemini.py workspace/chapter_01.json workspace/chapter_01.out.json [--start N --end M]

# 3. (review id_final untuk block ber-flag) lalu rakit jadi ISO modifikasi
python tools/translate_pipeline.py \
    --translations workspace/chapter_01.out.json \
    --original-iso "games/FFT WoTL.iso" \
    --output-iso /tmp/FFT_ID.iso
```

`translate_pipeline.py` menjalankan: validasi control-code (FATAL kalau ada
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

### Reverse engineering tools

```bash
# Heuristic byte stats untuk file biner apa pun
python tools/explore.py <folder-or-file> [--min-len N]

# Render FONT.BIN ke PGM (10x14 px @ 2bpp)
python tools/font_render.py <FONT.BIN> <out.pgm> [--scale 4]

# Kelola tabel karakter (byte → Unicode)
python tools/char_table.py {init|dump|set|stats} ...

# Decode TEST.EVT ke English
python tools/decode_evt.py <file.evt> tools/char_table.json [--search "Father" | --full]

# Encode text → bytes (lossless, roundtrip terverifikasi)
python tools/encode_evt.py <input.txt> tools/char_table.json [--output out.bin]

# Hitung byte budget per bubble (referensi constraint translator)
python tools/translation_budget.py <TEST.EVT> tools/events_parsed.json tools/char_table.json --output tools/translation_budget.json

# Verifikasi jalur stretch repacker (otomatis, tanpa PPSSPP)
python tools/test_stretch_path.py
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
