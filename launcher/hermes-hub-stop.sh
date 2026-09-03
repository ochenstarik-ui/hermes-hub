#!/usr/bin/env bash
# ==============================================================================
# Hermes Hub — Stop (Linux)
#
# На Windows фоновый сервер запускается из HermesHubWeb.exe, который держит
# значок в системном трее — оттуда «Exit» останавливает процесс. На Linux
# сервер стартует через nohup и остаётся в фоне после закрытия окна браузера
# (так и задумано: не переустанавливать при каждом перезапуске окна), но
# остановить его после этого было решительно нечем — ни кнопки в интерфейсе
# (её нет ни на одной платформе), ни трея, ни пункта меню. Только терминал и
# pkill вручную, либо переустановка/удаление, которые останавливают хаб
# только как побочный эффект.
#
# Этот скрипт — тот недостающий эквивалент «Exit из трея»: доступен из меню
# приложений через собственный .desktop-пункт, использует ту же проверенную
# функцию остановки, что installer/install-linux.sh и uninstall-linux.sh.
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Устанавливается рядом (в ~/.hermes/bin) install-linux.sh — оттуда и берём
# общую функцию. Если скрипт запущен не из установленного места (например,
# прямо из репозитория), ищем installer/ на уровень выше.
LIB=""
for candidate in \
    "$SCRIPT_DIR/lib_stop_running_hub.sh" \
    "$SCRIPT_DIR/../installer/lib_stop_running_hub.sh"
do
    if [ -f "$candidate" ]; then
        LIB="$candidate"
        break
    fi
done

if [ -z "$LIB" ]; then
    echo "❌ Не найдена installer/lib_stop_running_hub.sh — переустановите Hermes Hub." >&2
    exit 1
fi

# shellcheck source=../installer/lib_stop_running_hub.sh
. "$LIB"

echo "Останавливаю Hermes Hub..."
if stop_running_hub; then
    exit 0
fi
exit 1
