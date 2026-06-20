# TODO_PLAN.md — Roadmap Translasi FFT WoTL PSP

Rencana langkah-demi-langkah untuk menyelesaikan pipeline translasi EN→ID
*Final Fantasy Tactics: The War of the Lions* (PSP).

**Status saat ini** (2026-06-20): Pipeline text END-TO-END TERVERIFIKASI IN-GAME.
Decode, encode, repack EVT, patch fftpack, patch ISO, dan validasi control-code
semuanya jalan. Scene pembuka Orbonne (doa "Bapa..." + dialog event 1) sudah
ditest di PPSSPP: tampil benar, nama speaker utuh, tidak ter-split/terpotong.
Sisa: bulk translation (Fase 8) + tes khusus jalur stretch (ID > original).

---

## Ringkasan Fase

| Fase | Nama | Status | Effort | Output |
|------|------|--------|--------|--------|
| 0 | Setup & Discovery | ✅ Done | — | Format font, decoder dasar |
| 1 | Decode Pipeline | ✅ Done | — | TEST.EVT readable as English |
| 2 | Lengkapi Char Table | ✅ Done | — | 70 single-byte + 6 multi-byte mapped |
| 3 | Parse Struktur TEST.EVT | ✅ Mostly Done | — | Header + parser shipped (`evt-header` / `evt-parse`); sisa: semantik beberapa control code (§3.3) |
| 4 | LZW Decoder | ✅ Mostly Done | — | 3/7 .LZW files extractable, 2,650 proper nouns terdata |
| 5 | Encoder & Pointer Rewriter | ✅ Done | — | Encoder + repack 100% lossless |
| 6 | Repacker | ✅ Done | — | Byte-level patch TEST.EVT → fftpack → ISO |
| 7 | Test & Verifikasi | ✅ Verified (in-place) | Ongoing | Booting di PPSSPP — opening scene OK |
| 8 | Translation Work (Gemini + human) | ⏳ Bisa parallel | Bulan-an | Konten ID actual |
| 9 | FMV Subtitle Indonesia | ⏳ Optional/Polish | 2-3 minggu | Subtitle ID di cutscene |

**Total estimasi**: 5-8 minggu pipeline text + waktu translation + 2-3 minggu FMV sub.

---

## ✅ Fase 0-1: Yang sudah selesai

### Fase 0: Setup & Discovery
- ✅ Extract FFTPACK.BIN dari ISO WoTL PSP
- ✅ Identifikasi format file `EVENT/*` (TEST.EVT, *.LZW, *.OUT, FONT.BIN, dll)
- ✅ Riset komunitas ffhacktics (`../DocumentOfComunity.md`)
- ✅ Konfirmasi: tool komunitas tidak handle dialog WoTL PSP → harus bikin sendiri

### Fase 1: Decode Pipeline
- ✅ Reverse engineer format FONT.BIN: **10×14 px, 2bpp, MSB, 35 B/glyph**
- ✅ Visual identifikasi 62 glyph: digit `0-9` + `A-Z` + `a-z`
- ✅ Verifikasi statistik: frekuensi byte di TEST.EVT cocok English letter freq
- ✅ Identifikasi punctuation utama: `! ? . ' space`
- ✅ Identifikasi multi-byte: `0xda 0x74 = ,`, `0xd1 0x1D = -`
- ✅ Identifikasi control codes dasar: `0xfe` = EOS, `0xf8` = soft break, `0xe3 0x08` = speaker tag, `0xe0` = player name
- ✅ Decoder lengkap (`psp_translate/codec/decode.py`)
- ✅ Ekstrak 8,203 blok dialog readable (`build/TEST_EVT_dialog_only.txt`)

---

## Fase 2: Lengkapi Character Table (2-4 hari)

**Tujuan**: Memetakan semua karakter yang dipakai dialog English supaya translation ID bisa pakai semua simbol yang tersedia.

### 2.1 Identifikasi punctuation tersisa
- [x] **`:` (colon) = `0x46`** — verified di "Remember: The well-aimed thrust..."
- [ ] `;` (semicolon) — tidak ditemukan di dialog (kemungkinan tidak dipakai)
- [ ] `(` `)` — tidak ditemukan di dialog
- [x] **`"` (double quote) = `0x91`** — verified di 'called a "pistol." It uses...'
- [x] **`—` (em dash) = `0xda 0x68`** — verified di "class divides—a world where..."
- [ ] `/` `*` `&` — tidak ketemu yang clear di dialog area (kemungkinan ada di HELP.LZW)

