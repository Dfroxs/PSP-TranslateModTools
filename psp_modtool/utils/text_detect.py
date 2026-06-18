"""Helper untuk deteksi & ekstraksi teks dari file game."""

import re

from .constants import PLAIN_TEXT_EXTENSIONS


def detect_encoding(data: bytes) -> str:
    """Deteksi encoding sederhana berdasarkan BOM dan uji decode."""
    if data[:3] == b'\xef\xbb\xbf':
        return 'utf-8-sig'
    if data[:2] in (b'\xff\xfe', b'\xfe\xff'):
        return 'utf-16'
    try:
        data.decode('utf-8')
        return 'utf-8'
    except UnicodeDecodeError:
        return 'latin-1'


def is_plain_text_file(ext: str) -> bool:
    """Apakah ekstensi ini file teks murni yang dibaca per-baris?"""
    return ext.lower() in PLAIN_TEXT_EXTENSIONS


def extract_ascii_strings(data: bytes, min_len: int = 5):
    """
    Ekstrak rangkaian byte ASCII printable dari data biner.
    Mengembalikan list dict {offset, text, length}.
    """
    results = []
    pattern = re.compile(rb'[\x20-\x7E]{' + str(min_len).encode() + rb',}')
    for m in pattern.finditer(data):
        text = m.group().decode('ascii', errors='replace')
        results.append({
            'offset': m.start(),
            'text': text,
            'length': len(text),
        })
    return results


_VOWELS = frozenset('aeiouAEIOU')

# Pola yang menandakan string BUKAN teks game (path, konstanta, dll)
_SKIP_PATTERNS = [
    re.compile(r'^[A-Za-z]:\\'),       # Windows path
    re.compile(r'^/[a-z]+/'),          # Unix path
    re.compile(r'^\w+\.\w{2,4}$'),     # Nama file
    re.compile(r'^0x[0-9a-fA-F]+$'),   # Hex literal
    re.compile(r'^\d+$'),              # Angka murni
    re.compile(r'^[A-Z_]{5,}$'),       # KONSTANTA
]

_NON_LETTER_RUN = re.compile(r'[^A-Za-z ]{3,}')
_CAMEL_CASE = re.compile(r'[a-z][A-Z]')

# Bentuk "kata wajar" untuk token tanpa spasi. Lowercase-only sengaja tidak
# diizinkan: kebanyakan teks UI/dialog game PSP berbentuk Titlecase atau
# ALLCAPS, sementara lowercase-tanpa-spasi cenderung identifier atau noise.
_WORD_SHAPES = re.compile(
    r'^(?:'
    r'[A-Z][a-z]{2,}'      # Titlecase  : Save, Infinity, Ramza
    r'|[A-Z]{2,}'          # ALLCAPS    : HP, MAGIC
    r')$'
)


def looks_like_game_text(text: str) -> bool:
    """
    Heuristik: apakah string kemungkinan teks game (dialog/menu/UI)?
    Menyaring path, konstanta, identifier kode, dan noise biner yang
    kebetulan printable.
    """
    if not text:
        return False

    n = len(text)
    letters = sum(c.isalpha() for c in text)

    # 1) Mayoritas karakter harus huruf (buang "D%%0l", "B$mB ")
    if letters / n < 0.6:
        return False

    # 2) Huruf + spasi harus dominan (buang noise tanda baca acak)
    if (letters + text.count(' ')) / n < 0.75:
        return False

    # 3) Teks asli punya vokal; noise random biasanya tidak.
    #    Lewati untuk string < 4 huruf agar "HP", "MP", "FFT" tetap lolos.
    if letters >= 4 and sum(c in _VOWELS for c in text) / letters < 0.2:
        return False

    # 4) Hindari run simbol panjang ("$#@g", "%%0l")
    if _NON_LETTER_RUN.search(text):
        return False

    for pat in _SKIP_PATTERNS:
        if pat.match(text):
            return False

    stripped = text.strip()
    has_space = ' ' in stripped

    # 5) Identifier camelCase / PascalCase ("sceAudio", "UserSbrk")
    if not has_space and _CAMEL_CASE.search(text):
        return False

    # 6) Token semua-lowercase tanpa spasi ≥ 6 huruf → identifier C
    #    ("vfprintf", "defghijk"); kata Inggris asli umumnya diawali kapital
    #    dalam teks game atau muncul bersama spasi.
    if not has_space and len(text) >= 6 and text.isalpha() and text.islower():
        return False

    # 7) String panjang tanpa spasi biasanya identifier teknis
    if len(text) > 10 and not has_space:
        return False

    # 8) Tanpa spasi → diversitas karakter harus tinggi. Data biner yang
    #    kebetulan printable sering berisi byte berulang ("UUUVU%VZ",
    #    "effff", "wwwww"); kata Inggris asli ~0.7+ karakter unik.
    if not has_space and n >= 5 and len(set(text)) / n < 0.7:
        return False

    # 9) Bentuk kata wajar.
    #    - Tanpa spasi internal: seluruh string (setelah strip) harus
    #      cocok sebagai Titlecase/ALLCAPS. Membuang "GSSE5", "PUEuww",
    #      "Tueff", "Oqogw" dan sejenisnya.
    #    - Dengan spasi internal: minimal satu token huruf harus berbentuk
    #      kata wajar. Membuang "eu& VVvffDU", "AaI 2", "G hIsI".
    if not has_space:
        if not _WORD_SHAPES.match(stripped):
            return False
    else:
        tokens = re.findall(r'[A-Za-z]+', text)
        if not any(_WORD_SHAPES.match(t) for t in tokens):
            return False

    return True
