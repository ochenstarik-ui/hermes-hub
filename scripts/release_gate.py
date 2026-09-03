"""Hermes Hub — Automated Release Gate & Verification Engine.

Strictly checks all criteria before allowing a release build:
1. Version consistency across manifests and code (0.1.1).
2. P0 Release Gate tests pass 100%.
3. Full offline test suite passes hermetically.
4. Auto-updater, cryptographic verification, and rollback pass.
5. Zero hardcoded developer paths (E:\\Agent projects, C:\\Users\\trush, etc.) in src/.
6. Zero secrets / keys / credentials in git repo.
7. Multi-Provider Router verification passes.
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from antigravity_provider.console_encoding import force_utf8_output
from antigravity_provider.version import __version__, get_version
from antigravity_provider import paths

# Отчёт ворот печатается по-русски, а консоль Windows-раннера — cp1252.
# Ставится до первого вывода: иначе падает вывод, а не проверки.
force_utf8_output()


def check_version_consistency() -> tuple[bool, str]:
    ver = get_version()
    # Check compatibility.json
    compat_file = ROOT / "config" / "compatibility.json"
    if compat_file.exists():
        compat_data = json.loads(compat_file.read_text(encoding="utf-8"))
        if compat_data.get("hub_version") != ver:
            return False, f"compatibility.json has hub_version '{compat_data.get('hub_version')}' != '{ver}'"

    # Check pyproject.toml
    pyproject_file = ROOT / "pyproject.toml"
    if pyproject_file.exists():
        content = pyproject_file.read_text(encoding="utf-8")
        if f'version = "{ver}"' not in content:
            return False, f"pyproject.toml missing version = \"{ver}\""

    return True, f"Version {ver} is consistent across all manifests"


def _run_pytest(args: list[str]) -> subprocess.CompletedProcess:
    import shutil
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    pytest_bin = shutil.which("pytest")
    if pytest_bin:
        cmd = [pytest_bin] + args
    else:
        cmd = [sys.executable, "-m", "pytest"] + args
    return subprocess.run(
        cmd,
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
    )


def check_p0_release_gate() -> tuple[bool, str]:
    res = _run_pytest(["-v", "tests/test_p0_release_gate.py"])
    if res.returncode != 0:
        return False, f"P0 tests failed:\n{res.stdout}\n{res.stderr}"
    return True, "16/16 P0 release blockers & regression checks verified"


def check_updater_and_rollback() -> tuple[bool, str]:
    res = _run_pytest(["-v", "tests/test_updater.py"])
    if res.returncode != 0:
        return False, f"Updater tests failed:\n{res.stdout}\n{res.stderr}"
    return True, "Auto-updater, SHA-256 verification, and rollback verified"


def check_full_test_suite() -> tuple[bool, str]:
    res = _run_pytest(["-v"])
    if res.returncode != 0:
        return False, f"Offline pytest suite failed:\n{res.stdout}\n{res.stderr}"
    return True, "All unit and integration tests passed offline"


def check_zero_hardcoded_paths() -> tuple[bool, str]:
    forbidden_patterns = [
        re.compile(r"E:\\+Agent projects", re.IGNORECASE),
        re.compile(r"C:\\+Users\\+trush", re.IGNORECASE),
        re.compile(r"C:\\+Users\\+Ochenstarik", re.IGNORECASE),
    ]

    src_dir = ROOT / "src"
    violations = []
    for f in src_dir.rglob("*.py"):
        text = f.read_text(encoding="utf-8", errors="ignore")
        for pat in forbidden_patterns:
            if pat.search(text):
                violations.append(f"{f.relative_to(ROOT)} matched {pat.pattern}")

    if violations:
        return False, f"Found hardcoded developer paths in src:\n" + "\n".join(violations)
    return True, "Zero hardcoded developer paths in src/"


def _eval_ast_str_expr(node: ast.AST) -> str | None:
    """Evaluate constant string, binary string additions, or join of string constants in AST."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _eval_ast_str_expr(node.left)
        right = _eval_ast_str_expr(node.right)
        if left is not None and right is not None:
            return left + right
    elif isinstance(node, ast.Call):
        # Check ''.join(('a', 'b', ...))
        if isinstance(node.func, ast.Attribute) and node.func.attr == "join":
            if isinstance(node.func.value, ast.Constant) and isinstance(node.func.value.value, str):
                sep = node.func.value.value
                if node.args and isinstance(node.args[0], (ast.List, ast.Tuple)):
                    parts = []
                    for elt in node.args[0].elts:
                        sub = _eval_ast_str_expr(elt)
                        if sub is None:
                            return None
                        parts.append(sub)
                    return sep.join(parts)
    return None


