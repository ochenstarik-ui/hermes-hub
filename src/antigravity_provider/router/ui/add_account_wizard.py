"""Hermes Hub — Add Account Multi-Step Wizard Modal (v4).

Supports 5 AI Providers:
1. Google Antigravity (Cockpit Tools model OAuth with immediate URL & manual fallback)
2. OpenAI Codex (OAuth / ChatGPT Device Code flow + OpenAI API Key mode)
3. OpenCode Go (API Key / Token input with clipboard Paste button & full keyboard shortcuts)
4. Claude / Anthropic (OAuth PKCE for Claude Pro/Max + Anthropic API Key mode)
5. Grok / xAI (OAuth Device Code for SuperGrok + xAI API Key mode)

Includes multi-account profile isolation, duplicate detection, and auto-assignment to router roles.
"""

from __future__ import annotations

import json
import os
import threading
import time
import webbrowser
from typing import Any, Callable, Dict, List, Optional
import customtkinter as ctk

from antigravity_provider.router.ui.theme import Theme
from antigravity_provider.router.ui.components import HubButton, HubCard, HubEntry, HubModal
from antigravity_provider.router.auto_assigner import AutoAssigner
from antigravity_provider.router.profile_manager import ProfileAuthManager
from antigravity_provider.router.unified_health import EventLogService


