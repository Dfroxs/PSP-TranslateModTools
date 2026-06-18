"""Konstanta untuk format ISO 9660 / UMD PSP dan klasifikasi file."""

# --- Layout sektor ISO 9660 ---
SECTOR_SIZE = 2048
SYSTEM_AREA_SECTORS = 16
SYSTEM_AREA_SIZE = SYSTEM_AREA_SECTORS * SECTOR_SIZE  # 32768 bytes
PVD_SECTOR = 16                 # Primary Volume Descriptor
VDST_SECTOR = 17                # Volume Descriptor Set Terminator
ROOT_DIR_SECTOR = 18            # Root directory (saat repack)
FIRST_FILE_SECTOR = 19         # Sektor pertama untuk data file

ISO_MAGIC = b'CD001'
DIR_RECORD_MIN_LEN = 33         # Panjang minimum directory record (tanpa nama)

# --- Magic bytes pengenal format file ---
FILE_SIGNATURES = {
    b'PK\x03\x04': 'ZIP/JAR',
    b'\x89PNG': 'PNG Image',
    b'RIFF': 'WAV/AVI',
    b'OggS': 'OGG Audio',
    b'RIFFAT3': 'AT3 Audio (PSP)',
    b'PBPX': 'EBOOT.PBP',
    b'\x7fELF': 'ELF Binary',
    b'\x00PSP': 'PSP Header',
}

# --- File teks murni: dibaca per-baris ---
PLAIN_TEXT_EXTENSIONS = {
    '.txt', '.xml', '.ini', '.cfg', '.json',
    '.csv', '.script', '.msg', '.lua', '.html',
}

# --- File yang jelas biner / media: di-skip saat scan ---
BINARY_SKIP_EXTENSIONS = {
    '.png', '.jpg', '.jpeg', '.bmp', '.tga', '.gif',
    '.mp3', '.ogg', '.wav', '.at3', '.pmf', '.mp4',
    '.elf', '.prx', '.pbp', '.zip', '.gz',
}

# --- File biner yang mungkin berisi string: di-scan ASCII ---
BINARY_SCAN_EXTENSIONS = {
    '.bin', '.dat', '.pak', '.arc', '.str', '.tbl', '.lst',
}