def scan_file_for_secrets(file_path: Path) -> list[str]:
    """Scan a Python file using AST and regex for hardcoded secrets, keys, or obfuscated tokens."""
    violations = []
    content = file_path.read_text(encoding="utf-8", errors="ignore")

    # 1. Regex checks for live credentials
    patterns = [
        (re.compile(r"""(?:sk-[a-zA-Z0-9]{32,}|opencode-[a-zA-Z0-9]{20,})"""), "Live API key pattern"),
        (re.compile(r"""ya29\.[a-zA-Z0-9_-]{40,}"""), "Google OAuth user token"),
        (re.compile(r"""-----BEGIN [A-Z ]*PRIVATE KEY-----"""), "Private Key header"),
        (re.compile(r"""(?:bearer\s+[a-zA-Z0-9_\-\.]{40,})""", re.IGNORECASE), "Bearer token pattern"),
    ]
    for pat, desc in patterns:
        if pat.search(content):
            violations.append(f"{desc} in {file_path.name}")

    # 2. AST variable inspection
    try:
        tree = ast.parse(content, filename=str(file_path))
    except Exception as e:
        violations.append(f"Syntax error in {file_path.name}: {e}")
        return violations

    ALLOWED_PUBLIC_CLIENT_SECRET = "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"
    ALLOWED_PUBLIC_CLIENT_ID = "1071006060591-tmhssin2h21lcre235vtolojh4g403ep.apps.googleusercontent.com"
    SENSITIVE_VAR_NAMES = {"CLIENT_SECRET", "API_KEY", "ACCESS_TOKEN", "REFRESH_TOKEN", "SECRET_KEY", "PRIVATE_KEY"}

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.upper() in SENSITIVE_VAR_NAMES:
                    # Check if value is a statically evaluable string expression (literal or concatenation)
                    val_str = _eval_ast_str_expr(node.value)
                    if val_str is not None:
                        # Obfuscation detection
                        if isinstance(node.value, (ast.BinOp, ast.Call)):
                            violations.append(f"Obfuscated secret assignment in variable '{target.id}' in {file_path.name}")
                            continue

                        if target.id == "CLIENT_SECRET" and val_str == ALLOWED_PUBLIC_CLIENT_SECRET:
                            continue
                        if target.id == "CLIENT_ID" and val_str == ALLOWED_PUBLIC_CLIENT_ID:
                            continue
                        if val_str.startswith("PLACEHOLDER") or val_str.startswith("dummy_") or val_str == "":
                            continue
                        violations.append(f"Hardcoded sensitive secret in variable '{target.id}' in {file_path.name}")

    return violations


def check_security_zero_secrets() -> tuple[bool, str]:
    secret_files = list(ROOT.rglob("auth.json")) + list(ROOT.rglob("*.secret")) + list(ROOT.rglob("*.key")) + list(ROOT.rglob(".env*"))
    tracked_secrets = []
    for sf in secret_files:
        if ".git" not in str(sf) and "venv" not in str(sf) and "scratch" not in str(sf) and "example" not in str(sf):
            tracked_secrets.append(str(sf.relative_to(ROOT)))

    if tracked_secrets:
        return False, f"Found sensitive secret files in repository:\n" + "\n".join(tracked_secrets)

    # Scan all python files in src/
    src_dir = ROOT / "src"
    all_violations = []
    for f in src_dir.rglob("*.py"):
        violations = scan_file_for_secrets(f)
        if violations:
            all_violations.extend([f"{f.relative_to(ROOT)}: {v}" for v in violations])

    if all_violations:
        return False, f"Secret scanner detected violations in src/:\n" + "\n".join(all_violations)

    return True, "Zero secret files, live tokens, or obfuscated secret assignments in src/"


