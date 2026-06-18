"""Logging & pewarnaan output terminal."""


class C:
    """Kode warna ANSI untuk terminal."""
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    RESET = "\033[0m"


def info(msg):
    print(f"{C.CYAN}[INFO]{C.RESET}  {msg}")


def ok(msg):
    print(f"{C.GREEN}[OK]{C.RESET}    {msg}")


def warn(msg):
    print(f"{C.YELLOW}[WARN]{C.RESET}  {msg}")


def err(msg):
    print(f"{C.RED}[ERROR]{C.RESET} {msg}")


def header(msg):
    bar = "=" * 60
    print(f"\n{C.BOLD}{C.BLUE}{bar}{C.RESET}")
    print(f"{C.BOLD}  {msg}{C.RESET}")
    print(f"{C.BOLD}{C.BLUE}{bar}{C.RESET}")


def step(n, msg):
    print(f"\n{C.BOLD}{C.YELLOW}[STEP {n}]{C.RESET} {msg}")


def item(msg):
    """Cetak baris item dengan checkmark hijau."""
    print(f"  {C.GREEN}\u2713{C.RESET} {msg}")
