# SPDX-FileCopyrightText: 2026 Leandro Garcia
# SPDX-License-Identifier: MIT
"""Trava contra duas sincronizações ao mesmo tempo (agendada e manual)."""
import contextlib
import os


class Ocupado(Exception):
    pass


@contextlib.contextmanager
def trava(caminho):
    os.makedirs(os.path.dirname(caminho), mode=0o700, exist_ok=True)
    with open(caminho, "a+") as f:
        try:
            import fcntl
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Ocupado("Já existe uma sincronização em execução.")
        except ImportError:  # Windows (não testado)
            import msvcrt
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise Ocupado("Já existe uma sincronização em execução.")
        yield