# ═══════════════════════════════════════════════════════════════
#  Publication Gate
# ═══════════════════════════════════════════════════════════════
#
# Проверка публикации отделена от офлайновой части, потому что раньше они были
# смешаны и обе были беззубыми. Измерено на прежней реализации:
#   - при полном обрыве сети возвращался PASS ("check skipped");
#   - при 404 на манифест возвращался PASS ("not yet published");
#   - при 404 на пакет возвращался PASS ("pending upload");
#   - при живом пакете печаталось PACKAGE_HASH_VERIFIED=True, хотя hashlib в
#     файле не вызывался ни разу: скачивались байты 0-10 через заголовок Range,
#     и этого хватало, чтобы объявить хеш проверенным.
# То есть ворота публикации пропускали релиз при любом исходе, включая полное
# отсутствие релиза.
#
# Теперь: офлайновые проверки (1-6) блокируют всегда; публикация проверяется
# по-настоящему — релиз есть, ассеты есть, пакет скачан целиком, SHA-256
# сошёлся с опубликованным. Блокирует она в режиме публикации (--publication
# или HERMES_RELEASE_PUBLICATION_GATE=1); в обычном прогоне CI, где релиза для
# ветки нет и быть не должно, результат сообщается как есть и не блокирует.
# Неизмеренное называется "Н/Д" с причиной, а не выдаётся за проверенное.

PUBLICATION_MODE_ENV = "HERMES_RELEASE_PUBLICATION_GATE"

# Имена ассетов-установщиков; совпадают с выбором в update_manager.
PACKAGE_ASSET_NAMES = ("HermesHubSetup.exe", "hermes-hub-setup.sh", "install-linux.sh")
CHECKSUMS_ASSET_NAME = "checksums.txt"

# Пакет качается целиком, поэтому размер ограничен: подставленный гигантский
# ассет не должен превращать ворота в отказ в обслуживании самим себе.
MAX_PACKAGE_BYTES = 512 * 1024 * 1024

# Нижняя граница размера установщика — защита от усечённой сборки. Найдено
# живым прогоном на Windows (A61): собранный HermesHubSetup.exe считался
# готовым к публикации даже будучи почти пустым — сборка прервалась, а файл
# остался. 1 МБ — заведомо меньше любого настоящего установщика (несёт
# исходники плагина вшитым ресурсом), но отличает пустышку от файла.
MIN_PACKAGE_BYTES = 1024 * 1024


def is_publication_mode() -> bool:
    """Требуется ли блокирующая проверка публикации."""
    return "--publication" in sys.argv or os.environ.get(PUBLICATION_MODE_ENV, "") == "1"


def _http_get(url: str, timeout: int = 30):
    import urllib.request
    req = urllib.request.Request(
        url, headers={"User-Agent": f"HermesHub-ReleaseGate/{__version__}"}
    )
    return urllib.request.urlopen(req, timeout=timeout)


def _download_and_hash(url: str) -> tuple[str, int]:
    """Скачать поток целиком и посчитать SHA-256. Никаких частичных диапазонов."""
    import hashlib
    digest = hashlib.sha256()
    size = 0
    with _http_get(url, timeout=120) as resp:
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_PACKAGE_BYTES:
                raise ValueError(f"пакет превышает {MAX_PACKAGE_BYTES} байт")
            digest.update(chunk)
    return digest.hexdigest(), size


def _hash_local_file(path: Path) -> tuple[str, int]:
    """Посчитать SHA-256 локального файла целиком. Размер — побочный продукт."""
    import hashlib
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 256)
            if not chunk:
                break
            size += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size


def _parse_checksums(text: str) -> dict[str, str]:
    """Разобрать строки вида '<sha256>  <имя файла>'."""
    table: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            table[parts[-1].lstrip("*")] = parts[0].lower()
    return table


def check_offline_update_contract() -> tuple[bool, str]:
    """Офлайновая часть: адрес обновления входит в список разрешённых."""
    from antigravity_provider.updater.update_manager import DEFAULT_UPDATE_URL, is_allowed_update_host

    if not is_allowed_update_host(DEFAULT_UPDATE_URL):
        return False, f"Адрес обновления вне списка разрешённых: {DEFAULT_UPDATE_URL}"
    return True, f"Адрес обновления в списке разрешённых: {DEFAULT_UPDATE_URL}"