class AddAccountWizard(HubModal):
    """4-Step Add Account Wizard with OAuth / API Key support and Auto-Assignment."""

    def __init__(self, parent: Any, on_complete: Optional[Callable[[Dict[str, Any]], None]] = None):
        super().__init__(parent, title="Мастер подключения аккаунта", width=640, height=560)
        self.on_complete = on_complete
        self.step = 1

        self.selected_provider: str = "antigravity"
        self.codex_auth_mode: str = "oauth"  # oauth | api_key
        self.claude_auth_mode: str = "oauth"  # oauth | api_key
        self.grok_auth_mode: str = "oauth"  # oauth | api_key

        self.target_slot: str = ""
        self.discovered_identity: str = ""
        self.discovered_plan: str = "Тариф: неизвестен"
        self.discovered_models: List[str] = []
        self.is_verified: bool = False

        # Session tracking
        self.oauth_session_id: Optional[str] = None
        self.oauth_url: Optional[str] = None
        self.oauth_port: Optional[int] = None

        self.codex_session_id: Optional[str] = None
        self.codex_url: Optional[str] = None
        self.codex_user_code: Optional[str] = None

        self.claude_session_id: Optional[str] = None
        self.claude_url: Optional[str] = None

        self.grok_session_id: Optional[str] = None
        self.grok_url: Optional[str] = None
        self.grok_user_code: Optional[str] = None

        self._polling_active = False

        self._show_step_1_provider()

    def destroy(self):
        self._polling_active = False
        self._cancel_active_sessions()
        super().destroy()

    def _clear_body(self):
        for w in self.body.winfo_children():
            w.destroy()
        for w in self.footer.winfo_children():
            w.destroy()

    def _cancel_active_sessions(self):
        if self.oauth_session_id:
            try:
                from antigravity_provider.router.profile_oauth import cancel_oauth_session

                cancel_oauth_session(self.oauth_session_id)
            except Exception:
                pass
            self.oauth_session_id = None
            self.oauth_port = None

        if self.codex_session_id:
            try:
                from antigravity_provider.router.codex_oauth import cancel_codex_oauth_session

                cancel_codex_oauth_session(self.codex_session_id)
            except Exception:
                pass
            self.codex_session_id = None

        if self.claude_session_id:
            try:
                from antigravity_provider.router.claude_oauth import cancel_claude_oauth_session

                cancel_claude_oauth_session(self.claude_session_id)
            except Exception:
                pass
            self.claude_session_id = None

        if self.grok_session_id:
            try:
                from antigravity_provider.router.grok_oauth import cancel_grok_oauth_session

                cancel_grok_oauth_session(self.grok_session_id)
            except Exception:
                pass
            self.grok_session_id = None

    # ═══════════════════════════════════════════════════════════════
    #  STEP 1: Provider Selection
    # ═══════════════════════════════════════════════════════════════

    def _show_step_1_provider(self):
        self._cancel_active_sessions()
        self._polling_active = False
        self._clear_body()
        self.title_lbl.configure(text="Шаг 1 из 4: Выберите провайдера ИИ")

        ctk.CTkLabel(
            self.body,
            text="Выберите платформу для подключения учетной записи:",
            font=Theme.font_body(),
            text_color=Theme.TEXT_SECONDARY,
        ).pack(anchor="w", pady=(0, 10))

        providers = [
            ("antigravity", "Google Antigravity", "OAuth 2.0 (Google Account)", Theme.ACCENT),
            ("openai-codex", "OpenAI Codex", "OAuth (ChatGPT) или API Key", Theme.PROVIDER_CODEX),
            ("claude", "Claude (Anthropic)", "OAuth (Claude Pro/Max) или API Key", Theme.PROVIDER_CLAUDE),
            ("grok", "Grok (xAI)", "OAuth (SuperGrok) или API Key", Theme.PROVIDER_GROK),
            ("opencode-go", "OpenCode Go", "API Key / Subscription", Theme.PROVIDER_GENERIC),
        ]

        self.provider_var = ctk.StringVar(value=self.selected_provider)

        for p_id, p_title, p_desc, p_color in providers:
            card = HubCard(self.body)
            card.pack(fill="x", pady=3)

            r_frame = ctk.CTkFrame(card, fg_color="transparent")
            r_frame.pack(fill="x", padx=12, pady=6)

            rb = ctk.CTkRadioButton(
                r_frame,
                text=p_title,
                value=p_id,
                variable=self.provider_var,
                font=Theme.font_body_bold(),
                fg_color=p_color,
                command=lambda pid=p_id: self._select_provider(pid),
            )
            rb.pack(side="left")

            ctk.CTkLabel(
                r_frame,
                text=f"•  {p_desc}",
                font=Theme.font_caption(),
                text_color=Theme.TEXT_MUTED,
            ).pack(side="left", padx=(10, 0))

        # Footer
        HubButton(
            self.footer,
            text="Отмена",
            variant="ghost",
            command=self.destroy,
        ).pack(side="left", padx=10, pady=10)

        HubButton(
            self.footer,
            text="Далее →",
            variant="primary",
            command=self._proceed_to_step_2,
        ).pack(side="right", padx=10, pady=10)

    def _select_provider(self, p_id: str):
        self.selected_provider = p_id

    def _proceed_to_step_2(self):
        self.selected_provider = self.provider_var.get()
        self.step = 2
        self._show_step_2_auth()

    # ═══════════════════════════════════════════════════════════════
    #  STEP 2: Authentication
    # ═══════════════════════════════════════════════════════════════

    def _show_step_2_auth(self):
        self._clear_body()
        self.title_lbl.configure(text="Шаг 2 из 4: Авторизация учетной записи")

        self.target_slot = (
            AutoAssigner.find_free_slot(self.selected_provider) or f"{self.selected_provider[:3]}-spare-1"
        )

        if self.selected_provider == "antigravity":
            self._build_antigravity_oauth_flow()
        elif self.selected_provider == "openai-codex":
            if self.codex_auth_mode == "oauth":
                self._build_codex_oauth_flow()
            else:
                self._build_api_key_flow()
        elif self.selected_provider == "claude":
            if self.claude_auth_mode == "oauth":
                self._build_claude_oauth_flow()
            else:
                self._build_api_key_flow()
        elif self.selected_provider == "grok":
            if self.grok_auth_mode == "oauth":
                self._build_grok_oauth_flow()
            else:
                self._build_api_key_flow()
        else:
            self._build_api_key_flow()

    # ─────────────────────────────────────────────────────────────
    #  GOOGLE ANTIGRAVITY OAUTH FLOW
    # ─────────────────────────────────────────────────────────────

    def _build_antigravity_oauth_flow(self):
        ctk.CTkLabel(
            self.body,
            text="Для Google Antigravity требуется авторизация Google OAuth.",
            font=Theme.font_body_bold(),
            text_color=Theme.TEXT_PRIMARY,
            anchor="w",
        ).pack(fill="x", pady=(0, 2))

        # Authorization link card
        auth_card = HubCard(self.body, fg_color=Theme.SURFACE_MUTED)
        auth_card.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(
            auth_card,
            text="Ссылка авторизации",
            font=Theme.font_caption(),
            text_color=Theme.TEXT_SECONDARY,
        ).pack(anchor="w", padx=10, pady=(6, 2))

        url_row = ctk.CTkFrame(auth_card, fg_color="transparent")
        url_row.pack(fill="x", padx=10, pady=(0, 6))

        self.oauth_url_entry = HubEntry(
            url_row,
            font=Theme.font_mono(),
            height=32,
            fg_color=Theme.PRIMARY,
            border_color=Theme.BORDER,
            text_color=Theme.TEXT_PRIMARY,
        )
        self.oauth_url_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.copy_url_btn = HubButton(
            url_row,
            text="📋",
            variant="secondary",
            width=40,
            height=32,
            command=self._copy_oauth_url,
        )
        self.copy_url_btn.pack(side="right")

        action_row = ctk.CTkFrame(auth_card, fg_color="transparent")
        action_row.pack(fill="x", padx=10, pady=(0, 8))

        self.open_browser_btn = HubButton(
            action_row,
            text="🌐 Открыть в браузере",
            variant="primary",
            width=180,
            command=self._open_oauth_browser,
        )
        self.open_browser_btn.pack(side="left", padx=(0, 8))

        # Manual Callback Fallback Card
        manual_card = HubCard(self.body, fg_color=Theme.SURFACE_MUTED)
        manual_card.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(
            manual_card,
            text="▸ Не удалось завершить авторизацию автоматически?",
            font=Theme.font_body_bold(),
            text_color=Theme.TEXT_PRIMARY,
            anchor="w",
        ).pack(fill="x", padx=10, pady=(6, 2))

        ctk.CTkLabel(
            manual_card,
            text="Вставьте полный URL из адресной строки браузера (если localhost вернул ошибку):",
            font=Theme.font_caption(),
            text_color=Theme.TEXT_SECONDARY,
            anchor="w",
        ).pack(fill="x", padx=10, pady=(0, 4))

        manual_entry_row = ctk.CTkFrame(manual_card, fg_color="transparent")
        manual_entry_row.pack(fill="x", padx=10, pady=(0, 6))

        self.manual_callback_entry = HubEntry(
            manual_entry_row,
            placeholder_text="http://127.0.0.1:49725/oauth-callback?state=...&code=...",
            font=Theme.font_mono(),
            height=32,
            fg_color=Theme.PRIMARY,
            border_color=Theme.BORDER,
            text_color=Theme.TEXT_PRIMARY,
        )
        self.manual_callback_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

        HubButton(
            manual_entry_row,
            text="📋 Вставить",
            variant="secondary",
            width=80,
            height=32,
            command=lambda: self._paste_into_entry(self.manual_callback_entry),
        ).pack(side="right")

        self.manual_submit_btn = HubButton(
            manual_card,
            text="✓ Завершить авторизацию",
            variant="secondary",
            height=30,
            command=self._handle_manual_callback_submit,
        )
        self.manual_submit_btn.pack(anchor="w", padx=10, pady=(0, 6))

        # Status text
        self.oauth_status_lbl = ctk.CTkLabel(
            self.body,
            text="Создание сессии авторизации...",
            font=Theme.font_body(),
            text_color=Theme.TEXT_SECONDARY,
            anchor="w",
        )
        self.oauth_status_lbl.pack(fill="x", pady=4)

        self._build_step_2_footer()
        self._init_antigravity_oauth()

    def _init_antigravity_oauth(self):
        try:
            from antigravity_provider.router.profile_oauth import start_profile_oauth

            session_id, auth_url, port = start_profile_oauth(self.target_slot)
            self.oauth_session_id = session_id
            self.oauth_url = auth_url
            self.oauth_port = port

            self.oauth_url_entry.delete(0, "end")
            self.oauth_url_entry.insert(0, auth_url)

            self.oauth_status_lbl.configure(
                text="Ожидание завершения авторизации в браузере...",
                text_color=Theme.TEXT_SECONDARY,
            )

            self._polling_active = True
            threading.Thread(target=self._poll_antigravity_oauth, daemon=True).start()
        except Exception as e:
            self.oauth_status_lbl.configure(
                text=f"Ошибка создания сессии: {e}",
                text_color=Theme.STATUS_ERROR,
            )

    def _copy_oauth_url(self):
        if self.oauth_url:
            self.clipboard_clear()
            self.clipboard_append(self.oauth_url)
            self.copy_url_btn.configure(text="✓")
            self.after(2000, lambda: self.copy_url_btn.configure(text="📋"))

    def _open_oauth_browser(self):
        if self.oauth_url:
            webbrowser.open(self.oauth_url)

    def _handle_manual_callback_submit(self):
        raw_url = self.manual_callback_entry.get().strip()
        if not raw_url:
            self.oauth_status_lbl.configure(text="❌ Вставьте полный URL callback", text_color=Theme.STATUS_ERROR)
            return

        from antigravity_provider.router.profile_oauth import get_oauth_session

        session = get_oauth_session(self.oauth_session_id)
        if not session:
            self.oauth_status_lbl.configure(text="❌ Сессия не найдена", text_color=Theme.STATUS_ERROR)
            return

        ok, msg = session.handle_manual_callback_url(raw_url)
        if ok:
            info = getattr(session, "completed_profile_info", {}) or {}
            self.discovered_identity = info.get("email") or "Google Account"
            self.discovered_plan = "PRO"
            self.discovered_models = ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-thinking"]
            self.is_verified = True
            self._show_step_3_validation()
        else:
            self.oauth_status_lbl.configure(text=f"❌ {msg}", text_color=Theme.STATUS_ERROR)

    def _poll_antigravity_oauth(self):
        from antigravity_provider.router.profile_oauth import get_oauth_session

        for _ in range(300):
            if not self._polling_active:
                return
            time.sleep(1)
            session = get_oauth_session(self.oauth_session_id)
            if not session:
                continue

            status = getattr(session, "status", "").lower()
            if status in ("completed", "success"):
                info = getattr(session, "completed_profile_info", {}) or {}
                self.discovered_identity = info.get("email") or "Google Account"
                self.discovered_plan = "PRO"
                self.discovered_models = ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-thinking"]
                self.is_verified = True
                self.after(0, self._show_step_3_validation)
                return
            elif status in ("error", "failed", "cancelled"):
                err_msg = getattr(session, "error_msg", None) or "Авторизация не удалась"
                self.after(
                    0, lambda m=err_msg: self.oauth_status_lbl.configure(text=f"❌ {m}", text_color=Theme.STATUS_ERROR)
                )
                return

    # ─────────────────────────────────────────────────────────────
    #  OPENAI CODEX OAUTH FLOW
    # ─────────────────────────────────────────────────────────────

    def _build_codex_oauth_flow(self):
        mode_card = HubCard(self.body, fg_color="transparent")
        mode_card.pack(fill="x", pady=(0, 8))

        self.codex_mode_var = ctk.StringVar(value="oauth")

        rb1 = ctk.CTkRadioButton(
            mode_card,
            text="OAuth — OpenAI / ChatGPT аккаунт (Рекомендуется)",
            value="oauth",
            variable=self.codex_mode_var,
            font=Theme.font_body_bold(),
            fg_color=Theme.ACCENT,
            command=self._on_codex_mode_toggle,
        )
        rb1.pack(anchor="w", padx=4, pady=2)

        rb2 = ctk.CTkRadioButton(
            mode_card,
            text="API Key — OpenAI API (sk-...)",
            value="api_key",
            variable=self.codex_mode_var,
            font=Theme.font_body(),
            fg_color=Theme.ACCENT,
            command=self._on_codex_mode_toggle,
        )
        rb2.pack(anchor="w", padx=4, pady=2)

        auth_card = HubCard(self.body, fg_color=Theme.SURFACE_MUTED)
        auth_card.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(
            auth_card,
            text="Ссылка для входа в OpenAI (ChatGPT):",
            font=Theme.font_caption(),
            text_color=Theme.TEXT_SECONDARY,
        ).pack(anchor="w", padx=10, pady=(6, 2))

        url_row = ctk.CTkFrame(auth_card, fg_color="transparent")
        url_row.pack(fill="x", padx=10, pady=(0, 6))

        self.codex_url_entry = HubEntry(
            url_row,
            font=Theme.font_mono(),
            height=32,
            fg_color=Theme.PRIMARY,
            border_color=Theme.BORDER,
            text_color=Theme.TEXT_PRIMARY,
        )
        self.codex_url_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

        HubButton(
            url_row,
            text="📋",
            variant="secondary",
            width=40,
            height=32,
            command=self._copy_codex_url,
        ).pack(side="right")

        code_card = ctk.CTkFrame(auth_card, fg_color="transparent")
        code_card.pack(fill="x", padx=10, pady=(0, 6))

        ctk.CTkLabel(
            code_card,
            text="Код подтверждения:",
            font=Theme.font_body_bold(),
            text_color=Theme.TEXT_PRIMARY,
        ).pack(side="left", padx=(0, 8))

        self.codex_code_lbl = ctk.CTkLabel(
            code_card,
            text="...",
            font=Theme.font_mono_bold(),
            text_color=Theme.ACCENT,
        )
        self.codex_code_lbl.pack(side="left", padx=(0, 8))

        HubButton(
            code_card,
            text="📋 Копировать код",
            variant="secondary",
            width=130,
            height=28,
            command=self._copy_codex_code,
        ).pack(side="left")

        action_row = ctk.CTkFrame(auth_card, fg_color="transparent")
        action_row.pack(fill="x", padx=10, pady=(0, 8))

        HubButton(
            action_row,
            text="🌐 Открыть в браузере",
            variant="primary",
            width=180,
            command=self._open_codex_browser,
        ).pack(side="left", padx=(0, 8))

        # Manual Fallback Card
        manual_card = HubCard(self.body, fg_color=Theme.SURFACE_MUTED)
        manual_card.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(
            manual_card,
            text="▸ Вставить токен вручную:",
            font=Theme.font_body_bold(),
            text_color=Theme.TEXT_PRIMARY,
            anchor="w",
        ).pack(fill="x", padx=10, pady=(6, 2))

        manual_entry_row = ctk.CTkFrame(manual_card, fg_color="transparent")
        manual_entry_row.pack(fill="x", padx=10, pady=(0, 6))

        self.codex_manual_entry = HubEntry(
            manual_entry_row,
            placeholder_text='{"access_token": "..."} или токен...',
            font=Theme.font_mono(),
            height=32,
            fg_color=Theme.PRIMARY,
            border_color=Theme.BORDER,
            text_color=Theme.TEXT_PRIMARY,
        )
        self.codex_manual_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

        HubButton(
            manual_entry_row,
            text="📋 Вставить",
            variant="secondary",
            width=80,
            height=32,
            command=lambda: self._paste_into_entry(self.codex_manual_entry),
        ).pack(side="right")

        HubButton(
            manual_card,
            text="✓ Завершить авторизацию",
            variant="secondary",
            height=30,
            command=self._handle_codex_manual_submit,
        ).pack(anchor="w", padx=10, pady=(0, 6))

        self.codex_status_lbl = ctk.CTkLabel(
            self.body,
            text="Создание сессии входа OpenAI...",
            font=Theme.font_body(),
            text_color=Theme.TEXT_SECONDARY,
            anchor="w",
        )
        self.codex_status_lbl.pack(fill="x", pady=4)

        self._build_step_2_footer()
        self._init_codex_oauth()

    def _on_codex_mode_toggle(self):
        self.codex_auth_mode = self.codex_mode_var.get()
        self._show_step_2_auth()

    def _init_codex_oauth(self):
        try:
            from antigravity_provider.router.codex_oauth import start_codex_oauth, get_codex_oauth_session

            session_id, url, code = start_codex_oauth(self.target_slot)
            self.codex_session_id = session_id
            self.codex_url = url
            self.codex_user_code = code

            session = get_codex_oauth_session(session_id)
            if not code or (session and session.status == "failed"):
                err_msg = getattr(session, "error_msg", None) or "Не удалось получить код авторизации"
                self.codex_status_lbl.configure(text=f"❌ {err_msg}", text_color=Theme.STATUS_ERROR)
                return

            self.codex_url_entry.delete(0, "end")
            self.codex_url_entry.insert(0, url)
            self.codex_code_lbl.configure(text=code)

            if getattr(session, "is_dev_mode", False):
                self.codex_status_lbl.configure(
                    text=f"⚠️ ТЕСТОВЫЙ РЕЖИМ (HERMES_HUB_DEV_MODE): Код {code}",
                    text_color=Theme.STATUS_WARNING,
                )
            else:
                self.codex_status_lbl.configure(
                    text=f"Ожидание подтверждения кода {code} в браузере...",
                    text_color=Theme.TEXT_SECONDARY,
                )

            self._polling_active = True
            threading.Thread(target=self._poll_codex_oauth, daemon=True).start()
        except Exception as e:
            self.codex_status_lbl.configure(text=f"Ошибка: {e}", text_color=Theme.STATUS_ERROR)

    def _copy_codex_url(self):
        if self.codex_url:
            self.clipboard_clear()
            self.clipboard_append(self.codex_url)

    def _copy_codex_code(self):
        if self.codex_user_code:
            self.clipboard_clear()
            self.clipboard_append(self.codex_user_code)

    def _open_codex_browser(self):
        if self.codex_url:
            webbrowser.open(self.codex_url)

    def _handle_codex_manual_submit(self):
        raw = self.codex_manual_entry.get().strip()
        if not raw:
            self.codex_status_lbl.configure(text="❌ Введите данные токена", text_color=Theme.STATUS_ERROR)
            return

        from antigravity_provider.router.codex_oauth import get_codex_oauth_session

        session = get_codex_oauth_session(self.codex_session_id)
        if not session:
            self.codex_status_lbl.configure(text="❌ Сессия не найдена", text_color=Theme.STATUS_ERROR)
            return

        ok, msg = session.handle_manual_input(raw)
        if ok:
            info = getattr(session, "completed_profile_info", {}) or {}
            self.discovered_identity = info.get("email") or "ChatGPT Account"
            self.discovered_plan = "PLUS"
            self.discovered_models = ["gpt-4o", "o3-mini", "gpt-4o-mini", "codex"]
            self.is_verified = True
            self._show_step_3_validation()
        else:
            self.codex_status_lbl.configure(text=f"❌ {msg}", text_color=Theme.STATUS_ERROR)

    def _poll_codex_oauth(self):
        from antigravity_provider.router.codex_oauth import get_codex_oauth_session

        for _ in range(900):
            if not self._polling_active:
                return
            time.sleep(1)
            session = get_codex_oauth_session(self.codex_session_id)
            if not session:
                continue

            status = getattr(session, "status", "").lower()
            if status in ("completed", "success"):
                info = getattr(session, "completed_profile_info", {}) or {}
                self.discovered_identity = info.get("email") or "ChatGPT Account"
                self.discovered_plan = "PLUS"
                self.discovered_models = ["gpt-4o", "o3-mini", "gpt-4o-mini", "codex"]
                self.is_verified = True
                self.after(0, self._show_step_3_validation)
                return

    # ─────────────────────────────────────────────────────────────
    #  CLAUDE (ANTHROPIC) OAUTH FLOW
    # ─────────────────────────────────────────────────────────────

    def _build_claude_oauth_flow(self):
        mode_card = HubCard(self.body, fg_color="transparent")
        mode_card.pack(fill="x", pady=(0, 8))

        self.claude_mode_var = ctk.StringVar(value="oauth")

        rb1 = ctk.CTkRadioButton(
            mode_card,
            text="OAuth — Claude Pro/Max Account (Рекомендуется)",
            value="oauth",
            variable=self.claude_mode_var,
            font=Theme.font_body_bold(),
            fg_color=Theme.PROVIDER_CLAUDE,
            command=self._on_claude_mode_toggle,
        )
        rb1.pack(anchor="w", padx=4, pady=2)

        rb2 = ctk.CTkRadioButton(
            mode_card,
            text="API Key — Anthropic API (sk-ant-...)",
            value="api_key",
            variable=self.claude_mode_var,
            font=Theme.font_body(),
            fg_color=Theme.PROVIDER_CLAUDE,
            command=self._on_claude_mode_toggle,
        )
        rb2.pack(anchor="w", padx=4, pady=2)

        auth_card = HubCard(self.body, fg_color=Theme.SURFACE_MUTED)
        auth_card.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(
            auth_card,
            text="Ссылка для входа в Claude:",
            font=Theme.font_caption(),
            text_color=Theme.TEXT_SECONDARY,
        ).pack(anchor="w", padx=10, pady=(6, 2))

        url_row = ctk.CTkFrame(auth_card, fg_color="transparent")
        url_row.pack(fill="x", padx=10, pady=(0, 6))

        self.claude_url_entry = HubEntry(
            url_row,
            font=Theme.font_mono(),
            height=32,
            fg_color=Theme.PRIMARY,
            border_color=Theme.BORDER,
            text_color=Theme.TEXT_PRIMARY,
        )
        self.claude_url_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

        HubButton(
            url_row,
            text="📋",
            variant="secondary",
            width=40,
            height=32,
            command=self._copy_claude_url,
        ).pack(side="right")

        action_row = ctk.CTkFrame(auth_card, fg_color="transparent")
        action_row.pack(fill="x", padx=10, pady=(0, 8))

        HubButton(
            action_row,
            text="🌐 Открыть в браузере",
            variant="primary",
            width=180,
            command=self._open_claude_browser,
        ).pack(side="left", padx=(0, 8))

        # Code Entry Card
        code_card = HubCard(self.body, fg_color=Theme.SURFACE_MUTED)
        code_card.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(
            code_card,
            text="Вставьте код авторизации после входа на сайте Claude:",
            font=Theme.font_body_bold(),
            text_color=Theme.TEXT_PRIMARY,
            anchor="w",
        ).pack(fill="x", padx=10, pady=(6, 2))

        code_row = ctk.CTkFrame(code_card, fg_color="transparent")
        code_row.pack(fill="x", padx=10, pady=(0, 6))

        self.claude_code_entry = HubEntry(
            code_row,
            placeholder_text="Вставьте код...",
            font=Theme.font_mono(),
            height=32,
            fg_color=Theme.PRIMARY,
            border_color=Theme.BORDER,
            text_color=Theme.TEXT_PRIMARY,
        )
        self.claude_code_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

        HubButton(
            code_row,
            text="📋 Вставить",
            variant="secondary",
            width=80,
            height=32,
            command=lambda: self._paste_into_entry(self.claude_code_entry),
        ).pack(side="right")

        HubButton(
            code_card,
            text="✓ Завершить авторизацию",
            variant="secondary",
            height=30,
            command=self._handle_claude_code_submit,
        ).pack(anchor="w", padx=10, pady=(0, 6))

        self.claude_status_lbl = ctk.CTkLabel(
            self.body,
            text="Создание ссылки входа Claude...",
            font=Theme.font_body(),
            text_color=Theme.TEXT_SECONDARY,
            anchor="w",
        )
        self.claude_status_lbl.pack(fill="x", pady=4)

        self._build_step_2_footer()
        self._init_claude_oauth()

    def _on_claude_mode_toggle(self):
        self.claude_auth_mode = self.claude_mode_var.get()
        self._show_step_2_auth()

    def _init_claude_oauth(self):
        try:
            from antigravity_provider.router.claude_oauth import start_claude_oauth

            session_id, url = start_claude_oauth(self.target_slot)
            self.claude_session_id = session_id
            self.claude_url = url

            self.claude_url_entry.delete(0, "end")
            self.claude_url_entry.insert(0, url)
            self.claude_status_lbl.configure(text="Перейдите по ссылке и скопируйте код авторизации.")
        except Exception as e:
            self.claude_status_lbl.configure(text=f"Ошибка: {e}", text_color=Theme.STATUS_ERROR)

    def _copy_claude_url(self):
        if self.claude_url:
            self.clipboard_clear()
            self.clipboard_append(self.claude_url)

    def _open_claude_browser(self):
        if self.claude_url:
            webbrowser.open(self.claude_url)

    def _handle_claude_code_submit(self):
        raw = self.claude_code_entry.get().strip()
        if not raw:
            self.claude_status_lbl.configure(text="❌ Вставьте код авторизации", text_color=Theme.STATUS_ERROR)
            return

        from antigravity_provider.router.claude_oauth import get_claude_oauth_session

        session = get_claude_oauth_session(self.claude_session_id)
        if not session:
            self.claude_status_lbl.configure(text="❌ Сессия не найдена", text_color=Theme.STATUS_ERROR)
            return

        ok, msg = session.handle_auth_code(raw)
        if ok:
            info = getattr(session, "completed_profile_info", {}) or {}
            self.discovered_identity = info.get("email") or "Claude Account"
            self.discovered_plan = "MAX"
            self.discovered_models = ["claude-3-7-sonnet", "claude-3-5-sonnet", "claude-3-5-haiku", "claude-3-opus"]
            self.is_verified = True
            self._show_step_3_validation()
        else:
            self.claude_status_lbl.configure(text=f"❌ {msg}", text_color=Theme.STATUS_ERROR)

    # ─────────────────────────────────────────────────────────────
    #  GROK (XAI) OAUTH FLOW
    # ─────────────────────────────────────────────────────────────

    def _build_grok_oauth_flow(self):
        mode_card = HubCard(self.body, fg_color="transparent")
        mode_card.pack(fill="x", pady=(0, 8))

        self.grok_mode_var = ctk.StringVar(value="oauth")

        rb1 = ctk.CTkRadioButton(
            mode_card,
            text="OAuth — xAI / SuperGrok Account (Рекомендуется)",
            value="oauth",
            variable=self.grok_mode_var,
            font=Theme.font_body_bold(),
            fg_color=Theme.PROVIDER_GROK,
            command=self._on_grok_mode_toggle,
        )
        rb1.pack(anchor="w", padx=4, pady=2)

        rb2 = ctk.CTkRadioButton(
            mode_card,
            text="API Key — xAI API (xai-...)",
            value="api_key",
            variable=self.grok_mode_var,
            font=Theme.font_body(),
            fg_color=Theme.PROVIDER_GROK,
            command=self._on_grok_mode_toggle,
        )
        rb2.pack(anchor="w", padx=4, pady=2)

        auth_card = HubCard(self.body, fg_color=Theme.SURFACE_MUTED)
        auth_card.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(
            auth_card,
            text="Ссылка для входа в xAI Grok:",
            font=Theme.font_caption(),
            text_color=Theme.TEXT_SECONDARY,
        ).pack(anchor="w", padx=10, pady=(6, 2))

        url_row = ctk.CTkFrame(auth_card, fg_color="transparent")
        url_row.pack(fill="x", padx=10, pady=(0, 6))

        self.grok_url_entry = HubEntry(
            url_row,
            font=Theme.font_mono(),
            height=32,
            fg_color=Theme.PRIMARY,
            border_color=Theme.BORDER,
            text_color=Theme.TEXT_PRIMARY,
        )
        self.grok_url_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

        HubButton(
            url_row,
            text="📋",
            variant="secondary",
            width=40,
            height=32,
            command=self._copy_grok_url,
        ).pack(side="right")

        code_card = ctk.CTkFrame(auth_card, fg_color="transparent")
        code_card.pack(fill="x", padx=10, pady=(0, 6))

        ctk.CTkLabel(
            code_card,
            text="Код подтверждения:",
            font=Theme.font_body_bold(),
            text_color=Theme.TEXT_PRIMARY,
        ).pack(side="left", padx=(0, 8))

        self.grok_code_lbl = ctk.CTkLabel(
            code_card,
            text="...",
            font=Theme.font_mono_bold(),
            text_color=Theme.PROVIDER_GROK,
        )
        self.grok_code_lbl.pack(side="left", padx=(0, 8))

        HubButton(
            code_card,
            text="📋 Копировать код",
            variant="secondary",
            width=130,
            height=28,
            command=self._copy_grok_code,
        ).pack(side="left")

        action_row = ctk.CTkFrame(auth_card, fg_color="transparent")
        action_row.pack(fill="x", padx=10, pady=(0, 8))

        HubButton(
            action_row,
            text="🌐 Открыть в браузере",
            variant="primary",
            width=180,
            command=self._open_grok_browser,
        ).pack(side="left", padx=(0, 8))

        # Manual Entry Card
        manual_card = HubCard(self.body, fg_color=Theme.SURFACE_MUTED)
        manual_card.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(
            manual_card,
            text="▸ Вставить токен вручную:",
            font=Theme.font_body_bold(),
            text_color=Theme.TEXT_PRIMARY,
            anchor="w",
        ).pack(fill="x", padx=10, pady=(6, 2))

        manual_entry_row = ctk.CTkFrame(manual_card, fg_color="transparent")
        manual_entry_row.pack(fill="x", padx=10, pady=(0, 6))

        self.grok_manual_entry = HubEntry(
            manual_entry_row,
            placeholder_text='{"access_token": "..."} или токен...',
            font=Theme.font_mono(),
            height=32,
            fg_color=Theme.PRIMARY,
            border_color=Theme.BORDER,
            text_color=Theme.TEXT_PRIMARY,
        )
        self.grok_manual_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

        HubButton(
            manual_entry_row,
            text="📋 Вставить",
            variant="secondary",
            width=80,
            height=32,
            command=lambda: self._paste_into_entry(self.grok_manual_entry),
        ).pack(side="right")

        HubButton(
            manual_card,
            text="✓ Завершить авторизацию",
            variant="secondary",
            height=30,
            command=self._handle_grok_manual_submit,
        ).pack(anchor="w", padx=10, pady=(0, 6))

        self.grok_status_lbl = ctk.CTkLabel(
            self.body,
            text="Создание сессии xAI Grok...",
            font=Theme.font_body(),
            text_color=Theme.TEXT_SECONDARY,
            anchor="w",
        )
        self.grok_status_lbl.pack(fill="x", pady=4)

        self._build_step_2_footer()
        self._init_grok_oauth()

    def _on_grok_mode_toggle(self):
        self.grok_auth_mode = self.grok_mode_var.get()
        self._show_step_2_auth()

    def _init_grok_oauth(self):
        try:
            from antigravity_provider.router.grok_oauth import start_grok_oauth, get_grok_oauth_session

            session_id, url, code = start_grok_oauth(self.target_slot)
            self.grok_session_id = session_id
            self.grok_url = url
            self.grok_user_code = code

            session = get_grok_oauth_session(session_id)
            if not code or (session and session.status == "failed"):
                err_msg = getattr(session, "error_msg", None) or "Не удалось получить код авторизации"
                self.grok_status_lbl.configure(text=f"❌ {err_msg}", text_color=Theme.STATUS_ERROR)
                return

            self.grok_url_entry.delete(0, "end")
            self.grok_url_entry.insert(0, url)
            self.grok_code_lbl.configure(text=code)

            if getattr(session, "is_dev_mode", False):
                self.grok_status_lbl.configure(
                    text=f"⚠️ ТЕСТОВЫЙ РЕЖИМ (HERMES_HUB_DEV_MODE): Код {code}",
                    text_color=Theme.STATUS_WARNING,
                )
            else:
                self.grok_status_lbl.configure(
                    text=f"Ожидание подтверждения кода {code} в браузере...",
                    text_color=Theme.TEXT_SECONDARY,
                )

            self._polling_active = True
            threading.Thread(target=self._poll_grok_oauth, daemon=True).start()
        except Exception as e:
            self.grok_status_lbl.configure(text=f"Ошибка: {e}", text_color=Theme.STATUS_ERROR)

    def _copy_grok_url(self):
        if self.grok_url:
            self.clipboard_clear()
            self.clipboard_append(self.grok_url)

    def _copy_grok_code(self):
        if self.grok_user_code:
            self.clipboard_clear()
            self.clipboard_append(self.grok_user_code)

    def _open_grok_browser(self):
        if self.grok_url:
            webbrowser.open(self.grok_url)

    def _handle_grok_manual_submit(self):
        raw = self.grok_manual_entry.get().strip()
        if not raw:
            self.grok_status_lbl.configure(text="❌ Введите данные токена", text_color=Theme.STATUS_ERROR)
            return

        from antigravity_provider.router.grok_oauth import get_grok_oauth_session

        session = get_grok_oauth_session(self.grok_session_id)
        if not session:
            self.grok_status_lbl.configure(text="❌ Сессия не найдена", text_color=Theme.STATUS_ERROR)
            return

        ok, msg = session.handle_manual_input(raw)
        if ok:
            info = getattr(session, "completed_profile_info", {}) or {}
            self.discovered_identity = info.get("email") or "Grok Account"
            self.discovered_plan = "Grok Pro"
            self.discovered_models = ["grok-3", "grok-3-mini", "grok-2"]
            self.is_verified = True
            self._show_step_3_validation()
        else:
            self.grok_status_lbl.configure(text=f"❌ {msg}", text_color=Theme.STATUS_ERROR)

    def _poll_grok_oauth(self):
        from antigravity_provider.router.grok_oauth import get_grok_oauth_session

        for _ in range(900):
            if not self._polling_active:
                return
            time.sleep(1)
            session = get_grok_oauth_session(self.grok_session_id)
            if not session:
                continue

            status = getattr(session, "status", "").lower()
            if status in ("completed", "success"):
                info = getattr(session, "completed_profile_info", {}) or {}
                self.discovered_identity = info.get("email") or "Grok Account"
                self.discovered_plan = "Grok Pro"
                self.discovered_models = ["grok-3", "grok-3-mini", "grok-2"]
                self.is_verified = True
                self.after(0, self._show_step_3_validation)
                return

    # ─────────────────────────────────────────────────────────────
    #  API KEY FLOW
    # ─────────────────────────────────────────────────────────────

    def _build_api_key_flow(self):
        # Mode switchers for Codex, Claude, Grok
        if self.selected_provider == "openai-codex":
            mode_card = HubCard(self.body, fg_color="transparent")
            mode_card.pack(fill="x", pady=(0, 8))
            self.codex_mode_var = ctk.StringVar(value="api_key")
            ctk.CTkRadioButton(
                mode_card,
                text="OAuth — OpenAI / ChatGPT",
                value="oauth",
                variable=self.codex_mode_var,
                font=Theme.font_body(),
                fg_color=Theme.ACCENT,
                command=self._on_codex_mode_toggle,
            ).pack(anchor="w", padx=4, pady=2)
            ctk.CTkRadioButton(
                mode_card,
                text="API Key — OpenAI API (sk-...)",
                value="api_key",
                variable=self.codex_mode_var,
                font=Theme.font_body_bold(),
                fg_color=Theme.ACCENT,
                command=self._on_codex_mode_toggle,
            ).pack(anchor="w", padx=4, pady=2)
        elif self.selected_provider == "claude":
            mode_card = HubCard(self.body, fg_color="transparent")
            mode_card.pack(fill="x", pady=(0, 8))
            self.claude_mode_var = ctk.StringVar(value="api_key")
            ctk.CTkRadioButton(
                mode_card,
                text="OAuth — Claude Pro/Max",
                value="oauth",
                variable=self.claude_mode_var,
                font=Theme.font_body(),
                fg_color=Theme.PROVIDER_CLAUDE,
                command=self._on_claude_mode_toggle,
            ).pack(anchor="w", padx=4, pady=2)
            ctk.CTkRadioButton(
                mode_card,
                text="API Key — Anthropic API (sk-ant-...)",
                value="api_key",
                variable=self.claude_mode_var,
                font=Theme.font_body_bold(),
                fg_color=Theme.PROVIDER_CLAUDE,
                command=self._on_claude_mode_toggle,
            ).pack(anchor="w", padx=4, pady=2)
        elif self.selected_provider == "grok":
            mode_card = HubCard(self.body, fg_color="transparent")
            mode_card.pack(fill="x", pady=(0, 8))
            self.grok_mode_var = ctk.StringVar(value="api_key")
            ctk.CTkRadioButton(
                mode_card,
                text="OAuth — xAI / SuperGrok",
                value="oauth",
                variable=self.grok_mode_var,
                font=Theme.font_body(),
                fg_color=Theme.PROVIDER_GROK,
                command=self._on_grok_mode_toggle,
            ).pack(anchor="w", padx=4, pady=2)
            ctk.CTkRadioButton(
                mode_card,
                text="API Key — xAI API (xai-...)",
                value="api_key",
                variable=self.grok_mode_var,
                font=Theme.font_body_bold(),
                fg_color=Theme.PROVIDER_GROK,
                command=self._on_grok_mode_toggle,
            ).pack(anchor="w", padx=4, pady=2)

        prompt_map = {
            "openai-codex": "Введите ключ OpenAI API (sk-...):",
            "claude": "Введите ключ Anthropic API (sk-ant-...):",
            "grok": "Введите ключ xAI API (xai-...):",
            "opencode-go": "Введите ключ API / Bearer Token для OpenCode Go:",
        }
        ctk.CTkLabel(
            self.body,
            text=prompt_map.get(self.selected_provider, "Введите ключ API:"),
            font=Theme.font_body(),
            text_color=Theme.TEXT_SECONDARY,
        ).pack(anchor="w", pady=(0, 6))

        entry_row = ctk.CTkFrame(self.body, fg_color="transparent")
        entry_row.pack(fill="x", pady=(0, 8))

        placeholder_map = {
            "openai-codex": "sk-...",
            "claude": "sk-ant-...",
            "grok": "xai-...",
            "opencode-go": "opencode-...",
        }
        self.key_entry = HubEntry(
            entry_row,
            placeholder_text=placeholder_map.get(self.selected_provider, "sk-..."),
            font=Theme.font_mono(),
            show="*",
            height=38,
            fg_color=Theme.PRIMARY,
            border_color=Theme.BORDER,
            text_color=Theme.TEXT_PRIMARY,
        )
        self.key_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        HubButton(
            entry_row,
            text="📋 Вставить",
            variant="secondary",
            width=90,
            height=38,
            command=lambda: self._paste_into_entry(self.key_entry),
        ).pack(side="right")

        self.key_status_lbl = ctk.CTkLabel(
            self.body,
            text="",
            font=Theme.font_caption(),
            text_color=Theme.STATUS_ERROR,
        )
        self.key_status_lbl.pack(anchor="w")

        def _save_key():
            k = self.key_entry.get().strip()
            if not k:
                self.key_status_lbl.configure(text="Пожалуйста, введите ключ API.")
                return

            is_valid = False
            masked_id = None
            models: List[str] = []

            if self.selected_provider == "openai-codex":
                is_valid, masked_id, models = ProfileAuthManager.verify_codex_token(k)
                self.discovered_plan = "PLUS"
            elif self.selected_provider == "claude":
                is_valid, masked_id, models = ProfileAuthManager.verify_claude_token(k)
                self.discovered_plan = "MAX"
            elif self.selected_provider == "grok":
                is_valid, masked_id, models = ProfileAuthManager.verify_grok_token(k)
                self.discovered_plan = "Grok Pro"
            elif self.selected_provider == "opencode-go":
                is_valid, masked_id, models = ProfileAuthManager.verify_opencode_token(k)
                self.discovered_plan = "SUBSCRIPTION"

            auth_data = {
                "provider": self.selected_provider,
                "profile_id": self.target_slot,
                "auth_mode": "api_key",
                "api_key": k,
                "created_at": time.time(),
            }
            ProfileAuthManager.save_profile_auth(self.selected_provider, self.target_slot, auth_data)

            self.is_verified = is_valid
            self.discovered_identity = masked_id or (k[:8] + "..." + k[-4:] if len(k) > 12 else "API Key")
            self.discovered_models = models if is_valid else []
            self._show_step_3_validation()

        self._build_step_2_footer(next_cmd=_save_key)

    def _build_step_2_footer(self, next_cmd: Optional[Callable] = None):
        HubButton(
            self.footer,
            text="← Назад",
            variant="ghost",
            command=self._show_step_1_provider,
        ).pack(side="left", padx=10, pady=10)

        if next_cmd:
            HubButton(
                self.footer,
                text="Проверить и продолжить →",
                variant="primary",
                command=next_cmd,
            ).pack(side="right", padx=10, pady=10)

    def _paste_into_entry(self, entry_widget: HubEntry):
        try:
            content = self.clipboard_get().strip()
            if content:
                entry_widget.delete(0, "end")
                entry_widget.insert(0, content)
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════════
    #  STEP 3: Validation & Identity
    # ═══════════════════════════════════════════════════════════════

    def _show_step_3_validation(self):
        self._polling_active = False
        self._clear_body()
        self.step = 3
        self.title_lbl.configure(text="Шаг 3 из 4: Проверка учетной записи")

        # Duplicate check
        dup_profile = AutoAssigner.check_duplicate_identity(
            self.selected_provider,
            self.discovered_identity,
            exclude_profile_id=self.target_slot,
        )

        card = HubCard(self.body)
        card.pack(fill="x", pady=10)

        ctk.CTkLabel(
            card,
            text="Результат проверки подключения:",
            font=Theme.font_body_bold(),
            text_color=Theme.TEXT_PRIMARY,
        ).pack(anchor="w", padx=14, pady=(10, 6))

        # Identity line
        id_row = ctk.CTkFrame(card, fg_color="transparent")
        id_row.pack(fill="x", padx=14, pady=2)
        ctk.CTkLabel(id_row, text="Идентификатор:", font=Theme.font_caption(), text_color=Theme.TEXT_SECONDARY).pack(
            side="left"
        )
        ctk.CTkLabel(
            id_row, text=self.discovered_identity or "—", font=Theme.font_body_bold(), text_color=Theme.TEXT_PRIMARY
        ).pack(side="right")

        # Plan line
        plan_row = ctk.CTkFrame(card, fg_color="transparent")
        plan_row.pack(fill="x", padx=14, pady=2)
        ctk.CTkLabel(plan_row, text="Тариф:", font=Theme.font_caption(), text_color=Theme.TEXT_SECONDARY).pack(
            side="left"
        )
        ctk.CTkLabel(
            plan_row,
            text=self.discovered_plan or "Тариф: неизвестен",
            font=Theme.font_body_bold(),
            text_color=Theme.ACCENT,
        ).pack(side="right")

        # Status line
        stat_row = ctk.CTkFrame(card, fg_color="transparent")
        stat_row.pack(fill="x", padx=14, pady=2)
        ctk.CTkLabel(
            stat_row, text="Статус проверки:", font=Theme.font_caption(), text_color=Theme.TEXT_SECONDARY
        ).pack(side="left")
        stat_lbl = "✓ Успешно авторизован" if self.is_verified else "Подключен (без проверки)"
        stat_col = Theme.STATUS_HEALTHY if self.is_verified else Theme.STATUS_WARNING
        ctk.CTkLabel(stat_row, text=stat_lbl, font=Theme.font_body_bold(), text_color=stat_col).pack(side="right")

        if dup_profile:
            warn_card = HubCard(self.body, border_color=Theme.STATUS_WARNING, fg_color=Theme.ACCENT_DIM)
            warn_card.pack(fill="x", pady=6)
            ctk.CTkLabel(
                warn_card,
                text=f"⚠️ Этот аккаунт уже подключен к слоту {dup_profile}.",
                font=Theme.font_caption(),
                text_color=Theme.STATUS_WARNING,
            ).pack(padx=10, pady=8)

        HubButton(
            self.footer,
            text="← Назад",
            variant="ghost",
            command=self._show_step_2_auth,
        ).pack(side="left", padx=10, pady=10)

        HubButton(
            self.footer,
            text="Продолжить к распределению роли →",
            variant="primary",
            command=self._show_step_4_assignment,
        ).pack(side="right", padx=10, pady=10)

    # ═══════════════════════════════════════════════════════════════
    #  STEP 4: Auto-Assignment & Completion
    # ═══════════════════════════════════════════════════════════════

    def _show_step_4_assignment(self):
        self._clear_body()
        self.step = 4
        self.title_lbl.configure(text="Шаг 4 из 4: Назначение роли в роутере")

        disp_name, role_code, tier = AutoAssigner.get_display_name_and_role(self.target_slot)

        card = HubCard(self.body)
        card.pack(fill="x", pady=10)

        ctk.CTkLabel(
            card,
            text="Назначенная роль в команде:",
            font=Theme.font_body_bold(),
            text_color=Theme.TEXT_PRIMARY,
        ).pack(anchor="w", padx=14, pady=(10, 6))

        r_row = ctk.CTkFrame(card, fg_color="transparent")
        r_row.pack(fill="x", padx=14, pady=4)
        ctk.CTkLabel(r_row, text="Роль агента:", font=Theme.font_caption(), text_color=Theme.TEXT_SECONDARY).pack(
            side="left"
        )
        ctk.CTkLabel(r_row, text=disp_name, font=Theme.font_heading(), text_color=Theme.TEXT_PRIMARY).pack(side="right")

        s_row = ctk.CTkFrame(card, fg_color="transparent")
        s_row.pack(fill="x", padx=14, pady=4)
        ctk.CTkLabel(s_row, text="Внутренний слот:", font=Theme.font_caption(), text_color=Theme.TEXT_SECONDARY).pack(
            side="left"
        )
        ctk.CTkLabel(s_row, text=self.target_slot, font=Theme.font_mono(), text_color=Theme.TEXT_MUTED).pack(
            side="right"
        )

        ctk.CTkLabel(
            self.body,
            text="Аккаунт готов к работе в роутере Hermes Hub и приему запросов.",
            font=Theme.font_caption(),
            text_color=Theme.TEXT_SECONDARY,
            anchor="w",
        ).pack(fill="x", pady=8)

        HubButton(
            self.footer,
            text="✓ Завершить подключение",
            variant="primary",
            command=self._finish,
        ).pack(side="right", padx=10, pady=10)

    def _finish(self):
        # Ни журналирование, ни обратный вызов не должны мешать закрытию окна:
        # исключение здесь оставляло мастер открытым без единого признака ошибки.
        try:
            EventLogService.get().log(
                "account",
                f"Подключен аккаунт {self.selected_provider}: {self.discovered_identity}",
                details=f"Слот: {self.target_slot}",
                level="success",
            )
        except Exception:
            pass

        if self.on_complete:
            try:
                self.on_complete(
                    {
                        "provider": self.selected_provider,
                        "profile_id": self.target_slot,
                        "identity": self.discovered_identity,
                    }
                )
            except Exception:
                pass

        self.destroy()
