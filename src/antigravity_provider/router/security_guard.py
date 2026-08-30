"""Security perimeter, boundary enforcement, credential protection, and forensic guards for Hermes Hub."""
from __future__ import annotations

import os
import re
import shlex
import shutil
import tempfile
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from antigravity_provider import paths

# ═══════════════════════════════════════════════════════════════
#  Exceptions
# ═══════════════════════════════════════════════════════════════


class SecurityViolationError(Exception):
    """Base exception for security perimeter violations."""

    def __init__(self, message: str, safe_alternative: Optional[str] = None, violation_type: str = "general"):
        super().__init__(message)
        self.message = message
        self.safe_alternative = safe_alternative
        self.violation_type = violation_type


class BoundaryViolationError(SecurityViolationError):
    """Raised when an operation attempts to access or mutate paths outside allowed workspace."""

    def __init__(self, message: str, safe_alternative: Optional[str] = None):
        super().__init__(message, safe_alternative=safe_alternative, violation_type="boundary")


class CredentialProtectionError(SecurityViolationError):
    """Raised when an operation attempts to directly delete or corrupt protected credential files."""

    def __init__(self, message: str, safe_alternative: Optional[str] = None):
        super().__init__(message, safe_alternative=safe_alternative, violation_type="credentials")


class NetworkBoundaryViolationError(SecurityViolationError):
    """Raised when an outbound network request targets a host not in the allowed destination whitelist."""

    def __init__(self, message: str, safe_alternative: Optional[str] = None):
        super().__init__(message, safe_alternative=safe_alternative, violation_type="network")


# ═══════════════════════════════════════════════════════════════
#  Secret Scrubbing Utilities
# ═══════════════════════════════════════════════════════════════

BLOCKED_KEY_SUBSTRINGS: tuple[str, ...] = (
    "api_key",
    "token",
    "secret",
    "password",
    "client_secret",
    "refresh_token",
    "access_token",
    "private_key",
    "jwt",
    "auth_token",
    "credential",
    "bearer",
)

AUTH_BEARER_PATTERN = re.compile(r"Bearer\s+[A-Za-z0-9._~+/-]+", re.IGNORECASE)
ACCESS_TOKEN_QUERY_PATTERN = re.compile(r"(access_token=)[^&]+", re.IGNORECASE)
API_KEY_HEADER_PATTERN = re.compile(r"([A-Za-z0-9_-]*(?:api[_-]?key|token|secret|password)\s*[:=]\s*)[A-Za-z0-9._~+/-]+", re.IGNORECASE)
GENERIC_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{10,}", re.IGNORECASE),
    re.compile(r"gh[opsu]_[A-Za-z0-9_-]{10,}", re.IGNORECASE),
    re.compile(r"xox[baprs]-[A-Za-z0-9_-]{10,}", re.IGNORECASE),
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9._~+/-]{10,}", re.IGNORECASE),
]


def scrub_secrets(data: Any) -> Any:
    """Recursively scrub credentials, API keys, and authorization tokens from strings, dictionaries, and collections."""
    if isinstance(data, dict):
        result = {}
        for k, v in data.items():
            k_lower = str(k).lower()
            if any(sub in k_lower for sub in BLOCKED_KEY_SUBSTRINGS):
                result[k] = "***"
            elif isinstance(v, (dict, list, tuple, set)):
                result[k] = scrub_secrets(v)
            elif isinstance(v, str):
                result[k] = scrub_string(v)
            else:
                result[k] = v
        return result
    elif isinstance(data, list):
        return [scrub_secrets(item) for item in data]
    elif isinstance(data, tuple):
        return tuple(scrub_secrets(item) for item in data)
    elif isinstance(data, set):
        return {scrub_secrets(item) for item in data}
    elif isinstance(data, str):
        return scrub_string(data)
    return data


def scrub_string(text: str) -> str:
    """Mask credentials, bearer tokens, query parameters, and API keys within arbitrary text strings."""
    if not text or not isinstance(text, str):
        return str(text or "")
    s = AUTH_BEARER_PATTERN.sub("Bearer ***", text)
    s = ACCESS_TOKEN_QUERY_PATTERN.sub(r"\1***", s)
    s = API_KEY_HEADER_PATTERN.sub(r"\1***", s)
    for pat in GENERIC_SECRET_PATTERNS:
        s = pat.sub("***", s)
    return s