**Cara**: Pakai `psp-translate decode --search "<known word>"` untuk konteks. Lihat byte di sekitar punctuation yang expected dari original FFT script (referensi: [Final Fantasy Wiki script](https://finalfantasy.fandom.com/wiki/Final_Fantasy_Tactics:_The_War_of_the_Lions_script)).

### 2.2 Identifikasi accented characters (untuk nama)
- [x] **`ú` (u akut) = `0xda 0x65`** — verified di "Cúchulainn, the Impure" (Demon karakter)
- [ ] `é` — belum ditemukan (kemungkinan tidak ada di WoTL dialog)
- [ ] `ï` — belum ditemukan

**Catatan**: ID tidak butuh diakritik, tapi nama "Cúchulainn" harus tetap pakai ú kalau translation mempertahankan nama original.

### 2.3 Identifikasi control codes lanjutan
- [ ] `0xe0` placeholder lain (selain nama protagonis: ada untuk hero job, location?)
- [ ] Byte `0xf0+` lain yang muncul di dialog
- [ ] Multi-byte `0xd2 0x..`, `0xd3 0x..` di luar bytecode region

**Output Fase 2**: `data/char_table.json` lengkap dengan ≥80 mapping single-byte + 10+ multi-byte.

---

## Fase 3: Parse Struktur TEST.EVT (1-2 minggu)

**Tujuan**: Memahami layout file TEST.EVT untuk bisa modifikasi tanpa merusak format. **CRITICAL**: pointer table harus benar atau game crash.

### 3.1 Reverse engineer header
- [ ] Tulis `psp_translate/evt/header.py` — parse first 0x5800 byte sebagai struktur
- [ ] Identifikasi:
  - [ ] Magic number / version (4 byte pertama: `f2 f2 f2 f2`)
  - [ ] Jumlah event entries
  - [ ] Pointer table: offset ke setiap event
  - [ ] Ukuran tiap event block
- [ ] Verifikasi: pointer ke-N + size = pointer ke-(N+1)

### 3.2 Parse event block
- [ ] Tiap event punya:
  - [ ] Header event (event ID, map ID, params)
  - [ ] Bytecode script (camera, character movement, music)
  - [ ] Text data (dialog) dengan multi-bubble support
  - [ ] End-of-event marker
- [ ] Tulis `psp_translate/evt/parser.py` — pisahkan bytecode dari text

### 3.3 Semantik control codes
- [ ] `<e3>08` speaker tag — argumen apa? (icon? portrait?)
- [ ] `<f8>` soft line break — auto-wrap atau forced?
- [ ] `0xe0` placeholder — extend ke semua placeholder vars
- [ ] Color codes (kemungkinan `0xfa XX` atau `0xfc XX`)
- [ ] Delay/wait codes
- [ ] End-of-bubble vs end-of-event

**Output Fase 3**:
- `psp_translate/evt/parser.py` — parser yang ekstrak (event_id, dialog_text, control_codes)
- Format JSON intermediate untuk tiap event:
  ```json
  {
    "event_id": 123,
    "offset": 65728,
    "size": 4096,
    "bubbles": [
      {"speaker": "Knight", "text": "Lady Ovelia, it is time."},
      ...
    ],
    "bytecode": "<binary blob>"
  }
  ```

---

## Fase 4: LZW Decompressor (PARTIAL DONE ✅)

**Penemuan**: `.LZW` ternyata 2 jenis — yang plain text dan yang beneran compressed.

### 4.1 ✅ Plain text .LZW (3 file ber-pointer-table, langsung extractable)

| File | Readable | Content |
|------|----------|---------|
| WORLD.LZW | 81.8% | Job/weapon/spell/character/place names, menu, rumors |
| ATCHELP.LZW | 68.9% | Battle command tutorial text (English readable) |
| OPEN.LZW | 17.9% | Character names list (partial) |

**Format**: 128-byte header (32 LE32 pointers) + data section (0xFE-terminated strings).
Detail di `../formats/LZW_FORMAT.md`.

Tool: `psp_translate/lzw/extract.py` — sudah jalan, output JSON per file.

### 4.2 ❌ Compressed .LZW (TODO — perlu reverse engineer 0xF0 marker)

| File | Readable | Status |
|------|----------|--------|
| HELP.LZW | 8.6% | 0xF0 dominant (10,524x) — back-reference compression |
| WLDHELP.LZW | 8.1% | sama dengan HELP |
| JOIN.LZW | 8.7% | Header pointer ada yang invalid (struktur beda?) |
| SAMPLE.LZW | 6.0% | Mungkin internal test data, tidak in-game |

**Workaround tersedia**:
- HELP.LZW kemungkinan duplicate HELPMENU.OUT (byte distribution identical).
  Bisa extract HELPMENU.OUT instead.
- Tidak critical untuk translation Tier 1 (story dialog sudah cover via TEST.EVT).

### 4.3 ✅ Bonus: proper nouns extracted

Karena WORLD.LZW berisi semua nama (job/weapon/spell/character/place), kita extract
**2,650 unique proper nouns dalam 17 kategori** ke `data/proper_nouns.json`:

- characters (847): Abel, Abelard, Abraham, ...
- spells (483): Cure, Fire, Absorb MP, Abyssal Blade, ...
- weapons (291): Acacia Hat, Adamant Vest, Aegis Shield, ...
- rumors (242): named events
- quests (143), jobs (117), map_locations (110), quest_ships (93), sidequests (96), ...

**Untuk Gemini translator** (`psp_translate/translate/gemini.py`): list ini di-feed sebagai
"DO NOT TRANSLATE" reference. Setiap nama harus muncul as-is di output ID.

---

## Fase 5: Encoder (DONE ✅)

**Penemuan praktis** (lebih sederhana dari rencana awal):

Karena TEST.EVT tidak punya global pointer table (per Phase 3 — 231 event chunks
independen, 0x800-aligned), encoder hanya perlu substitusi in-place ATAU dalam
trailing zero buffer per bubble.

### 5.1 ✅ Encoder dasar (`psp_translate/codec/encode.py`)

- [x] Encoder text → bytes lossless
- [x] Handle single-byte + multi-byte sequences + named tags (`<SPEAKER>`, dll)
- [x] Roundtrip TEST.EVT FULL FILE: **byte-identical** (7,618,560 bytes)

### 5.2 ✅ Repack tool (`psp_translate/evt/repack.py`)

- [x] Substitusi bubble in-place (kalau ID ≤ EN length, pad dengan 0x00)
- [x] Stretch mode (`--allow-stretch`): extend ke trailing zero buffer kalau ada
- [x] Truncate mode (`--allow-truncate`): hard limit kalau ID terlalu panjang
- [x] Verifikasi: ALL 15,326 bubbles substitute dengan original text → **output byte-identical**

### 5.3 ✅ Translation budget (`psp_translate/evt/budget.py`)

Output: `build/translation_budget.json` — per-bubble byte budget untuk translator:
- `original_bytes`: panjang EN encoded
- `safe_bytes`: max kalau substitusi in-place (= original)
- `stretch_bytes`: max kalau extend ke adjacent zeros (rare, 2.3% bubbles)
- `event_padding_bytes`: total padding di akhir event (informational)

Stats hasil scan:
- 15,326 text bubbles
- Avg 102 bytes/bubble
- Avg stretch 159 bytes/bubble (kalau ada room)
- 348 bubbles (2.3%) dengan stretch room
- 1.5 MB total event padding (di akhir event, tidak adjacent ke bubble)

### 5.4 ⏳ Pointer rewriter (DITUNDA — tidak critical)

Karena tidak ada global pointer table, "true expansion" hanya perlu kalau:
- Translator butuh ID text > EN+stretch_buffer untuk bubble tertentu
- Solusinya: bytecode pointer rewriter PER EVENT (cari pointer ke text position di bytecode, rewrite kalau text geser)

**Status**: belum diperlukan untuk first translation pass. Translator harus
phrase ID dengan compact target ≤ EN length.

### Files Phase 5

| Path | Fungsi |
|------|--------|
| `psp_translate/codec/encode.py` | text → bytes (lossless) |
| `psp_translate/evt/repack.py` | Apply translations to TEST.EVT, output modified .EVT |
| `psp_translate/evt/budget.py` | Per-bubble byte budget calculator |
| `build/translation_budget.json` | Output budget (15,326 bubbles) |

---

## Fase 6: Repacker (DONE ✅)

**Pendekatan sederhana berhasil**: byte-level substitution di posisi yang sudah dipetakan, tanpa rebuild ISO dari scratch.

### 6.1 ✅ Map files dalam fftpack.bin

Tool: `psp_translate/pack/fftpack.py` + mapping di `data/fftpack_event_map.json`.

File yang ter-mapping (offset di fftpack.bin):
- `TEST.EVT` @ 0x00361800 (3,545,088)
- `WORLD.LZW` @ 0x00dab800 (14,333,952)
- `ATCHELP.LZW` @ 0x00d83000 (14,168,064)
- `OPEN.LZW` @ 0x00dbf800 (14,415,872)
- `WLDHELP.LZW` @ 0x00dd9000 (14,520,320)
- `SPELL.MES` @ 0x00da3000 (14,299,136)
- 4 file partial (HELP/JOIN/SAMPLE/FONT) — perlu fingerprint lebih dalam

### 6.2 ✅ Patch fftpack.bin (`psp_translate/pack/fftpack.py`)

CLI: substitute file dengan known offset, output modified fftpack.bin.
Verified: TEST.EVT modified → fftpack.bin 220 MB modified, decode masih readable.

### 6.3 ✅ Patch ISO langsung (`psp_translate/pack/iso.py`)

Pendekatan paling efisien: karena ukuran preserved, langsung byte-patch
ISO di posisi yang sudah dipetakan (`fftpack.bin` @ 0x02c20000 di ISO).
Skip ISO rebuild penuh.

Mode:
- `--substitute LABEL:NEW:OFFSET` — manual offset
- `--substitute-auto LABEL:NEW:ORIG` — auto-find via content matching

### End-to-end pipeline VERIFIED ✅

```
Translation JSON
       ↓
psp-translate evt-repack → modified TEST.EVT (same size)
       ↓
psp-translate fftpack    → modified fftpack.bin (same size)
       ↓
psp-translate iso        → modified ISO (same size, 418 MB)
       ↓
Test di PPSSPP
```

Or in one shot: `psp-translate pipeline --translations ... --original-iso ... --output-iso ...`

Hasil test: prayer area "Father" → "Bapa" terdecode dengan benar dari modified ISO.

### Files Phase 6

| Path | Fungsi |
|------|--------|
| `psp_translate/pack/fftpack.py` | Patch file di fftpack.bin |
| `psp_translate/pack/iso.py` | Patch fftpack.bin langsung di ISO |
| `data/fftpack_event_map.json` | Offset mapping per file di fftpack.bin |

---

## Fase 7: Test & Verifikasi (ongoing dari Fase 5+)

### ✅ HASIL VERIFIKASI (2026-06-20)

Ditest di PPSSPP dengan `/tmp/FFT_retest_opening.iso` (scene pembuka Orbonne,
event 1: doa "Bapa..." + 20 blok dialog). **Tampil benar, tidak ada bug** —
nama speaker utuh, kalimat lengkap, tidak ter-split. Jalur in-place (ID ≤
panjang original) TERVALIDASI in-game.

#### 🐛 Bug ditemukan & diperbaiki (regression dari fix "OOOO")

Saat ID lebih pendek dari EN, `repack_evt.py` lama menulis `[ID]+0xFE` di awal
bubble lalu **meninggalkan ekor English original** → muncul `0xFE` KEDUA + teks
sisa. Akibatnya engine membaca string ekstra: **dialog ter-split, nama speaker
hilang, kalimat terpotong**.

**Fix**: bubble harus tetap panjang byte SAMA dan **persis satu `0xFE` di
`byte_end-1`**. Tulis teks ID, isi gap dengan **space `0x95`** (bukan `0x00` —
itu glyph '0' = bug "OOOO"), terminator tunggal di posisi asli. Lihat
`CLAUDE.md` → "Repack bubble invariant".

Verifikasi: identity roundtrip byte-identical (19,925 bubble) + in-game PPSSPP.

#### ✅ Validasi control-code (`psp_translate/translate/pipeline.py`)

`validate_translation` sekarang cek tiap token `<...>` (`<SPEAKER>`, `<f8>`,
`<e0>`, `<PRAYER>`, `<e2>6`, `<XX>`) jumlahnya sama di `id_final`, dan speaker
bubble harus diawali `<SPEAKER>`. Pelanggaran = FATAL (pipeline abort; override
`--ignore-control-errors`).

#### ⏳ Belum diverifikasi

- Jalur `--allow-stretch` (ID **lebih panjang** dari original → extend ke
  trailing zeros). Di retest semua ID dibuat muat in-place, jadi stretch tak
  pernah terpicu. Perlu tes khusus karena bisa menggeser posisi terminator.

### 7.1 Test minimal (asap setelah encoder siap)
- [x] Edit bubble di TEST.EVT (doa + dialog opening Orbonne)
- [x] Encode + repack
- [x] Boot di PPSSPP — verifikasi:
  - Tidak crash
  - Text muncul benar di game
  - Game flow tidak rusak

### 7.2 Test stres
- [ ] Edit text dengan **PANJANG BERBEDA** dari original (test pointer rewriter)
- [ ] Edit di event tengah game (test pointer untuk semua event sesudahnya)
- [ ] Edit nama character placeholder (test `<e0>` masih kerja)

### 7.3 Test cross-file
- [ ] Setelah LZW codec siap: test edit HELP.LZW
- [ ] Verifikasi pemilihan kata di world map / battle menu

---

## Fase 8: Translation Work (parallel dari Fase 2+)

Tidak perlu nunggu tools 100% selesai — bisa start translasi paralel dengan engineering.

### 8.1 ✅ Setup workflow translasi
- [x] `psp_translate/translate/workspace.py` (CLI: `psp-translate workspace`)
  - Input: `build/events_parsed.json`
  - Output: 45 chunks of 100 blocks each (`workspace/chapter_*.json`) + `index.json`
  - Schema: `id`, `en`, `id_auto`, `id_final`, `flags`, `status` per block
- [x] Versioning: workspace/ gitignored (user-specific); translations go into the chunk files

### 8.2 Priority order translasi
Berdasarkan importance untuk player:
- [ ] **Tier 1** (essential): Story dialog (TEST.EVT) — Chapter 1-4 berurutan
- [ ] **Tier 2** (high value): UI text (HELP.LZW, WLDHELP.LZW, menu)
- [ ] **Tier 3** (nice to have): Battle quotes, item descriptions
- [ ] **Tier 4** (optional): Tutorial text, status messages

### 8.3 Style guide ID — **STRICT RULES**

**Aturan inviolable** (tidak boleh dilanggar saat translation):

- [ ] **JANGAN translate proper nouns** — biarkan English persis:
  - **Nama karakter**: Ramza, Delita, Ovelia, Agrias, Gaffgarion, Wiegraf, Cúchulainn, dll
  - **Nama tempat**: Ivalice, Lionel, Mullonde, Orbonne, Goug, Ziekden, dll
  - **Nama item**: Excalibur, Save the Queen, Phoenix Down, Elixir, dll
  - **Nama spell**: Fire, Holy, Cure, Raise, Meteor, dll
  - **Nama job**: Knight, Black Mage, Onion Knight, Dark Knight, Squire, dll
  - **Nama organisasi**: Order of the Northern Sky, Church of Glabados, House Beoulve, dll
  - **Istilah game**: HP, MP, JP, AT, Brave, Faith, Zodiac, Aurascite, dll
- [ ] **Honorifik tetap English juga**: "Lord", "Lady", "Sir", "Ser", "Highness", "Majesty", "Eminence"
- [ ] **Hanya translate**: dialog narratif (kata-kata yang diucapkan/dipikirkan)

**Style campuran** (formal + casual sesuai karakter):
- Karakter aristocrat/religious (Ovelia, Cardinal, Priest, Father): formal/baku
- Karakter sarcastic (Gaffgarion, Mustadio): campur slang
- Karakter prajurit (Knight, Soldier): netral
- Karakter villain (Demon, Cúchulainn): formal+ominous

### 8.4 Auto-translation dengan Gemini API

User memilih pakai Gemini API untuk auto-translation EN→ID. Workflow:

- [x] `psp_translate/translate/gemini.py` (CLI: `psp-translate gemini`)
  - Input: workspace chunk JSON (or plain text dialog file)
  - Output: same JSON with `id_auto`, `flags`, `status` filled per block
  - Pakai `google-genai` SDK; system prompt template di `docs/gemini_prompt_template.md`
  - **Prompt sudah grounded** dengan aturan strict di atas:
    - Jangan translate proper nouns (proper noun list dari `data/proper_nouns.json`)
    - Preserve control codes `<f8>`, `<e0>`, `<SPEAKER>`, dll EXACTLY
    - Adjust style sesuai speaker (character profile in prompt)
    - Singkatan umum ID (`yg`, `dgn`, `utk`…) untuk muat byte budget
- [x] Resumable: blocks yang sudah `auto`/`approved` di-skip pada run berikutnya
- [x] API key handling: env var `GEMINI_API_KEY`
- [x] Rate limiting: `--sleep` flag (default 4.5s ~ 13 RPM)
- [x] Dry-run mode: `--dry-run` cetak prompt tanpa kuota API

### 8.5 ✅ Translation validation (integrated)
- [x] `validate_translation()` di `psp_translate/translate/pipeline.py`
  - Verifikasi semua control codes (`<f8>`, `<e0>`, `<SPEAKER>`, raw `<XX>`) preserved per bubble
  - Speaker bubble harus diawali `<SPEAKER>`
  - Pelanggaran = FATAL (pipeline ABORTS; override `--ignore-control-errors`)
- [x] Byte length per bubble: `psp-translate budget` + repacker stats (`applied_in_place`, `applied_stretched`, `skipped_too_long`)
- [ ] Proper-noun check otomatis (verify nama tidak ke-translate) — masih manual review
- [ ] Spell check ID (optional)

### 8.6 QA workflow
- [ ] Tester (idealnya 2-3 orang) play through game dengan translasi
- [ ] Report bug: salah konteks, text overflow, encoding error, nama ke-translate
- [ ] Iterate

---

## Fase 9: FMV Subtitle Indonesia (NEW — ambitious track)

User mau **subtitle ID** di FMV cutscene (yang punya voice acting English).
Ini track terpisah, lebih sulit dari text translation.

### 9.1 Riset format .pmf PSP
- [ ] Extract FMV dari ISO (`PSP_GAME/USRDIR/*.pmf` atau di dalam FFTPACK)
- [ ] Riset format PSMF (PlayStation Movie Format)
- [ ] Tools yang tersedia: `pmfplayer`, `vpsmplay`, ffmpeg dengan PSMF support

### 9.2 Pilih approach subtitle
**Opsi A** (recommended): Hard-subtitled FMV
- Extract .pmf → convert ke .mp4 (demux H.264 + audio)
- Overlay subtitle ID via ffmpeg `subtitles` filter
- Convert balik ke .pmf format kompatibel PSP
- Replace di ISO
- **Risk**: kualitas video bisa drop, encoder PSMF challenging

**Opsi B**: Modify game code untuk render subtitle overlay
- Patch executable PSP — terlalu sulit tanpa source code

### 9.3 Implementation
- [ ] Tulis `psp_translate/fmv_extract.py` — pisahkan video stream dari .pmf
- [ ] Tulis `psp_translate/fmv_subtitle.py` — overlay subtitle dengan ffmpeg
- [ ] Tulis `psp_translate/fmv_repack.py` — convert balik ke .pmf
- [ ] Buat .srt file dari translated dialog (timing sync manual)

**Catatan**: Track ini bisa **DITUNDA** sampai Fase 1-7 selesai. FMV subtitle adalah polish layer, bukan blocker untuk playable translation.

---

## Risiko & Mitigasi

| Risiko | Probabilitas | Dampak | Mitigasi |
|--------|--------------|--------|----------|
| Pointer table struktur lebih kompleks dari dugaan | Tinggi | Tinggi | Mulai dengan event KECIL untuk test |
| ID text selalu lebih panjang dari EN (struktur bahasa) | Sangat tinggi | Sedang | Compact ID phrasing + pointer rewriter robust |
| Control codes punya constraint tidak terdokumentasi | Sedang | Tinggi | Test exhaustive di PPSSPP, observe behavior |
| LZW varian custom susah di-port | Rendah | Sedang | Ada referensi di forum ffhacktics |
| Karakter ID (`é`, dst) tidak tersedia di font | Rendah | Rendah | ID standar tidak butuh diakritik |
| PPSSPP behavior beda dari real PSP | Rendah | Sedang | Test juga di real hardware kalau possible |

---

## Tools yang Akan Dibuat

| Tool | Status | Fase | Fungsi |
|------|--------|------|--------|
| `psp_translate/revtools/explore.py` | ✅ Done | 0 | Heuristic byte analyzer |
| `psp_translate/revtools/font_render.py` | ✅ Done | 1 | FONT.BIN → PGM |
| `psp_translate/codec/char_table.py` | ✅ Done | 1-2 | Manage char_table.json |
| `psp_translate/codec/decode.py` | ✅ Done | 1 | TEST.EVT → readable text |
| `psp_translate/evt/header.py` | ✅ Done | 3 | Parse TEST.EVT header (CLI: `psp-translate evt-header`) |
| `psp_translate/evt/parser.py` | ✅ Done | 3 | Split bytecode + text (CLI: `psp-translate evt-parse`) |
| `psp_translate/lzw/codec.py` | TODO | 4 | LZW de/compress (folder ada; `extract.py` ✅ untuk plain-text LZW) |
| `psp_translate/codec/encode.py` | ✅ Done | 5 | text → bytes (CLI: `psp-translate encode`) |
| `psp_translate/evt/pointer.py` | TODO | 5 | Pointer rewriter for true expansion (DITUNDA — lihat §5.4) |
| `psp_translate/evt/repack.py` | ✅ Done | 6 | Apply translations → modified TEST.EVT (CLI: `psp-translate evt-repack`) |
| `psp_translate/pack/fftpack.py` | ✅ Done | 6 | Patch fftpack.bin (CLI: `psp-translate fftpack`) |
| `psp_translate/translate/workspace.py` | ✅ Done | 8 | Build translation workspace chunks (CLI: `psp-translate workspace`) |
| `psp_translate/translate/gemini.py` | ✅ Done | 8 | Auto-translate EN→ID via Gemini API (CLI: `psp-translate gemini`) |
| `psp_translate/translate/pipeline.py` :: `validate_translation` | ✅ Done | 8 | Control-code + proper-noun validator (integrated in `pipeline`, ABORTS on violation) |
| `psp_translate/pack/iso.py` | ✅ Done | 6 | Size-preserving ISO patch (CLI: `psp-translate iso`) |
| `psp_translate/xdelta_build.py` | TODO | 6 | Generate xdelta3 patch (original ISO → mod ISO) |
| `psp_translate/fmv/extract.py` | TODO | 9 | Extract video dari .pmf PSP |
| `psp_translate/fmv/subtitle.py` | TODO | 9 | Overlay subtitle ID via ffmpeg |
| `psp_translate/fmv/repack.py` | TODO | 9 | Repack mp4 → .pmf PSP-kompatibel |

---

## Keputusan User (RESOLVED ✅)

| # | Topik | Jawaban | Implikasi |
|---|-------|---------|-----------|
| 1 | Penamaan karakter | **Tetap English** | Strict: Ramza, Delita, dst TIDAK ditranslate. Plus semua proper nouns (item, spell, job, place, organization). Lihat Fase 8.3. |
| 2 | Scope | **Full game** | TEST.EVT + semua .LZW + battle quotes + UI. Bukan story-only. Multi-track work. |
| 3 | Style ID | **Campuran + Gemini API** | Auto-translate dengan Gemini AI, lalu human review. Style adjusted per karakter (formal/casual). Lihat Fase 8.4. |
| 4 | Distribusi | **xdelta3 patch** | Distribusi file patch saja (~5-20 MB). User apply patch ke ISO original sendiri. Legal-safe, standar komunitas ROM hack. |
| 5 | FMV subtitle | **YA, subtitle ID** | Track terpisah (Fase 9). Hard-sub via ffmpeg. Bisa ditunda sampai pipeline text selesai. |

### Aturan Strict (jangan dilanggar saat translation)

**HANYA dialog narratif yang ditranslate**. Yang TIDAK BOLEH diubah:

- Nama karakter (Ramza, Delita, Ovelia, Cúchulainn, dll)
- Nama item (Excalibur, Phoenix Down, dll)
- Nama spell (Fire, Holy, Cure, dll)
- Nama job (Knight, Black Mage, Onion Knight, dll)
- Nama tempat (Ivalice, Lionel, Orbonne, dll)
- Nama organisasi (Order of the Northern Sky, dll)
- Istilah game (HP, MP, JP, Brave, Faith, dll)
- Honorifik (Lord, Lady, Sir, Ser, Highness, dll)
- Control codes (`<f8>`, `<e0>`, `<SPEAKER>`, dll)

Aturan ini di-encode di:
- `docs/gemini_prompt_template.md` (prompt yang dibaca oleh `psp_translate/translate/gemini.py`; berlaku juga sebagai style guide manusia)
- `validate_translation()` di `psp_translate/translate/pipeline.py` (automated check — control codes & speaker tag)

---

## Recommended Next Step (Updated 2026-06-20, post-refactor)

**Pipeline engineering ✅ DONE** (Fase 0-7): decode → encode → repack EVT → patch
fftpack → patch ISO + control-code validator semuanya jalan, opening Orbonne
verified in-game (PPSSPP), `--allow-stretch` path verified programmatically
(`psp-translate verify` / `tests/test_stretch_path.py`).

**Codebase ✅ REFACTORED** (2026-06-20): tools/ flatpack → `psp_translate/`
package + `data/` (source) + `build/` (generated) + `docs/` + `tests/`. Single
CLI: `psp-translate <sub>` (or `python -m psp_translate <sub>`).

### Track utama yang tersisa

**Track A — Bulk translation work (Fase 8)** — primary remaining work:
- Iterate per chapter: `psp-translate gemini workspace/chapter_NN.json
  workspace/chapter_NN.out.json`
- Review blok ber-flag (`status='needs_review'`), isi `id_final`
- Rakit incremental: `psp-translate pipeline --translations workspace/`
  (auto-merge semua chapter)
- Test di PPSSPP per beberapa chapter

#### ✅ Checkpoint 2026-06-21 — Fase 8 dimulai (wiki-grounded)

- **Wiki grounding shipped**: `data/wiki_script/fft_story_dialogue.json` (script
  kanonik Final Fantasy Wiki, 66 scene / 1970 baris) sekarang dipakai untuk
  *grounding* translator. Tiap blok dicocokkan ke baris kanonik (`psp_translate/
  translate/wiki_ref.py`); baris bersih disuntik ke prompt Gemini sbg `wiki_ref`
  (makna otoritatif, anti-noise/anti-halusinasi). `script_check.py` refactor
  pakai helper yang sama.
- **gemini.py robustness**: (a) auto-retry control-code — blok yang drop/ubah
  `<...>` dikirim ulang sekali, diadopsi hanya kalau code-nya sudah benar;
  (b) `load_system_prompt` tahan template fenced/plain (fix bug saat user update
  prompt tanpa ``` fence); (c) `merge_blocks` simpan `byte_length` utk blok baru.
- **Chapter 01 — DONE & reviewed**: 84 auto + 11 approved + 5 skip. 0 control-code
  mismatch. (Translation outputs live di `workspace/` yg gitignored.)
- **Chapter 02 — DONE & reviewed**: 58 auto + 36 approved + 6 skip. 0 control-code
  mismatch. 12 blok error (batch awal gagal parse/503) berhasil di-recover.
- **Keputusan gaya (precedent untuk chapter berikutnya)**: honorifik boleh
  dilokalkan; `Order`→"Ordo", `Corpse Brigade`→"Pasukan Mayat", nama institusi
  spt `Akademy` tetap English. Konfirmasi per-term saat review.
- **Diketahui aman**: sebagian bubble adalah bytecode-glued (mis-parsed: bytecode
  + dialog tail) → di-`skip`; baris itu tetap English in-game (tidak korup).
- **Berikutnya**: chapter 03+ (saran `--batch 8`). Nice-to-have: auto-retry untuk
  error transient 503/JSON di `gemini.py` (sekarang masih perlu re-run manual).

**Track B — Distribution (Fase 6 leftover + new)**
- `xdelta3` patch generator (TODO: `psp_translate/xdelta_build.py`)
- README untuk distribusi patch ke end-user

**Track C — FMV subtitle (Fase 9, optional)**
- Tunda sampai Track A produktif. PSMF format reverse engineering.

### Nice-to-have engineering
- Pointer rewriter (§5.4 — `psp_translate/evt/pointer.py`) untuk true expansion
  kalau Track A menemukan banyak bubble `skipped_too_long`.
- LZW compressor (§4.2 — `psp_translate/lzw/codec.py`) kalau translasi
  perlu sentuh HELP.LZW / WLDHELP.LZW.

---

*Last updated: 2026-06-21 (Fase 8 started: wiki-grounded Gemini translate; chapter 01 & 02 done + reviewed)*
