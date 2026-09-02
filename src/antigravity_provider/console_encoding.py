"""Принудительный UTF-8 для потоков вывода.

Инструменты Hermes печатают по-русски, а консоль Windows-раннера в CI работает
в cp1252. Первый же `print` с кириллицей роняет процесс UnicodeEncodeError'ом —
падает вывод, не логика. Измерено на `scripts/verify_multi_provider_router.py`:
строка `[PASS] Чистая конфигурация...` обрывала прогон с кодом 1.

Модуль ставит UTF-8 на stdout/stderr и оставляет запасной путь на случай, когда
перекодировать поток нельзя: тогда непечатаемые символы заменяются, но процесс
продолжает работу. Вывод инструмента не должен быть причиной падения.
"""
from __future__ import annotations

import sys
from typing import Any, Iterable

__all__ = ["force_utf8_output"]


def _reconfigure(stream: Any) -> bool:
    """Перевести один поток на UTF-8. True, если получилось."""
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is None:
        return False
    for errors in ("strict", "backslashreplace"):
        try:
            reconfigure(encoding="utf-8", errors=errors)
            return True
        except Exception:
            continue
    # Поток не перекодировать (подменён, закрыт, не текстовый). Тогда хотя бы
    # снимем строгость с текущей кодировки, чтобы кириллица не роняла процесс.
    try:
        reconfigure(errors="backslashreplace")
        return True
    except Exception:
        return False


def force_utf8_output(streams: Iterable[str] = ("stdout", "stderr")) -> None:
    """Перевести стандартные потоки на UTF-8; молча пропустить недоступные.

    Вызывается один раз на старте точки входа, до первого вывода.
    """
    for name in streams:
        stream = getattr(sys, name, None)
        if stream is not None:
            _reconfigure(stream)
