# Format file .LZW FFT WoTL PSP

## Penemuan utama

File `.LZW` di FFT WoTL **TIDAK SEMUA terkompresi** — meskipun namanya.

**3 file plain text** (extractable langsung):
- `WORLD.LZW` (81.8% readable) — semua nama: job, weapon, spell, character, place
- `ATCHELP.LZW` (68.9% readable) — help/tutorial text battle commands
- `OPEN.LZW` (17.9% partial) — character name list

**4 file masih compressed** (perlu decompressor):
- `HELP.LZW` (8.6% readable) — dominant byte 0xF0
- `WLDHELP.LZW` (8.1% readable) — dominant byte 0xF0
- `JOIN.LZW` (8.7% readable) — header pointer ada yang invalid
- `SAMPLE.LZW` (6.0% readable) — uncertain content

## Struktur file plain-text .LZW

```
+----------------------+
| Header               |  Offset 0x00 - 0x7F (128 bytes)
| 32 × LE32 pointers   |  Setiap pointer = offset RELATIF ke data section
+----------------------+
| Data section         |  Offset 0x80 sampai EOF
| 0xFE-terminated      |
| strings concatenated |
+----------------------+
```

### Header

- Lebar fixed: **128 bytes** (32 entries × 4 bytes LE32)
- Setiap entry = byte offset relatif terhadap awal data section
- Entries 0-6 biasanya pointer ke offset 0-6 di data section → entry kosong/sentinel
  (data section dimulai dengan beberapa byte 0xFE sebagai padding)
- Entries 7+ menunjuk ke chunk berisi sub-strings nyata

### Data section

- Dimulai di offset 0x80
- Berisi string-string yang dipisah dengan byte **0xFE**
- Setiap "chunk" antara `pointer[i]` dan `pointer[i+1]` bisa berisi banyak sub-string
- Sub-string dalam satu chunk biasanya 1 kategori (mis. semua weapon names)
- Encoding karakter sama dengan TEST.EVT (lihat `char_table.json`)

### Contoh chunking di WORLD.LZW

| Entry | Konten | Jumlah sub-strings |
|-------|--------|-------------------|
| 0-5 | sentinel/kosong | — |
| 6 | Job names (Squire, Holy Knight, ...) | 160 |
| 7 | Weapon names (Dagger, Mythril Knife, ...) | 313 |
| 8 | Character names round 1 (Ramza, Delita, ...) | 1011 |
| 9 | Character names round 2 (sama persis dengan #8) | 1011 |
| 12 | Side quest titles (Salvage of the Highwind, ...) | 96 |
| 14 | Spell names (Cure, Fire, Holy, ...) | 505 |
| 15 | Gil (uang) + zodiac names | 69 |
| 16 | Chronicle headings | 66 |
| 18 | Place names (Lesalia, Riovanes Castle, ...) | 43 |
| 20 | UI menu (Move/Party Roster/Chronicle/Tutorial/...) | 1 (big) |
| 21 | Map location names | 115 |
| 22 | Battle commands | 110 |
| 23 | Rumors/news headlines | 326 |
| 25 | Quest names (The Corpse Brigade, ...) | 147 |
| 31 | Quest descriptions | 97 |

## File compressed (.LZW with 0xF0)

Untuk HELP, WLDHELP, JOIN, SAMPLE — kompresi pakai 0xF0 sebagai control byte.

Karakteristik:
- Byte 0xF0 muncul SANGAT sering (~10-15% dari semua byte)
- Distance antar 0xF0 mostly 3-4 byte (= sequence pattern `<f0> <code> <literal>`)
- 127 unique byte values muncul setelah 0xF0
- Distribusi byte-after-0xF0 mendekati uniform → bukan literal byte tapi index ke dictionary

**Hipotesis format**: dictionary-based back-reference compression
- `0xF0 XX` = expand entry XX dari dictionary
- Literal bytes (0x00-0xEF, 0xF1-0xFF) di-output as-is
- Dictionary mungkin dibangun runtime (LZW-style) atau static (in-game ROM/EBOOT.BIN)

**Belum di-implement**. Workaround:
- HELP.LZW kemungkinan duplikat dari `HELPMENU.OUT` (byte distribution identical)
- Bisa pakai HELPMENU.OUT instead untuk extract konten

## Catatan untuk Phase 5 (Encoder)

Saat repacking file .LZW plain-text:
1. Update pointer table dengan offset baru (kalau panjang string berubah)
2. Pastikan semua sub-string masih dipisah dengan 0xFE
3. Jaga ukuran file (untuk amann, padding ke ukuran original)
4. Test di PPSSPP — text overflow kemungkinan masalah utama

Konten yang **TIDAK BOLEH ditranslate** (per aturan user — lihat `../TASK/TODO_PLAN.md`):
- Semua entry di `WORLD.LZW` (proper nouns kategorinya jelas)
- Character names di `OPEN.LZW`
- Job/spell/item names di mana pun ada
- Honorifik (Lord, Lady, Sir, dll)

Yang **BISA ditranslate**:
- `ATCHELP.LZW` entry 19 (battle command descriptions)
- Help/tutorial text di mana pun yang readable
