# Dokumentasi Komunitas — FFT: War of the Lions (PSP) Translation

Ringkasan riset dari komunitas **FFHacktics** dan sumber lain terkait modding /
translasi *Final Fantasy Tactics: The War of the Lions* (PSP). Dokumen ini dibuat
sebagai basis pengambilan keputusan untuk proyek translasi EN→ID.

---

## 1. Tool Resmi Komunitas

### 1.1 FFTactext (yang sedang dipakai)

- **Fungsi**: Editor teks untuk job name, ability name, item name, skill description, menu, help text.
- **Versi rekomendasi**: **0.457** — versi paling stabil untuk WotL PSP.
- **Batasan penting**: **TIDAK** dapat mengedit dialog cerita (story dialogue) di `TEST.EVT`. Scope-nya hanya text section yang ter-expose oleh tool.
- **Platform**: Windows (jalan via Wine di macOS/Linux — sudah terkonfirmasi).
- **Dokumentasi**: <https://ffhacktics.com/wiki/FFTactext>
- **Thread resmi (Tactext)**: <https://ffhacktics.com/smf/index.php?topic=3165.0>

### 1.2 TLW FFTText Editor v1.1

- **Fungsi**: Editor teks lengkap (termasuk dialog cerita) untuk **The Lion War** — PSX mod yang mem-port konten WotL ke ROM PSX original.
- **Catatan penting**: Tool ini **untuk PSX, bukan PSP**. Patching dilakukan melalui Tactext bundled dengan FFTPatcher 0.493 Beta 7+.
- **Thread**: <https://ffhacktics.com/smf/index.php?topic=12847.0>

### 1.3 FFTPatcher

- **Fungsi**: Patcher utama untuk FFT (PSX & PSP). Mengandung Tactext untuk distribusi patch teks.
- **Wiki tools**: <https://ffhacktics.com/wiki/Tools>

---

## 2. Format File yang Relevan (WotL PSP)

Lokasi: `PSP_GAME/USRDIR/FFTPACK.BIN` → setelah extract jadi folder dengan
struktur seperti yang ada di repo ini (`extracted/FFTPACK_Extracted/EVENT/`).

| File | Ukuran | Isi | Status tool komunitas |
|------|--------|-----|------------------------|
| **TEST.EVT** | 7.3 MB | **Semua dialog cerita + event script + bytecode** | ❌ Tidak ada editor user-friendly untuk PSP |
| ATTACK.OUT | 126 KB | Battle quotes, pre-battle text | ❌ Tidak fully supported |
| WLDHELP.LZW | 82 KB | World map help text (LZW compressed) | ⚠️ Sebagian |
| HELP.LZW | 64 KB | General help text (LZW compressed) | ⚠️ Sebagian |
| OPEN.LZW | 26 KB | Opening cutscene text | ⚠️ Sebagian |
| WORLD.LZW | 80 KB | World map text | ⚠️ Sebagian |
| JOIN.LZW | 12 KB | Karakter join text | ⚠️ Sebagian |
| SPELL.MES | 18 KB | Spell messages | ⚠️ Sebagian |
| FONT.BIN | 76 KB | Bitmap font glyph | ✅ Bisa di-reverse manual |
| BATTLE.BIN | — | Battle code + lookup tables | — |

### 2.1 TEST.EVT — Format Custom

- Byte-level encoding **bukan ASCII** — pakai **custom charset table** (mapping `byte → glyph index` di `FONT.BIN`).
- Control codes 1-byte untuk: delay, color, character name placeholder (`{Ramza}`, `{Delay}`, dll).
- Punya **pointer table** di header → menunjuk ke setiap event.
- **Konsekuensi**: text Indonesia yang lebih panjang dari Inggris → semua pointer setelahnya harus di-update, atau game crash / text rusak.

### 2.2 LZW Files

- Format LZW **non-standar** (varian custom FFT).
- Harus di-decompress, edit, recompress dengan algoritma yang sama.

---

## 3. Konsensus Komunitas Tentang Dialog WotL PSP

Hasil dari thread-thread teknis:

> **Dialog cerita WotL PSP sangat sulit di-edit secara langsung.**
> Hampir semua proyek translasi serius FFT akhirnya **pindah ke The Lion War (PSX)**, karena di sana tooling-nya lengkap.

