# TEST.EVT Format (FFT WoTL PSP)

Hasil reverse engineering file `extracted/FFTPACK_Extracted/EVENT/TEST.EVT`
(7,618,560 byte) untuk proyek translasi Indonesia. Dokumentasi ini adalah
input untuk **encoder phase (Fase 5)** dan boleh direvisi seiring temuan
baru.

## 1. File layout

```
+--------+--------------+
| 0x0000 | Event[0]     |   (selalu mulai dengan magic f2 f2 f2 f2)
| 0x2800 | Event[1]     |
| 0x7800 | Event[2]     |
|  ...   |              |
| ~0x5c0800 | Event[230] |
+--------+--------------+
```

- File terdiri dari **231 event chunks** yang masing-masing independen.
- **Tidak ada tabel pointer global** di awal file. Bytes setelah magic
  langsung berisi bytecode (opcode `f1 XX 00`, `e5 XX 00`, dst).
- Setiap event dimulai dengan magic `f2 f2 f2 f2` dan posisinya selalu
  aligned ke batas **0x800** (2048 byte / 1 sektor PSP UMD).
- Ukuran event = jarak ke event berikutnya (atau EOF untuk yang terakhir).
  Ukuran tipikal: `0x2800`, `0x5000`, `0x7800`, `0xa000`, dst — selalu
  kelipatan `0x800`.
- Cara loader engine mendeteksi: lookup tabel di executable (BOOT.BIN /
  EBOOT.BIN) yang menyimpan offset+size tiap event. Tabel itu belum
  diparse di proyek ini; untuk extractor/encoder cukup pakai magic scan.

## 2. Event chunk layout

```
offset within event:
  0x000        magic = f2 f2 f2 f2
  0x004-0x7ff  common bytecode prologue (~ 201/231 event identik)
  0x800-...    unique event script (campuran bytecode + dialog bubbles)
  ...          zero padding hingga next 0x800 alignment
```

- **Common prologue (0x800 byte pertama)** sama untuk 201 dari 231 event.
  Kemungkinan: init opcode/setup yang umum dipanggil semua event. Konten
  prologue mengandung byte `d1`, `f8`, `fa`, `fe` — terlihat seperti
  message bank entries yang di-share antar event (mungkin generic
  battle/UI text).
- **Trailing padding** selalu byte `0x00`, padding ke kelipatan `0x800`.
- Setiap event boleh punya banyak dialog bubble. Bubble di event ini
  rata-rata ~100 bubble per event yang besar (event 6 punya ratusan).

## 3. Dialog bubble framing

Dialog dipisahkan oleh terminator **`0xFE`** (end-of-string). Tiap chunk
antara dua `0xFE` adalah satu "bubble" (atau message bank entry untuk
chunk yang isinya Japanese leftover).

### 3a. Speaker bubble (English dialog)

```
... e3 08  <speaker_name_bytes>  f8 e3  <dialog_bytes>  fe
        \__________ name __________/      \___ dialog ___/
```

Contoh (offset 0x5926):
```
e3 08 13 36 53 4c 4a 2b 37 f8 e3 21 38 37 95 18 95 36 38 35 33 32 36 28 95 ... fe
              "Knight"           "But I suppose ..."
```

### 3b. Narration / prayer bubble

Ditandai dengan marker `0xE2 0x02` di tengah/awal chunk (bukan speaker
tag). Contoh prayer pembuka di event 1:
```
... e2 02 0f 24 37 2b 28 35  e2 06 da 74  e2 02 95 24 25 24 31 27 32 31 ... fe
       "Father"              ", "          " abandon ..."
```

`0xE2` adalah opcode parameterized 2-byte. Variant yang ditemukan:
- `e2 02` = paragraph break (PRAYER style, italic narration?)
- `e2 06` = sub-paragraph (sering tepat sebelum punctuation seperti comma)
- `e2 01`, `e2 03`, `e2 05`, `e2 0a`, `e2 0f`, `e2 1e`, `e2 3c`, `e2 ff` —
  banyak variant, kemungkinan kontrol formatting (color tag, delay, font
  effect). Semantik tepat belum dipastikan.

### 3c. Untranslated chunk (Japanese leftover)

Ada ~4,479 chunk yang didominasi prefix `d1`-`d9` (kemungkinan glyph
tabel multi-byte untuk kanji/kana yang tidak diterjemahkan saat WoTL
diport ke EN). Parser meng-flag chunk sebagai `kind: "untranslated"`
kalau ≥30% body-nya byte di range `0xD1`-`0xD9`.

Untuk **fase translasi Indonesia**, chunk ini KEMUNGKINAN tidak perlu
diterjemahkan (tidak muncul in-game di versi EN) — perlu verifikasi
dengan PPSSPP.

## 4. Control codes (terverifikasi)