# ═══════════════════════════════════════════════════════════════
#  P0-1: Workspace Boundary & Destructive Operations Guard
# ═══════════════════════════════════════════════════════════════

DESTRUCTIVE_COMMAND_NAMES: Set[str] = {
    "rm",
    "rmdir",
    "unlink",
    "del",
    "erase",
    "rd",
    "remove-item",
    "ri",
    "trash-put",
    "srm",
    "shred",
}


class WorkspaceBoundaryGuard:
    """Enforces explicit workspace boundaries, defends credential directories, and inspects destructive operations."""

    def __init__(self, additional_allowed_roots: Optional[List[Path]] = None):
        self._custom_roots: List[Path] = [r.resolve() for r in (additional_allowed_roots or [])]

    def get_allowed_roots(self) -> List[Path]:
        """Return the canonical list of allowed roots (Project Root, HERMES_HOME, explicit allowed roots)."""
        roots: List[Path] = []
        try:
            repo_root = paths.get_repo_root().resolve()
            roots.append(repo_root)
        except Exception:
            pass

        try:
            hermes_home = paths.get_hermes_home().resolve()
            roots.append(hermes_home)
        except Exception:
            pass

        roots.extend(self._custom_roots)
        # Deduplicate while preserving order
        deduped = []
        seen = set()
        for r in roots:
            resolved = r.resolve()
            if resolved not in seen:
                seen.add(resolved)
                deduped.append(resolved)
        return deduped

    def get_forbidden_paths(self) -> List[Path]:
        """Return unconditionally protected paths (Credentials, SSH, Core Hub Configs)."""
        forbidden = []
        try:
            hermes_home = paths.get_hermes_home().resolve()
            # Credential pools
            forbidden.append((hermes_home / "agy_profiles").resolve())
            forbidden.append((hermes_home / "codex_profiles").resolve())
            forbidden.append((hermes_home / "opencode_profiles").resolve())
            forbidden.append((hermes_home / "claude_profiles").resolve())
            forbidden.append((hermes_home / "grok_profiles").resolve())
            forbidden.append((hermes_home / "local_profiles").resolve())
            # Sensitive config files
            forbidden.append((hermes_home / "auth.json").resolve())
            forbidden.append((hermes_home / "hub_settings.json").resolve())
            forbidden.append((hermes_home / "router_profiles.yaml").resolve())
        except Exception:
            pass

        # User SSH directory
        try:
            ssh_dir = (Path.home() / ".ssh").resolve()
            forbidden.append(ssh_dir)
        except Exception:
            pass

        # User global credentials
        try:
            user_agy = (Path.home() / ".hermes" / "agy_profiles").resolve()
            if user_agy not in forbidden:
                forbidden.append(user_agy)
        except Exception:
            pass

        return forbidden

    def is_inside_allowed_root(self, path: Path | str) -> bool:
        """Check whether the given path resolves within any allowed root."""
        try:
            target = Path(path).expanduser().resolve()
            for root in self.get_allowed_roots():
                try:
                    target.relative_to(root)
                    return True
                except ValueError:
                    continue
            return False
        except Exception:
            return False

    def is_forbidden_path(self, path: Path | str) -> Tuple[bool, Optional[str]]:
        """Check whether the path touches an unconditionally protected directory or file."""
        try:
            target = Path(path).expanduser().resolve()
            # 1. Exact match or child of forbidden directory
            for fpath in self.get_forbidden_paths():
                if target == fpath:
                    return True, f"Путь {target} является защищённым системным ресурсом"
                try:
                    target.relative_to(fpath)
                    return True, f"Путь {target} находится внутри защищённого каталога учётных данных {fpath}"
                except ValueError:
                    continue

            # 2. Match critical filenames
            target_name = target.name.lower()
            if target_name in {"auth.json", "hub_settings.json", "id_rsa", "id_ed25519", "known_hosts"}:
                return True, f"Файл {target_name} является защищённым системным файлом"

            # 3. Match .git core internals
            for part in target.parts:
                if part.lower() == ".git":
                    # Disallow deleting/modifying .git root, hooks, objects, or config
                    if target_name in {"config", "head", "index"} or "objects" in target.parts or "hooks" in target.parts:
                        return True, "Прямое разрушение служебных файлов git (.git/) запрещено"

            return False, None
        except Exception as exc:
            return True, f"Ошибка разрешения пути: {exc}"

    def validate_path(self, path: Path | str, operation: str = "read") -> Tuple[bool, str, Optional[str]]:
        """Validate whether an operation on path is permitted.

        Returns: (is_allowed: bool, reason: str, safe_alternative: Optional[str])
        """
        try:
            target = Path(path).expanduser().resolve()
        except Exception as exc:
            return False, f"Недопустимый путь '{path}': {exc}", "Используйте стандартный относительный путь"

        # Check unconditional forbidden paths for mutating/deleting operations
        if operation in {"delete", "write", "truncate", "move"}:
            is_forbidden, forbidden_reason = self.is_forbidden_path(target)
            if is_forbidden:
                alt = (
                    "Для удаления аккаунта используйте штатное действие 'delete_credentials' с подтверждением"
                    if "agy_profiles" in str(target) or "auth" in str(target)
                    else "Выполняйте операцию только в рабочей области проекта"
                )
                return False, f"Запрещённая операция над защищённым ресурсом: {forbidden_reason}", alt

        # Check boundary containment
        if not self.is_inside_allowed_root(target):
            roots_display = ", ".join(str(r) for r in self.get_allowed_roots())
            return (
                False,
                f"Путь '{target}' находится за пределами разрешённых рабочих областей: [{roots_display}]",
                "Переместите целевой файл в каталог проекта или рабочую область агента",
            )

        return True, "OK", None

    def validate_command(self, cmd_line: str | List[str], cwd: Optional[Path | str] = None) -> Tuple[bool, str, Optional[str]]:
        """Inspect and classify a shell command line for destructive or boundary-violating operations.

        Returns: (is_allowed: bool, reason: str, safe_alternative: Optional[str])
        """
        if not cmd_line:
            return True, "OK", None

        # Parse command tokens
        if isinstance(cmd_line, list):
            tokens = list(cmd_line)
        else:
            try:
                # Windows and POSIX-compatible shlex split
                tokens = shlex.split(cmd_line, posix=(os.name != "nt"))
            except Exception:
                tokens = cmd_line.split()

        if not tokens:
            return True, "OK", None

        base_cwd = Path(cwd or paths.get_repo_root()).resolve()
        cmd_name = Path(tokens[0]).name.lower()
        if cmd_name.endswith(".exe"):
            cmd_name = cmd_name[:-4]

        # 1. Check destructive command names
        if cmd_name in DESTRUCTIVE_COMMAND_NAMES:
            # Extract target arguments (skip flags starting with - or /)
            targets = []
            for arg in tokens[1:]:
                if arg.startswith("-") or (os.name == "nt" and arg.startswith("/") and len(arg) == 2):
                    continue
                targets.append(arg)

            if not targets:
                # If no targets specified (e.g. interactive rm), check cwd
                ok, reason, alt = self.validate_path(base_cwd, operation="delete")
                if not ok:
                    return False, f"Команда {cmd_name} запущена в недопустимом каталоге: {reason}", alt
            else:
                for target_arg in targets:
                    # Тильда и переменные окружения раскрываются ДО проверки.
                    #
                    # Без этого "rm -rf ~/.hermes/agy_profiles" не считался
                    # абсолютным путём, склеивался с каталогом проекта в путь с
                    # буквальным "~" внутри и признавался допустимым. Проверено:
                    # команда с тильдой проходила, та же команда с абсолютным
                    # путём отклонялась. То есть самый естественный способ
                    # написать опасную команду обходил защиту ровно там, ради
                    # чего она и делалась — на каталоге учётных данных.
                    expanded = os.path.expandvars(os.path.expanduser(target_arg))
                    target_path = Path(expanded) if Path(expanded).is_absolute() else (base_cwd / expanded)
                    ok, reason, alt = self.validate_path(target_path, operation="delete")
                    if not ok:
                        return False, f"Команда '{cmd_name}' пытается удалить недопустимый путь '{target_arg}': {reason}", alt

        # 2. Check git clean -fdx / git reset --hard targets
        if cmd_name == "git":
            subcmd = tokens[1].lower() if len(tokens) > 1 else ""
            if subcmd == "clean" and any("-f" in a or "-x" in a or "-d" in a for a in tokens[2:]):
                # Git clean inside workspace is allowed only if CWD is strictly within project root
                ok, reason, alt = self.validate_path(base_cwd, operation="delete")
                if not ok:
                    return False, f"git clean запущен вне проекта: {reason}", alt

        return True, "OK", None

    def dry_run_deletion(self, target_paths: List[Path | str]) -> Dict[str, Any]:
        """Perform a safe dry-run assessment of a pending deletion, returning affected files and risk analysis."""
        files_to_delete: List[Dict[str, Any]] = []
        dirs_to_delete: List[Dict[str, Any]] = []
        total_bytes = 0
        risk_level = "low"
        has_violations = False
        reasons: List[str] = []

        for p_raw in target_paths:
            p = Path(p_raw).expanduser().resolve()
            ok, reason, alt = self.validate_path(p, operation="delete")
            if not ok:
                has_violations = True
                reasons.append(reason)
                risk_level = "critical"
                continue

            if p.is_file():
                try:
                    sz = p.stat().st_size
                except OSError:
                    sz = 0
                total_bytes += sz
                files_to_delete.append({"path": str(p), "size_bytes": sz, "type": "file"})
            elif p.is_dir():
                dir_bytes = 0
                file_count = 0
                for root, _, files in os.walk(p):
                    for f in files:
                        fp = Path(root) / f
                        try:
                            fsz = fp.stat().st_size
                        except OSError:
                            fsz = 0
                        dir_bytes += fsz
                        file_count += 1
                total_bytes += dir_bytes
                dirs_to_delete.append({"path": str(p), "file_count": file_count, "size_bytes": dir_bytes, "type": "directory"})
                if file_count > 10:
                    risk_level = "medium" if risk_level != "critical" else risk_level

        return {
            "dry_run": True,
            "allowed": not has_violations,
            "risk_level": risk_level,
            "total_files": len(files_to_delete),
            "total_dirs": len(dirs_to_delete),
            "total_bytes": total_bytes,
            "files": files_to_delete[:100],
            "directories": dirs_to_delete,
            "violations": reasons,
        }

    def safe_delete_file(self, path: Path | str, dry_run: bool = False) -> Dict[str, Any]:
        """Safely delete a single file after boundary and credential checks, supporting dry-run."""
        target = Path(path).expanduser().resolve()
        ok, reason, alt = self.validate_path(target, operation="delete")
        if not ok:
            raise BoundaryViolationError(reason, safe_alternative=alt)

        if dry_run:
            return self.dry_run_deletion([target])

        if not target.exists():
            return {"deleted": False, "reason": "File does not exist", "path": str(target)}

        if target.is_dir():
            raise BoundaryViolationError(f"Путь '{target}' является директорией, используйте safe_delete_dir")

        target.unlink()
        return {"deleted": True, "path": str(target)}

    def safe_delete_dir(self, path: Path | str, dry_run: bool = False) -> Dict[str, Any]:
        """Safely delete a directory tree after boundary and credential checks, supporting dry-run."""
        target = Path(path).expanduser().resolve()
        ok, reason, alt = self.validate_path(target, operation="delete")
        if not ok:
            raise BoundaryViolationError(reason, safe_alternative=alt)

        if dry_run:
            return self.dry_run_deletion([target])

        if not target.exists():
            return {"deleted": False, "reason": "Directory does not exist", "path": str(target)}

        if not target.is_dir():
            raise BoundaryViolationError(f"Путь '{target}' не является директорией")

        shutil.rmtree(target)
        return {"deleted": True, "path": str(target)}


