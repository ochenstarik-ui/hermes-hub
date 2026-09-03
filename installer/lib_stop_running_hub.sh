#!/usr/bin/env bash
# ==============================================================================
# Hermes Hub — общая функция остановки работающего хаба (Linux/POSIX).
#
# До этого файла одна и та же функция была отдельно вписана в install-linux.sh
# и в uninstall-linux.sh — две копии, которые разошлись бы при первой же
# правке одной из них незамеченной для другой. Источник источается («source»)
# обоими скриптами и лаунчером остановки, поэтому логика одна.
#
# Использование: `source "$(dirname "$0")/lib_stop_running_hub.sh"`, затем
# вызвать `stop_running_hub`. Функция сама печатает ход дела и возвращает
# 0 (остановлен или нечего было останавливать) либо 1 (что-то осталось —
# вызывающий решает, прерывать ли из-за этого).
# ==============================================================================

stop_running_hub() {
    local pattern="antigravity_provider.router.web|hermes_hub_web_entry"
    local pids
    # Только процессы ЭТОГО пользователя и только те, что относятся к хабу.
    pids="$(pgrep -u "$(id -u)" -f "$pattern" 2>/dev/null | tr '\n' ' ')"

    if [ -z "$pids" ]; then
        echo "      Работающий хаб не найден — останавливать нечего."
        return 0
    fi

    echo "      Найдены процессы хаба: $pids"
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true

    local waited=0
    while [ "$waited" -lt 10 ]; do
        sleep 1
        waited=$((waited + 1))
        pids="$(pgrep -u "$(id -u)" -f "$pattern" 2>/dev/null | tr '\n' ' ')"
        [ -z "$pids" ] && break
    done

    if [ -n "$pids" ]; then
        echo "      Не завершились за 10 секунд, снимаю принудительно: $pids"
        # shellcheck disable=SC2086
        kill -9 $pids 2>/dev/null || true
        sleep 1
        pids="$(pgrep -u "$(id -u)" -f "$pattern" 2>/dev/null | tr '\n' ' ')"
    fi

    if [ -n "$pids" ]; then
        echo "      ⚠ Остались процессы: $pids. Снимите их вручную."
        return 1
    fi

    echo "      Хаб остановлен."
    return 0
}
