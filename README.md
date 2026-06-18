# PSP Mod Tool

Tool Python untuk **extract, scan, terjemahkan, dan repack** file ISO game PSP.
Berguna untuk lokalisasi bahasa game (misalnya English → Indonesia).

## Struktur Proyek

```
psp_mod_tool/
├── main.py                  # Entry point
├── pyproject.toml           # Konfigurasi package
├── README.md
└── psp_modtool/             # Package utama
    ├── __init__.py
    ├── cli.py               # Antarmuka command-line
    ├── core/                # Logika inti
    │   ├── iso9660.py       # Parser/writer format ISO 9660
    │   ├── extractor.py     # Bongkar ISO → folder
    │   ├── scanner.py       # Deteksi teks dalam file
    │   ├── translator.py    # Terapkan terjemahan
    │   ├── repacker.py      # Folder → ISO
    │   └── pipeline.py      # Alur lengkap interaktif
    └── utils/               # Pendukung
        ├── constants.py     # Konstanta ISO & klasifikasi file
        ├── logger.py        # Output terminal berwarna
        └── text_detect.py   # Deteksi & ekstraksi string
```

## Cara Pakai

### Per langkah

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

Menjalankan semua langkah dan berhenti di tengah agar kamu bisa
mengisi terjemahan, lalu lanjut otomatis.

### Sebagai package terpasang

```bash
pip install -e .
psp-modtool extract game.iso ./extracted
```

## Format strings.json

```json
{
  "files": [
    {
      "path": "DATA/MENU.BIN",
      "type": "binary",
      "strings": [
        {
          "offset": 1024,
          "original": "Start Game",
          "translation": "Mulai Permainan"
        }
      ]
    }
  ]
}
```

Isi field `translation`. Kosongkan untuk string yang tidak ingin diubah.

## Catatan & Keterbatasan

- **File biner**: terjemahan tidak boleh lebih panjang dari teks asli
  (otomatis dipotong/di-pad agar offset tidak bergeser).
- **Backup**: file `.bak` dibuat otomatis sebelum diubah.
- **Encoding khusus** (Shift-JIS untuk game Jepang) perlu hex editor manual.
- **Format custom**: file `.pak`/`.arc` tiap game berbeda; tool men-scan
  string ASCII di dalamnya, tapi pointer internal mungkin perlu disesuaikan.
- Selalu **test di PPSSPP** setelah repack.

## Lisensi

MIT
