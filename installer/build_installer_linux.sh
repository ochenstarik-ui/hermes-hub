#!/usr/bin/env bash
# Собирает ОДИН самодостаточный файл dist/hermes-hub-setup.sh.
#
# Зачем: install-linux.sh читает исходники из каталога репозитория, поэтому на
# каждую машину приходилось копировать весь клон git. Здесь исходники
# упакованы внутрь самого установщика — файл переносится один и работает там,
# где git не установлен вовсе.
#
# Устройство: текстовый пролог, затем строка-маркер, затем tar.gz побайтово.
# Пролог обрезает себя по маркеру и распаковывает хвост во временный каталог.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DIST_DIR="$REPO_ROOT/dist"
OUT="$DIST_DIR/hermes-hub-setup.sh"

COMMIT="$(cd "$REPO_ROOT" && git rev-parse --short HEAD 2>/dev/null || echo 'не определён')"
echo "Сборка установщика Linux, коммит: $COMMIT"

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

# Тот же состав, что в виндовом payload, плюс installer/ — внутри него лежит
# install-linux.sh, который и выполняет установку.
for item in src launcher assets config scripts installer; do
    [ -e "$REPO_ROOT/$item" ] || continue
    cp -r "$REPO_ROOT/$item" "$STAGE/$item"
done
printf '%s' "$COMMIT" > "$STAGE/BUILD_COMMIT"

# Нормализация переводов строк — обязательный шаг, а не гигиена.
#
# Сборка идёт на Windows, где рабочая копия хранится с CRLF (core.autocrlf).
# В git объекты лежат с LF, но сборщик копирует из РАБОЧЕЙ КОПИИ, поэтому
# .gitattributes её не спасает. Установщик с  падает на первой же строке:
# "$'': command not found", а строка-маркер с  не совпадает, и пролог не
# находит границу вложенных данных. Именно так сломалась сборка 44808bd.
echo "Нормализация переводов строк..."
find "$STAGE" -type f \( -name '*.sh' -o -name '*.py' -o -name '*.yaml' -o -name '*.yml' -o -name '*.json' \) -print0     | xargs -0 -r sed -i 's/$//'

find "$STAGE" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$STAGE" -name '*.pyc' -delete 2>/dev/null || true
# Виндовые бинарники в линуксовой поставке бесполезны и весят больше мегабайта.
find "$STAGE/launcher" -name '*.exe' -delete 2>/dev/null || true

PAYLOAD="$(mktemp)"
tar -czf "$PAYLOAD" -C "$STAGE" .

mkdir -p "$DIST_DIR"
cat > "$OUT" <<'STUB'
#!/usr/bin/env bash
# Hermes Hub — самодостаточный установщик. Репозиторий и git не нужны.
#   bash hermes-hub-setup.sh
set -euo pipefail

if ! command -v tar >/dev/null 2>&1; then
    echo "Нужен tar. Установите его: apt install tar" >&2
    exit 1
fi

MARKER='__HERMES_HUB_PAYLOAD_BELOW__'
SELF="$0"
LINE="$(grep -a -n "^$MARKER\$" "$SELF" | head -1 | cut -d: -f1)"
if [ -z "${LINE:-}" ]; then
    echo "Файл повреждён: не найдена граница вложенных данных." >&2
    exit 1
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "Распаковка..."
tail -n +$((LINE + 1)) "$SELF" | tar -xzf - -C "$TMP"

if [ ! -f "$TMP/installer/install-linux.sh" ]; then
    echo "Файл повреждён: во вложенных данных нет installer/install-linux.sh." >&2
    exit 1
fi

chmod +x "$TMP/installer/install-linux.sh" 2>/dev/null || true
exec bash "$TMP/installer/install-linux.sh" "$@"
STUB

echo '__HERMES_HUB_PAYLOAD_BELOW__' >> "$OUT"
cat "$PAYLOAD" >> "$OUT"
rm -f "$PAYLOAD"
chmod +x "$OUT"

SIZE_KB=$(( $(wc -c < "$OUT") / 1024 ))
echo "Готово: $OUT (${SIZE_KB} КБ)"