Indikasi konkret:
- Tidak ada thread aktif yang mempublish editor dialog WotL PSP yang user-friendly.
- Diskusi script dialog WotL ([thread ini](https://ffhacktics.com/smf/index.php?topic=9823.0)) banyak diarahkan ke jalur PSX.
- Tool **Tactext** untuk PSP secara eksplisit di-dokumentasi sebagai "text, code, events, and more" tapi **bukan editor dialog graphical** — masih perlu pemahaman format mendalam.

---

## 4. Jalur Alternatif: The Lion War (PSX)

- **The Lion War** adalah PSX mod yang mem-port konten tambahan WotL (job baru, cerita tambahan, multiplayer-only content) ke ROM PSX FFT original.
- **Keunggulan untuk translator**:
  - Tooling lengkap (TLW FFTText Editor, EasyVent, dll).
  - Dialog 100% dapat di-edit.
  - Komunitas aktif support.
- **Trade-off**:
  - Main di emulator PSX (ePSXe, DuckStation, Mednafen) — bukan PSP/PPSSPP.
  - Grafis 2D PSX (bukan widescreen PSP).
  - Audio voice acting WotL tidak ada (PSX audio).
- **Board**: <https://ffhacktics.com/smf/index.php?board=78.0>

---

## 5. Jika Tetap Ingin WotL PSP — Pekerjaan Reverse Engineering

Yang harus di-implement (Python/C++) bila membangun tool sendiri:

| Komponen | Estimasi effort | Risiko |
|----------|----------------|--------|
| 1. Character table (font map) dari FONT.BIN | 1-3 hari (kalau metodis) | **Sedang** — komunitas mungkin sudah punya, perlu cari |
| 2. Control codes / tag parser | 1-2 minggu trial & error | Sedang |
| 3. LZW decompressor (varian FFT) | 3-7 hari | Rendah (LZW well-known) |
| 4. Pointer table parser & rewriter (TEST.EVT) | 1 minggu | **Tinggi** — kalau salah, game crash |
| 5. Repacker (TEST.EVT + LZW + FFTPACK + ISO) | 1-2 minggu | Sedang |

**Total realistis**: 2-4 bulan kerja part-time untuk programmer kompeten, dengan
asumsi nyaman dengan hex editor (HxD / 010 Editor) dan debugger PPSSPP.

### Sumber kode yang bisa di-port

- **FFTactext / Tactext** open source (C#/.NET) — bisa dibaca logic-nya dan di-port ke Python/C++.
- **PPSSPP** open source — dapat dipakai untuk dump memory saat game baca TEST.EVT.

---

## 6. Daftar Link Penting

### Wiki & Dokumentasi
- [FFHacktics Wiki — Tools](https://ffhacktics.com/wiki/Tools)
- [FFHacktics Wiki — FFTactext](https://ffhacktics.com/wiki/FFTactext)
- [FFHacktics Tutorials](https://ffhacktics.com/tutorials.php?id=9)

### Forum Boards
- [War of the Lions Hacking (main board)](https://ffhacktics.com/smf/index.php?board=15.0)
- [War of the Lions Hacking — page 3](https://ffhacktics.com/smf/index.php?board=15.60)
- [The Lion War board](https://ffhacktics.com/smf/index.php?board=78.0)

### Thread Teknis Spesifik
- [Tactext — thread resmi](https://ffhacktics.com/smf/index.php?topic=3165.0)
- [FFT/WotL Dialogue Script discussion](https://ffhacktics.com/smf/index.php?topic=9823.0)
- [Asking for TLW 2.021 Resources — FFTText Editor](https://ffhacktics.com/smf/index.php?topic=12847.0)
- [What does FFTPatcher and Lion Editor do?](https://ffhacktics.com/smf/index.php?topic=11279.0)

### Referensi Eksternal
- [FFT: WotL Script (Final Fantasy Wiki — Fandom)](https://finalfantasy.fandom.com/wiki/Final_Fantasy_Tactics:_The_War_of_the_Lions_script) — full English script, berguna untuk referensi translation
- [FFT: WotL Game Script — GameFAQs](https://gamefaqs.gamespot.com/psp/937312-final-fantasy-tactics-the-war-of-the-lions/faqs/50913)
- [Tactics League — Tutorials](https://tacticsleague.com/tutorials/)

### Thread GameFAQs (Q&A pengguna)
- [FFtactext help thread](https://gamefaqs.gamespot.com/boards/937312-final-fantasy-tactics-the-war-of-the-lions/70048985)
- [FFHacktics text edit question](https://gamefaqs.gamespot.com/boards/937312-final-fantasy-tactics-the-war-of-the-lions/74820409)

---

## 7. Rekomendasi Akhir

Berdasarkan riset di atas, tiga jalur realistis:

1. **Translasi parsial WotL PSP** (paling cepat dapat hasil)
   - Pakai FFTactext untuk: job/ability/item/skill/menu/help.
   - Hasil: ~40-50% game ber-bahasa Indonesia, dialog cerita tetap Inggris.
   - Effort: minggu-an.

2. **Pindah ke The Lion War (PSX)** (kalau prioritas dialog 100%)
   - Pakai TLW FFTText Editor + ekosistem PSX.
   - Hasil: 100% translatable.
   - Trade-off: bukan PSP, grafis PSX, tanpa voice acting WotL.

3. **Bangun tool Python/C++ sendiri untuk WotL PSP** (proyek panjang)
   - 2-4 bulan minimum.
   - Mulai dari Fase 0: riset 1-2 minggu di thread teknis ffhacktics untuk cari character table & dokumentasi format yang sudah ada.
   - Hanya layak kalau ada commit waktu konsisten dan nyaman dengan reverse engineering.

---

## 8. Progress Reverse Engineering Internal (2026-06-18 / 19)

Tanpa bantuan dokumentasi komunitas, sebagian format sudah berhasil
di-reverse melalui analisis statistik file. Catatan teknis:

### 8.1 Format FONT.BIN

| Properti | Nilai |
|----------|-------|
| Ukuran glyph | **10 × 14 pixel** |
| Bit depth | **2 bpp** (anti-aliased, 4 grayscale level) |
| Bit order | MSB first |
| Byte per glyph | **35** |
| Total glyph | 2223 |

**Cara ditemukan**: autocorrelation byte di FONT.BIN menunjukkan periodisitas
**41% di lag 35** (jauh di atas baseline). Dari sana 10×14×2/8 = 35 cocok.
Verifikasi visual: glyph #0 = "0", #1 = "1", ..., #10 = "A", #35 = "Z",
#36 = "a", #61 = "z".

### 8.2 Character mapping (sebagian)

Confirmed dari visual + frekuensi byte:

```
Glyph idx  Char    Notes
  0-9      0-9     digit
 10-35     A-Z     uppercase
 36-61     a-z     lowercase
 62+       ???     belum dipetakan (kemungkinan accented + symbol + kanji)
```

**Verifikasi statistik**: frekuensi byte di `TEST.EVT` cocok dengan frekuensi
huruf English:
- `e` (0x28) = 68K hits (paling sering — sesuai 'e' = huruf paling umum)
- `o` (0x32) = 51K, `t` (0x37) = 45K, `a` (0x24) = 40K
- `i` (0x2c), `r` (0x35), `n` (0x31), `s` (0x36), `h` (0x2b) urut frekuensi

Disimpan di `data/char_table.json`.

### 8.3 Encoding TEST.EVT (parsial)

- Byte 0x00 = padding/null (69% dari file, struktur sparse)
- Byte 0x00-0x3D langsung map ke glyph 0-61 (alphabet)
- **0xD0-0xDF**: kemungkinan **multi-byte prefix** (chunk ID, butuh byte berikut)
- **0xF0+**: kemungkinan **control codes** (color, delay, character placeholder)
- **0xFE**: end-of-string marker (27K hits)
- **0x95**: belum jelas (109K hits, bukan space)

### 8.4 File cluster yang share encoding sama

Top byte 0xD1, 0xD2, 0xD3, 0xFE menunjukkan file-file berikut pakai encoding sama:
- `TEST.EVT` (dialog cerita utama)
- `SPELL.MES` (spell text)
- `HELP.LZW`, `WLDHELP.LZW`, `JOIN.LZW`, `SAMPLE.LZW` (post-decompress)
- `HELPMENU.OUT`, `SMALL.OUT`

→ Sekali decoder TEST.EVT siap, **6+ file langsung bisa di-decode**.

### 8.5 Tools internal yang sudah dibuat

| Path | Fungsi |
|------|--------|
| `psp_translate/revtools/explore.py` | Scanner heuristik byte stats + ASCII run untuk file biner |
| `psp_translate/revtools/font_render.py` | Render FONT.BIN ke PGM dengan format yang sudah diketahui |
| `psp_translate/codec/char_table.py` | Build & maintain char_table.json |
| `data/char_table.json` | Mapping glyph index → karakter (62 confirmed) |
| `build/font_renders/` | PGM output untuk inspeksi visual |
| `build/font_renders/glyph_dump.txt` | ASCII art tiap glyph (referensi visual) |

### 8.6 BREAKTHROUGH: Dialog TEST.EVT Berhasil Di-Decode

Setelah karakter table dasar terverifikasi via frekuensi byte, decoding TEST.EVT
**berhasil membaca dialog asli FFT WoTL** — termasuk opening prayer, scene Ovelia/Agrias,
scene Ziekden/Tietra, dan dialog karakter sepanjang game.

#### Punctuation tambahan yang teridentifikasi:

| Byte | Char | Cara verifikasi |
|------|------|-----------------|
| `0x3e` | `!` | "Govern your tongue!", "Milady! The enemy is upon us!", "To battle!" |
| `0x40` | `?` | "are you?", "Duke Goltanna's men?", "What is it, <e0>?" |
| `0x5f` | `.` | "salvation.", "Majesty.", "hurry.", "Lord..." (3x period = "...") |
| `0x93` | `'` | "I'll", "lady's", "It's", "Don't" |
| `0x95` | ` ` (space) | Antar tiap kata di dialog |
| `0xfe` | EOS | End-of-string / line break |

#### Multi-byte sequences:

| Sequence | Meaning |
|----------|---------|
| `0xda 0x74` | `,` comma |
| `0xd1 0x1D` | `-` hyphen ("rain-sodden", dll) |
| `0xe3 0x08` | speaker tag start |
| `0xe2 0x02` | paragraph/stanza start (di prayer) |
| `0xf8` | soft line break dalam dialog box |
| `0xe0` | placeholder nama protagonis (Ramza/custom) |

#### Hasil decode:

- Decoded text TEST.EVT: **5.9 MB** (27,454 baris)
- Dialog blocks terekstrak: **8,203 blok readable English**
- Sample yang ter-decode dengan benar:
  - Opening prayer: "Father, abandon not Your wayward children of Ivalice..."
  - Knight scene: "Lady Ovelia, it is time." / "I'll not be much longer, Agrias."
  - Gaffgarion: "Mayhap bowed heads would less offend. You would do well to waste..."
  - Ramza-Tietra arc: "Tietra died because I could not be bothered to save her."

#### Tools final:

| Path | Fungsi |
|------|--------|
| `psp_translate/codec/decode.py` | Decoder lengkap dengan multi-byte support + search |
| `build/TEST_EVT_decoded.txt` | Full decoded TEST.EVT (5.9 MB) |
| `build/TEST_EVT_dialog_only.txt` | Dialog-only ekstrak (844 KB) |

### 8.7 Status pekerjaan (updated 2026-06-19)

Hampir semua estimasi awal **berhasil di-resolve lebih cepat** dari yang diperkirakan:

| Step | Status | Catatan |
|------|--------|--------|
| ~~Identifikasi font format~~ | ✅ Done | 10×14 px @ 2bpp, 35 B/glyph |
| ~~Char table dasar (digit + A-Z + a-z)~~ | ✅ Done | 62 chars verified |
| ~~Punctuation utama~~ | ✅ Done | 70 single-byte + 6 multi-byte total |
| ~~Decoder dengan multi-byte support~~ | ✅ Done | psp_translate/codec/decode.py |
| ~~Punctuation tersisa~~ | ✅ Done | `:`, `"`, `—`, `ú`, `-`, ... |
| Parse semantik control codes (color, delay) | ⏳ Partial | Phase 7 (runtime test) |
| ~~Pointer table parser di TEST.EVT header~~ | ✅ Done | Tidak ada global table — 231 event chunks 0x800-aligned |
| **~~Encoder ID→bytes~~** | ✅ Done | **100% lossless** (psp_translate/codec/encode.py) |
| LZW decompressor untuk .LZW files | ⏳ Partial | 3/7 plain text, 4 compressed TODO |
| ~~Repacker FFTPACK + ISO~~ | ✅ Done | Byte-level patch (no rebuild needed) |

### 8.8 BREAKTHROUGH MAJOR: End-to-End Pipeline WORKING ✅

Setelah Phase 5+6 selesai, kita punya **full translation pipeline byte-level** yang BUKAN rebuild ISO from scratch — cukup substitusi pada offset yang dipetakan:

```
Translation JSON (Gemini auto / human)
       ↓
psp_translate/evt/repack.py        → modified TEST.EVT (same 7.6 MB)
       ↓
psp_translate/pack/fftpack.py    → modified fftpack.bin (same 210 MB)
       ↓
psp_translate/pack/iso.py         → modified ISO (same 418 MB)
       ↓
PPSSPP (boot & verify)
```

#### Verifikasi lossless

- **TEST.EVT roundtrip** (7,618,560 bytes): byte-identical setelah decode → encode
- **All 15,326 dialog bubbles**: substitute dengan text asli mereka → output byte-identical
- **fftpack.bin patch** (220 MB): substitusi pada 42 known offsets — semua valid
- **ISO patch** (418 MB): direct write pada offset `0x02c20000` — sector-aligned ✓

#### File mapping di fftpack.bin (42 dari 44 EVENT files)

Lengkap di `data/fftpack_event_map.json`. Highlight:
- `TEST.EVT` @ 0x00361800 (7.6 MB, dialog cerita)
- `WORLD.LZW` @ 0x00dab800 (job/spell/character/place names)
- `ATCHELP.LZW` @ 0x00d83000 (battle command tutorials)
- `EVTCHR.BIN` @ 0x00ded800 (4.4 MB, event character sprites)
- `BONUS.BIN` @ 0x00ae0000 (1.9 MB, bonus content)
- ... 37 file lainnya

#### Constraint translation yang real

| Aspek | Nilai |
|-------|-------|
| Total dialog bubbles | 15,326 |
| Avg byte per bubble (EN) | 102 bytes |
| Bubbles dengan adjacent zero buffer | 348 (2.3%) |
| Avg buffer size kalau ada | +57 bytes |
| Total event padding | 1.5 MB (tidak adjacent ke bubble) |

**Implication**: Translation ID harus phrased **compact** — target ≤ EN length per bubble.
Untuk 97% bubbles, ID text harus muat in-place. Hanya 2.3% punya stretch room.

### 8.9 Yang masih harus dikerjakan

| Step | Effort | Notes |
|------|--------|-------|
| LZW decompressor untuk HELP/WLDHELP/JOIN/SAMPLE | 3-7 hari | 4 file kompresi 0xF0 — bukan blocker (HELPMENU.OUT bisa dipakai) |
| Parse semantik control codes (color, delay) | Trial-error PPSSPP | Only needed jika translator pakai control codes baru |
| Gemini translation actual run | User action | Set GEMINI_API_KEY + run batch |
| QA test in PPSSPP | User action | Verify scene-by-scene |
| FMV subtitle (Fase 9) | 2-3 minggu | Optional polish |

**Bottleneck removed**: pointer rewriter TIDAK perlu (no global table). Encoder bisa
substitute langsung dalam slot per bubble.

### 8.10 🎉 RUNTIME CONFIRMED — TRANSLATION VISIBLE IN PPSSPP

Setelah end-to-end pipeline selesai dibangun, modified ISO **berhasil di-boot di PPSSPP**
dan opening prayer narration **muncul dengan terjemahan ID**:

> Original: `O Father, abandon not Your wayward children of Ivalice...`
>
> **Modified**: `O Bapa, abandon not Your wayward children of Ivalice...`

User konfirmasi visual via PPSSPP screen.

#### Lesson penting yang ditemukan

**Bubble kinds matter!** Opening prayer di-classify oleh parser sebagai `kind='narration'`
(bukan `kind='text'`). Initial `repack_evt` hanya handle `text` bubbles → narration di-skip
silently, walaupun tools report "applied=1, failed=0".

Fix (commit `bf50cf0`): include `{'text', 'narration', 'speaker'}` di translatable_kinds.
Block ID sekarang konsisten antara workspace builder dan repack — first narration bubble
(opening prayer) is `block_id=82`.

#### Implication untuk translation work

Distribusi bubble kinds di TEST.EVT:
- `text`: 15,326 (96.5%)
- `speaker`: 4,586 (29% — speaker name tags, biasanya gak perlu translate)
- `narration`: 13 (sangat sedikit, tapi PENTING — opening prayer, intro)
- `untranslated`: 4,479 (Japanese remnant, di-skip otomatis)

Translator harus aware kind apa yang lagi di-edit. `narration` biasanya yang
paling visible (intro/cutscene), prioritaskan di awal.

#### Confirmed working pipeline (final state)

```bash
# 1. Build workspace dari events_parsed.json
python -m psp_translate workspace build/events_parsed.json workspace/ --filter-quality

# 2. Translate (manual edit chapter_*.json atau Gemini auto)
python -m psp_translate gemini workspace/chapter_01.json workspace/chapter_01.json

# 3. Apply ke ISO
python -m psp_translate pipeline \
    --translations workspace/ \
    --original-iso games/FFT_WoTL.iso \
    --output-iso FFT_WoTL_ID.iso

# 4. Boot di PPSSPP — confirmed visible ✓
```
