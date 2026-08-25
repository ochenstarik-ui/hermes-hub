"""Открыть веб-хаб в домашнюю сеть: привязка к 0.0.0.0 плюс обязательный токен.

    python3 scripts/enable_lan_access.py              # показать, что будет сделано
    python3 scripts/enable_lan_access.py --yes        # применить
    python3 scripts/enable_lan_access.py --yes --rotate   # сменить токен

Почему подтверждение обязательно. Каталог берётся из HERMES_HOME, а эта
переменная часто задана в окружении незаметно для запускающего. При отладке
скрипт из-за этого записал настройки не туда, куда предполагалось, и привязал
к сети не тот хаб. Поэтому цель печатается всегда, а изменение требует --yes.

Настройки ДОПОЛНЯЮТСЯ, а не переписываются: рядом лежат тема, интервал
обновления квот и параметры маршрутизации. Запись атомарная.
"""
import json
import os
import secrets
import sys
from pathlib import Path


def main() -> int:
    apply = "--yes" in sys.argv
    rotate = "--rotate" in sys.argv
    env_home = os.environ.get("HERMES_HOME")
    home = Path(env_home) if env_home else (Path.home() / ".hermes")
    target = home / "hub_settings.json"

    print(f"Каталог Hermes : {home}")
    print(f"  источник     : {'переменная HERMES_HOME' if env_home else 'по умолчанию ~/.hermes'}")
    print(f"Файл настроек  : {target}")
    print(f"  существует   : {'да' if target.exists() else 'нет, будет создан'}")

    data = {}
    if target.exists():
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except ValueError:
            print(f"\nОТКАЗ: {target} повреждён. Разберитесь вручную — перезаписывать не буду.")
            return 1

    existing = None if rotate else data.get("web_api_token")
    keep = sorted(k for k in data if not k.startswith("web_api"))
    print(f"Будут сохранены: {', '.join(keep) if keep else '(файл пуст)'}")
    if rotate:
        note = "БУДЕТ ЗАМЕНЁН — прежний перестанет действовать"
    elif existing:
        note = "уже задан, оставляю прежний"
    else:
        note = "будет создан новый"
    print(f"Токен          : {note}")

    if not apply:
        print("\nПоказан предпросмотр. Чтобы применить, повторите с --yes")
        return 0

    token = existing or secrets.token_urlsafe(32)
    data["web_api_host"] = "0.0.0.0"
    data["web_api_token"] = token
    data.setdefault("web_api_port", 5800)

    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)

    print(f"\nГотово: {target}")
    print("\nТОКЕН — вставить в «Настройки» в интерфейсе:")
    print(f"    {token}")
    print("\nДальше: перезапустить хаб, затем открыть http://<адрес-сервера>:5800")
    print("Токен хранится в этом файле; в снапшот и в /api/settings он не попадает.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