# ═══════════════════════════════════════════════════════════════
#  P0-3: Network Boundary Guard & Whitelist
# ═══════════════════════════════════════════════════════════════

ALLOWED_OUTBOUND_HOSTS: Set[str] = {
    # 1. AI Provider APIs
    "api.anthropic.com",
    "generativelanguage.googleapis.com",
    "api.x.ai",
    "api.openai.com",
    "api.deepseek.com",
    "openrouter.ai",
    "api.together.xyz",
    "api.groq.com",
    "api.mistral.ai",
    "dashscope.aliyuncs.com",
    "open.bigmodel.cn",
    "api.moonshot.cn",
    # 2. Release & Update Hosts
    "api.github.com",
    "github.com",
    "raw.githubusercontent.com",
    "objects.githubusercontent.com",
    "github-releases.githubusercontent.com",
    # 3. Local LLMs & Diagnostics
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
}


class NetworkBoundaryGuard:
    """Enforces explicit network boundaries for all outgoing Hub HTTP/HTTPS requests."""

    @classmethod
    def is_host_allowed(cls, host_or_url: str) -> bool:
        """Check whether the given hostname or URL target is allowed by the whitelist."""
        if not host_or_url:
            return False
        clean = host_or_url.strip().lower()
        if "://" in clean:
            parsed = urllib.parse.urlparse(clean)
            host = (parsed.hostname or "").lower()
        else:
            host = clean.split(":")[0].lower()

        if not host:
            return False

        # Exact match
        if host in ALLOWED_OUTBOUND_HOSTS:
            return True

        # Wildcard subdomain match (e.g. *.githubusercontent.com, *.aliyuncs.com, *.googleapis.com)
        for allowed in ALLOWED_OUTBOUND_HOSTS:
            if allowed.startswith("*."):
                suffix = allowed[1:]
                if host.endswith(suffix):
                    return True
            elif host.endswith("." + allowed):
                # Subdomains of explicitly trusted domains (e.g. download.github.com)
                return True

        # Local subnet / private IP / loopback allow
        if host.startswith("127.") or host.startswith("10.") or host.startswith("192.168."):
            return True

        return False

    @classmethod
    def validate_outbound_url(cls, url: str) -> None:
        """Validate destination URL, raising NetworkBoundaryViolationError if host is not permitted."""
        if not cls.is_host_allowed(url):
            parsed = urllib.parse.urlparse(url)
            hostname = parsed.hostname or url
            raise NetworkBoundaryViolationError(
                f"Сетевое обращение к хосту '{hostname}' заблокировано сетевой границей хаба.",
                safe_alternative="Используйте разрешённых провайдеров из белого списка или настройте локальный прокси",
            )


