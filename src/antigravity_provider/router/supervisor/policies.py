"""Centralized WebPolicy & ToolPolicy enforcement layer for Multi-Provider Router."""
from __future__ import annotations

import fnmatch
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

from antigravity_provider.router.unified_health import EventLogService

logger = logging.getLogger("hermes.router.policies")


@dataclass
class WebPolicyConfig:
    enabled: bool = True
    allowed_domains: List[str] = field(default_factory=lambda: [
        "*.googleapis.com",
        "*.google.com",
        "*.openai.com",
        "api.opencode.ai",
        "*.deepseek.com",
        "*.github.com",
        "github.com",
    ])
    blocked_domains: List[str] = field(default_factory=lambda: [
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "169.254.169.254",  # AWS/Cloud metadata
        "*.internal",
        "*.local",
    ])
    allow_localhost_for_oauth: bool = True
    max_request_bytes: int = 10 * 1024 * 1024  # 10 MB
    timeout_sec: float = 30.0


@dataclass
class ToolPolicyConfig:
    enabled: bool = True
    allowed_tools: List[str] = field(default_factory=lambda: [
        "search_web",
        "read_url_content",
        "run_command",
        "view_file",
        "write_to_file",
        "replace_file_content",
        "list_dir",
        "grep_search",
        "find_by_name",
    ])
    blocked_tools: List[str] = field(default_factory=list)
    require_confirmation_tools: List[str] = field(default_factory=lambda: [
        "run_destructive_command",
        "delete_database",
    ])
    blocked_command_patterns: List[str] = field(default_factory=lambda: [
        r"format\s+[a-zA-Z]:",
        r"rmdir\s+/s\s+/q\s+c:\\",
        r"del\s+/f\s+/s\s+/q\s+c:\\windows",
        r"shutdown\s+/s",
    ])


class PolicyEnforcer:
    """Policy engine validating web outbound connections and tool executions."""

    _instance: Optional[PolicyEnforcer] = None

    def __init__(
        self,
        web_config: Optional[WebPolicyConfig] = None,
        tool_config: Optional[ToolPolicyConfig] = None,
    ):
        self.web_config = web_config or WebPolicyConfig()
        self.tool_config = tool_config or ToolPolicyConfig()

    @classmethod
    def get(cls) -> PolicyEnforcer:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def validate_url(self, url: str, is_oauth_callback: bool = False) -> Tuple[bool, str]:
        """Validate if outgoing URL is permitted under WebPolicy."""
        if not self.web_config.enabled:
            return True, "WebPolicy disabled"

        try:
            parsed = urlparse(url)
            host = (parsed.hostname or "").lower()
            if not host:
                return False, f"Invalid URL format: {url}"

            # Check OAuth localhost exception
            if is_oauth_callback and self.web_config.allow_localhost_for_oauth:
                if host in ("localhost", "127.0.0.1"):
                    return True, "OAuth localhost permitted"

            # Check blocked hosts
            for pat in self.web_config.blocked_domains:
                if fnmatch.fnmatch(host, pat):
                    EventLogService.get().log("security", f"Заблокирован доступ к хосту: {host}", level="warning")
                    return False, f"Access to host '{host}' blocked by WebPolicy"

            # Check allowed domains
            allowed = False
            for pat in self.web_config.allowed_domains:
                if fnmatch.fnmatch(host, pat):
                    allowed = True
                    break

            if not allowed:
                EventLogService.get().log("security", f"Хост не в списке разрешенных: {host}", level="warning")
                return False, f"Host '{host}' is not in WebPolicy allowlist"

            return True, "URL allowed"
        except Exception as e:
            return False, f"URL validation error: {e}"

    def validate_tool_execution(self, tool_name: str, tool_args: Dict[str, Any]) -> Tuple[bool, str]:
        """Validate if tool execution is permitted under ToolPolicy."""
        if not self.tool_config.enabled:
            return True, "ToolPolicy disabled"

        if tool_name in self.tool_config.blocked_tools:
            EventLogService.get().log("security", f"Вызов инструмента '{tool_name}' запрещен политикой", level="error")
            return False, f"Tool '{tool_name}' is blocked by ToolPolicy"

        # Check command safety for run_command
        if tool_name == "run_command":
            cmd = tool_args.get("CommandLine", "") or tool_args.get("command", "")
            for pat in self.tool_config.blocked_command_patterns:
                if re.search(pat, cmd, re.IGNORECASE):
                    EventLogService.get().log("security", f"Опасная команда заблокирована: {cmd[:60]}", level="error")
                    return False, f"Command matches dangerous pattern: {pat}"

        return True, "Tool execution permitted"
