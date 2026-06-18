"""Extract file dari ISO PSP ke folder."""

import json
import hashlib
import datetime
from pathlib import Path

from . import iso9660
from ..utils import logger as log
from ..utils.constants import SYSTEM_AREA_SIZE, SECTOR_SIZE


def extract_iso(iso_path, output_dir) -> bool:
    """
    Extract semua file dari ISO PSP ke folder output.
    Menyimpan system area & metadata untuk keperluan repack.
    """
    log.header("EXTRACT ISO")
    iso_path = Path(iso_path)
    output_dir = Path(output_dir)

    if not iso_path.exists():
        log.err(f"File tidak ditemukan: {iso_path}")
        return False

    output_dir.mkdir(parents=True, exist_ok=True)
    log.info(f"Membuka: {iso_path.name}")
    log.info(f"Output : {output_dir}")

    with open(iso_path, 'rb') as f:
        # Simpan system area asli (boot sector) untuk repack nanti
        system_area = f.read(SYSTEM_AREA_SIZE)
        (output_dir / '_system_area.bin').write_bytes(system_area)
        log.ok(f"System area disimpan ({len(system_area):,} bytes)")

        try:
            pvd = iso9660.parse_pvd(f)
        except ValueError as e:
            log.err(str(e))
            return False
        log.ok(f"Volume: '{pvd['volume_name']}' | Root LBA: {pvd['root_dir_lba']}")

        log.step(1, "Scanning direktori...")
        entries = iso9660.parse_directory(
            f, pvd['root_dir_lba'], pvd['root_dir_size'], ''
        )
        log.info(f"Ditemukan {len(entries)} file")

        log.step(2, "Mengekstrak file...")
        count = 0
        for entry in entries:
            rel = entry['path'].lstrip('/\\')
            dest = output_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)

            f.seek(entry['lba'] * SECTOR_SIZE)
            dest.write_bytes(f.read(entry['size']))
            count += 1
            log.item(f"{rel} ({entry['size']:,} bytes)")

    _write_meta(iso_path, output_dir, pvd['volume_name'], count)
    log.ok(f"\nSelesai! {count} file diekstrak ke: {output_dir}")
    return True


def _write_meta(iso_path: Path, output_dir: Path, volume_name: str, count: int):
    """Tulis metadata ISO ke _meta.json."""
    meta = {
        'original_iso': str(iso_path.resolve()),
        'volume_name': volume_name,
        'extracted_at': datetime.datetime.now().isoformat(),
        'iso_size_bytes': iso_path.stat().st_size,
        'iso_sha256': hashlib.sha256(iso_path.read_bytes()).hexdigest(),
        'file_count': count,
    }
    (output_dir / '_meta.json').write_text(
        json.dumps(meta, indent=2, ensure_ascii=False)
    )