# ═══════════════════════════════════════════════════════════════
#  P0-2: Agent Workspace Guard & Role Credential Separation
# ═══════════════════════════════════════════════════════════════


class AgentWorkspaceGuard:
    """Provides workspace isolation and scoped credential injection per agent/role."""

    @staticmethod
    def get_agent_workspace_dir(agent_id: str) -> Path:
        """Return dedicated workspace directory for an agent, ensuring it exists."""
        clean_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(agent_id).strip()).strip("-").lower()
        ws_dir = paths.get_hermes_home() / "workspaces" / f"agent-{clean_id}"
        ws_dir.mkdir(parents=True, exist_ok=True)
        return ws_dir.resolve()

    @staticmethod
    def build_agent_subprocess_env(
        agent_id: str,
        role: str,
        assigned_profile_id: Optional[str] = None,
    ) -> Dict[str, str]:
        """Construct an isolated environment containing ONLY the credentials needed for the agent's assigned role."""
        from antigravity_provider.agy_subprocess import build_safe_subprocess_env
        from antigravity_provider.router.adapters.antigravity_adapter import get_profile_env_dir

        ws_dir = AgentWorkspaceGuard.get_agent_workspace_dir(agent_id)
        overrides: Dict[str, str] = {
            "HERMES_AGENT_ID": agent_id,
            "HERMES_AGENT_ROLE": role,
            "HERMES_AGENT_WORKSPACE": str(ws_dir),
        }

        # Role-scoped profile isolation: inject HOME/USERPROFILE targeting the agent's profile directory
        if assigned_profile_id:
            profile_dir = get_profile_env_dir(assigned_profile_id)
            overrides["HOME"] = str(profile_dir)
            overrides["USERPROFILE"] = str(profile_dir)
            overrides["HOMEPATH"] = str(profile_dir)

        return build_safe_subprocess_env(overrides=overrides)


# Singleton instance
_workspace_guard = WorkspaceBoundaryGuard()


def get_workspace_guard() -> WorkspaceBoundaryGuard:
    return _workspace_guard