| Byte(s)     | Semantik                                          | Catatan |
|-------------|--------------------------------------------------|---------|
| `f2 f2 f2 f2` | Magic header tiap event chunk                 | Selalu di offset aligned 0x800 |
| `00`         | Padding (di-skip oleh decoder)                  | Trailing pad event, juga inline |
| `fe`         | End-of-string / end-of-bubble                   | Terminator wajib tiap bubble |
| `f8`         | Soft line break dalam bubble (newline)          | Wrap dialog ke baris berikut |
| `e0`         | Placeholder nama player (Ramza)                 | Diganti runtime |
| `e3 08`      | Speaker tag start (diikuti nama, lalu `f8 e3`)  | Pola: `e3 08 NAME f8 e3 DIALOG fe` |
| `e2 02`      | Paragraph marker (narration / prayer style)     | Dipakai opening prayer |
| `e2 06`      | Sub-paragraph (sering sebelum punctuation)      | Mungkin "small caps" / italics |
| `da 74`      | "," (comma)                                     | Multi-byte glyph |
| `da 68`      | "—" (em dash)                                   | Multi-byte glyph |
| `da 65`      | "ú"                                             | Untuk nama Spanish-style |
| `d1 1d`      | "-" (hyphen)                                    | Multi-byte glyph |
| `d1 XX`      | Multi-byte glyph prefix (XX = sub-glyph)        | Sangat sering, butuh tabel lengkap |
| `d2`-`d9 XX` | Multi-byte glyph prefix (kelompok lain)         | Kemungkinan kanji/kana di Japanese build |

## 5. Opcode (bytecode region)

Format umum opcode: **`f1 XX 00`** (3-byte instruction dengan parameter
LE byte XX). Distribusi top frequency di bytecode region (di luar bubble):

| Opcode          | Count | Hipotesis fungsi |
|-----------------|-------|------------------|
| `f1 08 00`      | 2,352 | Kemungkinan WAIT / CALL pendek |
| `f1 0a 00`      | 2,274 | Common branching |
| `f1 1e 00`      | 1,302 | Setup scene (sering di prolog) |
| `f1 14 00`      |   968 | |
| `f1 3c 00`      |   938 | |
| `f1 06 00`      |   796 | |
| `f1 02 00`      |   584 | |
| `f1 10 00`      |   577 | |
| `e5 01`         | 4,887 | Event flag set (boolean) |
| `e5 04`         | 1,814 | Event flag query |
| `e5 38/36/34/43` | ~2,000 | Variant flag/state ops |

Catatan: parameter `f1 XX 00` selalu byte ketiga = `0x00`, mengindikasikan
XX adalah LE16 dengan high byte nol — yaitu byte index 0-255. Bisa juga
diinterpretasi sebagai 1-byte opcode dengan padding.

`0xFA` dan `0xFD` muncul ~22k dan ~306 kali tapi terutama di chunk
untranslated; kemungkinan glyph prefix tambahan untuk Japanese, bukan
opcode di English dialog flow.

## 6. Verifikasi & batasan

**Sudah diverifikasi:**
- 231 event chunks ter-deteksi, semua aligned 0x800.
- Total 24,404 bubble ter-ekstrak (15,326 text + 4,586 speaker + 4,479
  untranslated + 13 narration).
- Opening prayer "Father, abandon not..." berhasil di-decode dari event 1
  offset `0x58c0` (verified literal match).
- Speaker yang paling sering: `<e0>` (Ramza placeholder, 607x), Onion
  Knight (420), Argath (271), Delita (196).

**Masih unclear (TODO Fase 5+):**
1. Semantik tepat `e2 XX` (kemungkinan color/effect/delay).
2. Mapping lengkap `d1 XX`, `d2 XX`, ... — banyak glyph yang masih
   `<xx>` di decoder. Butuh ekstrak dari FONT.BIN.
3. Apakah engine PSP punya pointer table di EBOOT.BIN yang reference
   offset event di TEST.EVT? (Kalau ya, encoder harus update juga.)
4. Constraint padding: apakah event SIZE harus tetap sama setelah edit?
   Hipotesis: ya — `f2f2f2f2` di-load per sektor, jadi setiap event harus
   tetap kelipatan 0x800 byte. Encoder harus repad dengan `0x00` sampai
   alignment terpenuhi.
5. Apakah ada checksum/CRC per event atau global? Belum ditemukan.

## 7. Tools

- `psp_translate/evt/header.py <evt> --output struct.json` — parse layout level
  file (offset & size tiap event).
- `psp_translate/evt/parser.py <evt> <struct.json> --output parsed.json
  [--event-id N]` — extract bubbles per event.
- `psp_translate/codec/decode.py` — decoder reused sebagai library oleh parser.
- `data/char_table.json` — mapping byte → glyph (single + multi-byte).