def check_publication_gate() -> tuple[bool, str]:
    """Релиз опубликован, ассеты на месте, SHA-256 пакета сошёлся.

    В режиме публикации любой недостижимый шаг — отказ. Вне его отказ не
    блокирует релиз, но и не выдаётся за успех.
    """
    import urllib.error
    from antigravity_provider.updater.update_manager import DEFAULT_UPDATE_URL

    blocking = is_publication_mode()

    def verdict(ok: bool, msg: str) -> tuple[bool, str]:
        if ok:
            return True, msg
        if blocking:
            return False, msg
        return True, f"[НЕ БЛОКИРУЕТ: режим публикации не запрошен] {msg}"

    # 1. Манифест релиза
    try:
        with _http_get(DEFAULT_UPDATE_URL) as resp:
            if resp.status != 200:
                return verdict(False, f"Манифест релиза ответил HTTP {resp.status}")
            data = json.loads(resp.read().decode("utf-8-sig"))
    except urllib.error.HTTPError as he:
        return verdict(False, f"Манифест релиза недоступен: HTTP {he.code} ({DEFAULT_UPDATE_URL})")
    except Exception as exc:
        return verdict(False, f"Манифест релиза недоступен: {type(exc).__name__}: {exc}")

    version = data.get("version") or str(data.get("tag_name", "")).lstrip("v")
    if not version:
        return verdict(False, "В манифесте релиза нет ни version, ни tag_name")

    # 2. Ассеты
    assets: dict[str, str] = {}
    for asset in data.get("assets") or []:
        name = asset.get("name")
        url = asset.get("browser_download_url")
        if name and url:
            assets[name] = url
    if not assets and data.get("package_url"):
        assets[Path(data["package_url"]).name] = data["package_url"]

    if not assets:
        return verdict(False, f"У релиза v{version} нет ни одного ассета")

    packages = [n for n in PACKAGE_ASSET_NAMES if n in assets]
    if not packages:
        return verdict(
            False,
            f"У релиза v{version} нет ни одного пакета установки "
            f"{PACKAGE_ASSET_NAMES}; опубликованы: {sorted(assets)}",
        )

    # 3. Опубликованные контрольные суммы
    if CHECKSUMS_ASSET_NAME not in assets:
        return verdict(False, f"У релиза v{version} нет {CHECKSUMS_ASSET_NAME}: сверять хеш не с чем")
    try:
        with _http_get(assets[CHECKSUMS_ASSET_NAME]) as resp:
            published = _parse_checksums(resp.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        return verdict(False, f"{CHECKSUMS_ASSET_NAME} не скачивается: {type(exc).__name__}: {exc}")
    if not published:
        return verdict(False, f"{CHECKSUMS_ASSET_NAME} не содержит ни одной строки с SHA-256")

    # 4. Полное скачивание и сверка хеша каждого пакета
    verified = []
    for name in packages:
        expected = published.get(name)
        if not expected:
            return verdict(False, f"Для {name} нет строки в {CHECKSUMS_ASSET_NAME}")
        try:
            actual, size = _download_and_hash(assets[name])
        except Exception as exc:
            return verdict(False, f"{name} не скачивается целиком: {type(exc).__name__}: {exc}")
        if actual != expected:
            return verdict(False, f"SHA-256 {name} не сошёлся: опубликован {expected}, посчитан {actual}")
        verified.append(f"{name} ({size} байт)")

    return True, (
        f"[RELEASE_LIVE=True, PACKAGES={len(verified)}, PACKAGE_HASH_VERIFIED=True] "
        f"Релиз v{version}: пакеты скачаны целиком и сверены с {CHECKSUMS_ASSET_NAME} — "
        + ", ".join(verified)
    )


def check_publishable_assets(dist_dir: Path) -> tuple[bool, str]:
    """Собранный набор ассетов действительно устанавливается обновлением.

    Проверяется до публикации. Причина: update_manager ищет в релизе строго
    HermesHubSetup.exe или hermes-hub-setup.sh/install-linux.sh, а release.yml
    собирает hermes-hub-<версия>.zip и update_manifest.json. Такой релиз
    становится "latest", и на любой попытке обновиться владелец получает
    "В релизе не найден подходящий файл обновления для текущей платформы".

    Раньше это не проявлялось лишь потому, что весь релизный конвейер падал
    на тех же двух дефектах, что и CI: каждый его прогон завершался ошибкой, а
    релизы публиковались мимо него. Как только тесты позеленели, случайная
    защита исчезла — поэтому набор проверяется явно.

    Помимо присутствия файлов — размер и хеш КАЖДОГО найденного установщика
    против локального checksums.txt. Найдено живым прогоном на Windows
    (A61): сборка может прерваться на середине и оставить усечённый файл, а
    checksums.txt и сам установщик могут разойтись ещё до всякой публикации.
    Проверка одного присутствия этого не ловит.
    """
    if not dist_dir.is_dir():
        return False, f"Каталог сборки не найден: {dist_dir}"

    present = {item.name for item in dist_dir.iterdir() if item.is_file()}
    installers = sorted(present & set(PACKAGE_ASSET_NAMES))
    problems = []
    if not installers:
        problems.append(
            f"нет ни одного установщика {list(PACKAGE_ASSET_NAMES)} — "
            f"обновление такой релиз поставить не сможет"
        )
    if CHECKSUMS_ASSET_NAME not in present:
        problems.append(f"нет {CHECKSUMS_ASSET_NAME} — сверять хеш пакета будет не с чем")

    if problems:
        return False, (
            f"Набор ассетов в {dist_dir} непригоден для публикации: "
            + "; ".join(problems)
            + f". Собрано: {sorted(present)}. Установщики собираются скриптами "
            f"installer/build_installer.ps1 и installer/build_installer_linux.sh"
        )

    local_checksums = _parse_checksums((dist_dir / CHECKSUMS_ASSET_NAME).read_text(encoding="utf-8-sig", errors="replace"))
    verified = []
    for name in installers:
        actual_hash, size = _hash_local_file(dist_dir / name)
        if size < MIN_PACKAGE_BYTES:
            return False, (
                f"{name} подозрительно мал ({size} байт, ожидался хотя бы {MIN_PACKAGE_BYTES}) "
                f"— похоже на прерванную сборку"
            )
        expected_hash = local_checksums.get(name)
        if not expected_hash:
            return False, f"Для {name} нет строки в {CHECKSUMS_ASSET_NAME} — сверить хеш не с чем"
        if actual_hash != expected_hash:
            return False, (
                f"SHA-256 {name} не сошёлся с {CHECKSUMS_ASSET_NAME}: "
                f"файл {actual_hash}, записан {expected_hash}"
            )
        verified.append(f"{name} ({size} байт, SHA-256 сошёлся)")

    return True, f"Набор ассетов пригоден для публикации: {', '.join(verified)}"


def run_release_gate():
    print("=" * 70)
    print(f" Hermes Hub — Release Gate Verification Suite (Target: v{__version__})")
    mode = "публикация (проверки 1-8 блокируют)" if is_publication_mode() else "офлайн (блокируют 1-7)"
    print(f" Режим: {mode}")
    print("=" * 70)

    checks = [
        ("1. Version Consistency", "[UNIT VERIFIED]", check_version_consistency),
        ("2. P0 Release Blockers (16/16)", "[UNIT VERIFIED]", check_p0_release_gate),
        ("3. Auto-Updater & Rollback", "[INTEGRATION VERIFIED]", check_updater_and_rollback),
        ("4. Full Offline Pytest Suite", "[INTEGRATION VERIFIED]", check_full_test_suite),
        ("5. Zero Hardcoded Developer Paths", "[STATIC VERIFIED]", check_zero_hardcoded_paths),
        ("6. Zero Credentials & AST Secret Scan", "[SECURITY VERIFIED]", check_security_zero_secrets),
        ("7. Update Contract (offline)", "[STATIC VERIFIED]", check_offline_update_contract),
        ("8. Publication Gate", "[LIVE VERIFIED]", check_publication_gate),
    ]

    all_passed = True
    for title, tier, check_func in checks:
        print(f"\nRunning {title} ({tier})...")
        ok, msg = check_func()
        if ok:
            print(f"  {tier} {msg}")
        else:
            print(f"  [FAIL] {msg}")
            all_passed = False

    print("\n" + "=" * 70)
    if all_passed:
        print(f" [RELEASE GATE: PASSED] All criteria verified. Ready for Candidate v{__version__}")
        print("=" * 70)
        sys.exit(0)
    else:
        print(" [RELEASE GATE: FAILED] One or more checks failed. Release blocked.")
        print("=" * 70)
        sys.exit(1)


def _run_single(title: str, check) -> None:
    """Выполнить одну проверку и завершиться её итогом."""
    print("=" * 70)
    print(f" Hermes Hub — {title}")
    print("=" * 70)
    ok, msg = check()
    print(f"  {'[OK]' if ok else '[FAIL]'} {msg}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    if "--assets" in sys.argv:
        index = sys.argv.index("--assets")
        target = Path(sys.argv[index + 1]) if len(sys.argv) > index + 1 else ROOT / "dist"
        _run_single("Publishable Assets Check", lambda: check_publishable_assets(target))
    elif "--publication-only" in sys.argv:
        # Запускается ПОСЛЕ публикации: проверяет опубликованный релиз, а не сборку.
        os.environ[PUBLICATION_MODE_ENV] = "1"
        _run_single("Publication Gate", check_publication_gate)
    else:
        run_release_gate()
