from __future__ import annotations

import ctypes


def zero_bytearray(ba: bytearray) -> None:
    try:
        for i in range(len(ba)):
            ba[i] = 0
    except Exception:
        pass


def zero_str_inplace(s: str) -> None:
    """Best-effort attempt to zero a Python str by using ctypes to overwrite its memory.

    Note: CPython does not guarantee str mutability and this is best-effort only.
    """
    try:
        addr = id(s)
        # This is extremely implementation dependent and best-effort only
        c = ctypes.cast(addr, ctypes.POINTER(ctypes.c_char * (len(s) + 1)))
        for i in range(len(s)):
            c.contents[i] = b"\x00"[0]
    except Exception:
        pass
