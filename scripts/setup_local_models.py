"""Прописать локальные модели в Hermes Hub и назначить им роли.

Запускать на той машине, где работает хаб:

    python3 scripts/setup_local_models.py            # показать, что будет сделано
    python3 scripts/setup_local_models.py --yes      # применить

Скрипт ДОПОЛНЯЕТ конфигурацию, а не переписывает: чужие профили, роли и
цепочки сохраняются. Запись атомарная, повторный запуск ничего не ломает.

Идентификаторы моделей не выдумываются — они спрашиваются у самих серверов
через /v1/models. Сервер не ответил — профиль не трогаем и говорим об этом.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# Замысел владельца: тяжёлая 27B на разработку, лёгкая 4B на служебные роли.
LOCAL_PLAN = [
    {
        "profile_id": "local-1",
        "base_url": "http://127.0.0.1:8081/v1",
        "title": "Qwen3.8-27B (тяжёлый локальный кодер)",
        "roles": ["developer-1"],
    },
    {
        "profile_id": "local-2",
        "base_url": "http://127.0.0.1:8082/v1",
        "title": "Qwen3-4B (служебная модель)",
        "roles": ["cost-controller", "dependency-agent", "tech-writer", "tester"],
    },
]


def ask_models(base_url: str, timeout: float = 6.0):
    """Спросить у сервера список моделей. Ничего не выдумывать."""
    url = base_url.rstrip("/") + "/models"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
        return None, f"{type(exc).__name__}: {exc}"
    ids = [m["id"] for m in payload.get("data", []) if isinstance(m, dict) and m.get("id")]
    return ids, None


# Соответствие для СТАРЫХ сборок, где тринадцати ролей ещё нет. Служебные
# роли там отсутствуют как понятие, поэтому 4B назначается на быстрые роли —
# это ближайшее по смыслу, а не подмена.
LEGACY_FALLBACK = {
    "developer-1": "coder-primary",
    "developer-2": "coder-secondary",
    "code-reviewer": "reviewer",
    "researcher": "research",
    "tester": "fast",
    "tech-writer": "fast",
    "cost-controller": None,
    "dependency-agent": None,
}


def resolve_role(name: str, known_roles) -> str | None:
    """Привести роль к имени, которое понимает установленная сборка."""
    try:
        from antigravity_provider.router.role_registry import RoleRegistry

        canon = RoleRegistry.resolve_canonical_role(name)
    except Exception:
        canon = name

    if canon in known_roles:
        return canon
    # Сборка старая: пробуем ближайшую по смыслу роль из шести.
    legacy = LEGACY_FALLBACK.get(canon, canon)
    if legacy and legacy in known_roles:
        return legacy
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--yes", action="store_true", help="применить изменения")
    args = parser.parse_args()

    from antigravity_provider.paths import get_router_profiles_path
    from antigravity_provider.router.router_config import load_router_config, save_router_config

    target = get_router_profiles_path()
    print(f"Файл конфигурации : {target}")
    print(f"  существует      : {'да' if target.is_file() else 'нет, будет создан'}")
    if os.environ.get("HERMES_HOME"):
        print(f"  HERMES_HOME     : {os.environ['HERMES_HOME']}")
    print()

    config = load_router_config()
    known_roles = set(config.roles)
    print(f"Ролей в конфигурации: {len(known_roles)}")
    print()

    planned = []
    for item in LOCAL_PLAN:
        pid = item["profile_id"]
        models, err = ask_models(item["base_url"])
        if err:
            print(f"  {pid}: сервер {item['base_url']} не ответил — {err}")
            print("        профиль не трогаю; запустите сервер и повторите")
            continue

        roles_ok, roles_missing = [], []
        for r in item["roles"]:
            resolved = resolve_role(r, known_roles)
            if resolved and resolved not in roles_ok:
                roles_ok.append(resolved)
            elif not resolved:
                roles_missing.append(r)

        print(f"  {pid}: {item['title']}")
        print(f"        адрес   : {item['base_url']}")
        print(f"        моделей : {len(models)} -> {', '.join(m.split('/')[-1] for m in models)}")
        print(f"        роли    : {', '.join(roles_ok) if roles_ok else '(нет подходящих)'}")
        if roles_missing:
            print(f"        пропуск : {', '.join(roles_missing)} — таких ролей в этой сборке нет")
        planned.append({**item, "models": models, "roles_ok": roles_ok})

    if not planned:
        print("\nНечего применять.")
        return 1

    if not args.yes:
        print("\nПоказан предпросмотр. Чтобы применить, повторите с --yes")
        return 0

    from antigravity_provider.router.router_config import RouterProfileConfig

    for item in planned:
        pid = item["profile_id"]
        existing = config.get_profile(pid)
        if existing is None:
            config.profiles[pid] = RouterProfileConfig(
                profile_id=pid,
                provider="local",
                account_id=pid,
                capabilities=["coding", "reasoning", "fast", "research"],
                preferred_models=list(item["models"]),
                custom_base_url=item["base_url"],
                # У обоих серверов --parallel 1: один запрос за раз.
                # Больше единицы означает очередь и лавину таймаутов.
                max_concurrency=1,
            )
        else:
            existing.custom_base_url = item["base_url"]
            existing.preferred_models = list(item["models"])
            existing.max_concurrency = 1
            existing.enabled = True

        # Профиль ставится ПОСЛЕДНИМ в цепочке роли: локальная модель бесплатна
        # и не исчерпывается, поэтому она хороший последний рубеж, когда платные
        # квоты кончились. Существующий порядок при этом не переставляется.
        for role_id in item["roles_ok"]:
            chain = list(config.roles[role_id].preferred_chain)
            if pid not in chain:
                chain.append(pid)
                config.roles[role_id].preferred_chain = chain

    save_router_config(config)
    print(f"\nГотово: {target}")
    print("\nИтоговые цепочки затронутых ролей:")
    fresh = load_router_config()
    for item in planned:
        for role_id in item["roles_ok"]:
            print(f"  {role_id:20} {list(fresh.roles[role_id].preferred_chain)}")
    print("\nПерезапустите хаб, чтобы он перечитал конфигурацию.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
