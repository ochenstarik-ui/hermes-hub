"""Hermes Hub — Add Account Multi-Step Wizard Modal (v3).

Supports:
- Google Antigravity (Cockpit Tools model OAuth with immediate URL & manual fallback)
- OpenAI Codex (OAuth / ChatGPT Device Code flow + OpenAI API Key mode)
- OpenCode Go (API Key / Token input with clipboard Paste button & full keyboard shortcuts)
- Multi-account profile isolation & auto-assignment to router roles.
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
        super().__init__(parent, title="Мастер подключения аккаунта", width=640, height=540)
        self.on_complete = on_complete
        self.step = 1

        self.selected_provider: str = "antigravity"
        self.codex_auth_mode: str = "oauth"  # oauth | api_key
        self.target_slot: str = ""
        self.discovered_identity: str = ""
        self.discovered_models: List[str] = []
        self.is_verified: bool = False

        self.oauth_session_id: Optional[str] = None
        self.oauth_url: Optional[str] = None
        self.codex_session_id: Optional[str] = None
        self.codex_url: Optional[str] = None
        self.codex_user_code: Optional[str] = None
        self._polling_active = False

        self._show_step_1_provider()

    def destroy(self):
        self._polling_active = False
        if self.oauth_session_id:
            try:
                from antigravity_provider.router.profile_oauth import cancel_oauth_session
                cancel_oauth_session(self.oauth_session_id)
            except Exception:
                pass
        if self.codex_session_id:
            try:
                from antigravity_provider.router.codex_oauth import cancel_codex_oauth_session
                cancel_codex_oauth_session(self.codex_session_id)
            except Exception:
                pass
        super().destroy()

    def _clear_body(self):
        for w in self.body.winfo_children():
            w.destroy()
        for w in self.footer.winfo_children():
            w.destroy()

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
            ("openai-codex", "OpenAI Codex", "OAuth (ChatGPT) или API Key", "#10a37f"),
            ("opencode-go", "OpenCode Go", "API Key / Subscription", "#8b5cf6"),
        ]

        self.provider_var = ctk.StringVar(value=self.selected_provider)

        for p_id, p_title, p_desc, p_color in providers:
            card = HubCard(self.body)
            card.pack(fill="x", pady=4)

            rb = ctk.CTkRadioButton(
                card,
                text="",
                value=p_id,
                variable=self.provider_var,
                width=24,
                fg_color=Theme.ACCENT,
                hover_color=Theme.ACCENT_HOVER,
            )
            rb.pack(side="left", padx=(12, 8), pady=12)

            info_f = ctk.CTkFrame(card, fg_color="transparent")
            info_f.pack(side="left", fill="both", expand=True, pady=8)

            ctk.CTkLabel(
                info_f,
                text=p_title,
                font=Theme.font_body_bold(),
                text_color=Theme.TEXT_PRIMARY,
            ).pack(anchor="w")

            ctk.CTkLabel(
                info_f,
                text=p_desc,
                font=Theme.font_caption(),
                text_color=Theme.TEXT_SECONDARY,
            ).pack(anchor="w")

        HubButton(self.footer, text="Отмена", variant="secondary", width=100, command=self.destroy).pack(side="left")
        HubButton(self.footer, text="Далее ➔", variant="primary", width=140, command=self._on_provider_selected).pack(side="right")

    def _on_provider_selected(self):
        self.selected_provider = self.provider_var.get()
        self._show_step_2_auth()

    def _cancel_active_sessions(self):
        if self.oauth_session_id:
            try:
                from antigravity_provider.router.profile_oauth import cancel_oauth_session
                cancel_oauth_session(self.oauth_session_id)
            except Exception:
                pass
            self.oauth_session_id = None
            self.oauth_url = None

        if self.codex_session_id:
            try:
                from antigravity_provider.router.codex_oauth import cancel_codex_oauth_session
                cancel_codex_oauth_session(self.codex_session_id)
            except Exception:
                pass
            self.codex_session_id = None
            self.codex_url = None
            self.codex_user_code = None

    # ═══════════════════════════════════════════════════════════════
    #  STEP 2: Authentication
    # ═══════════════════════════════════════════════════════════════

    def _show_step_2_auth(self):
        self._clear_body()
        self.title_lbl.configure(text="Шаг 2 из 4: Авторизация учетной записи")

        # Find target slot
        self.target_slot = AutoAssigner.find_free_slot(self.selected_provider) or f"{self.selected_provider[:3]}-spare-1"

        if self.selected_provider == "antigravity":
            self._build_antigravity_oauth_flow()
        elif self.selected_provider == "openai-codex":
            if self.codex_auth_mode == "oauth":
                self._build_codex_oauth_flow()
            else:
                self._build_api_key_flow()
        else:
            self._build_api_key_flow()

    # ─────────────────────────────────────────────────────────────
    #  ANTIGRAVITY OAUTH FLOW
    # ─────────────────────────────────────────────────────────────

    def _build_antigravity_oauth_flow(self):
        ctk.CTkLabel(
            self.body,
            text="Для Google Antigravity требуется авторизация Google OAuth.",
            font=Theme.font_body_bold(),
            text_color=Theme.TEXT_PRIMARY,
            anchor="w",
        ).pack(fill="x", pady=(0, 2))

        ctk.CTkLabel(
            self.body,
            text="После входа Google автоматически вернёт результат авторизации в Hermes Hub.",
            font=Theme.font_caption(),
            text_color=Theme.TEXT_SECONDARY,
            wraplength=540,
            justify="left",
            anchor="w",
        ).pack(fill="x", pady=(0, 8))

        # 1. Authorization link card
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

        self.regen_btn = HubButton(
            action_row,
            text="🔄 Создать новую ссылку",
            variant="secondary",
            width=180,
            command=self._regenerate_oauth_session,
        )

        # 2. Manual Callback Fallback Card
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
            width=200,
            command=self._submit_manual_callback,
        )
        self.manual_submit_btn.pack(anchor="w", padx=10, pady=(0, 8))

        # Status label
        self.oauth_status_lbl = ctk.CTkLabel(
            self.body,
            text="Подготовка авторизации...",
            font=Theme.font_body_bold(),
            text_color=Theme.STATUS_WARNING,
        )
        self.oauth_status_lbl.pack(pady=(4, 0))

        HubButton(self.footer, text="⬅ Назад", variant="secondary", width=100, command=self._show_step_1_provider).pack(side="left")

        # Initialize session immediately
        self._init_antigravity_oauth_session()

    def _init_antigravity_oauth_session(self):
        try:
            from antigravity_provider.router.profile_oauth import start_profile_oauth
            self.oauth_session_id, self.oauth_url, self.oauth_port = start_profile_oauth(self.target_slot)
            self.oauth_url_entry.configure(state="normal")
            self.oauth_url_entry.delete(0, "end")
            self.oauth_url_entry.insert(0, self.oauth_url)
            self.oauth_url_entry.configure(state="readonly")
            self.oauth_status_lbl.configure(
                text="✓ Ссылка авторизации готова. Ожидание авторизации...",
                text_color=Theme.STATUS_HEALTHY,
            )
            if hasattr(self, "regen_btn") and self.regen_btn.winfo_exists():
                self.regen_btn.pack_forget()
            if hasattr(self, "manual_callback_entry"):
                self.manual_callback_entry.configure(state="normal")
                self.manual_callback_entry.delete(0, "end")
            if hasattr(self, "manual_submit_btn"):
                self.manual_submit_btn.configure(state="normal")
            self._polling_active = True
            threading.Thread(target=self._poll_antigravity_oauth, daemon=True).start()
        except Exception as e:
            self.oauth_status_lbl.configure(
                text=f"Не удалось запустить локальный OAuth callback: {e}",
                text_color=Theme.STATUS_ERROR,
            )
            if hasattr(self, "regen_btn") and self.regen_btn.winfo_exists():
                self.regen_btn.pack(side="left")

    def _open_oauth_browser(self):
        if not self.oauth_url:
            self._init_antigravity_oauth_session()
        if self.oauth_url:
            import logging
            logging.getLogger("hermes.router.profile_oauth").info(
                "OAUTH browser opening redirect_port=%d", getattr(self, "oauth_port", 51121)
            )
            webbrowser.open(self.oauth_url)
            self.oauth_status_lbl.configure(
                text="🌐 Браузер открыт. Ожидание завершения авторизации...",
                text_color=Theme.ACCENT,
            )

    def _copy_oauth_url(self):
        if self.oauth_url:
            self.clipboard_clear()
            self.clipboard_append(self.oauth_url)
            self.oauth_status_lbl.configure(
                text="✓ Ссылка скопирована",
                text_color=Theme.STATUS_HEALTHY,
            )

    def _regenerate_oauth_session(self):
        if self.oauth_session_id:
            try:
                from antigravity_provider.router.profile_oauth import cancel_oauth_session
                cancel_oauth_session(self.oauth_session_id)
            except Exception:
                pass
        self._init_antigravity_oauth_session()

    def _submit_manual_callback(self):
        raw_url = self.manual_callback_entry.get().strip()
        if not raw_url:
            self.oauth_status_lbl.configure(
                text="❌ Пожалуйста, вставьте полный URL из адресной строки браузера.",
                text_color=Theme.STATUS_ERROR,
            )
            return

        from antigravity_provider.router.profile_oauth import get_oauth_session
        session = get_oauth_session(self.oauth_session_id)
        if not session:
            self.oauth_status_lbl.configure(
                text="❌ Сессия авторизации не найдена. Создайте новую ссылку.",
                text_color=Theme.STATUS_ERROR,
            )
            if hasattr(self, "regen_btn") and self.regen_btn.winfo_exists():
                self.regen_btn.pack(side="left")
            return

        self.oauth_status_lbl.configure(
            text="Проверка авторизации...",
            text_color=Theme.ACCENT,
        )

        ok, msg = session.handle_manual_callback_url(raw_url)
        if ok:
            self.manual_callback_entry.configure(state="disabled")
            self.manual_submit_btn.configure(state="disabled")
            info = getattr(session, "completed_profile_info", {}) or {}
            self.discovered_identity = info.get("email") or "Google Account"
            self.discovered_models = ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-thinking"]
            self.is_verified = True
            self.oauth_status_lbl.configure(
                text=f"✓ Аккаунт подключен: {self.discovered_identity}",
                text_color=Theme.STATUS_HEALTHY,
            )
            self._show_step_3_validation()
        else:
            self.oauth_status_lbl.configure(
                text=f"❌ {msg}",
                text_color=Theme.STATUS_ERROR,
            )
            if hasattr(self, "regen_btn") and self.regen_btn.winfo_exists():
                self.regen_btn.pack(side="left")

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
                self.discovered_models = ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-thinking"]
                self.is_verified = True
                self.after(0, self._show_step_3_validation)
                return
            elif status in ("error", "failed", "cancelled"):
                err_msg = getattr(session, "error_msg", None) or "Авторизация отменена или не удалась"
                self.after(0, lambda m=err_msg: self._handle_oauth_failure(f"❌ {m}"))
                return
            elif status == "timeout":
                self.after(0, lambda: self._handle_oauth_failure("❌ Время ожидания авторизации истекло"))
                return

    def _handle_oauth_failure(self, msg: str):
        self.oauth_status_lbl.configure(text=msg, text_color=Theme.STATUS_ERROR)
        if hasattr(self, "regen_btn") and self.regen_btn.winfo_exists():
            self.regen_btn.pack(side="left")

    # ─────────────────────────────────────────────────────────────
    #  OPENAI CODEX OAUTH FLOW (DEVICE CODE / CHATGPT)
    # ─────────────────────────────────────────────────────────────

    def _build_codex_oauth_flow(self):
        ctk.CTkLabel(
            self.body,
            text="Для OpenAI Codex доступно подключение через ChatGPT Account или API Key:",
            font=Theme.font_body(),
            text_color=Theme.TEXT_SECONDARY,
            anchor="w",
        ).pack(fill="x", pady=(0, 6))

        # Mode selector radio buttons
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

        # Device auth card
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

        # Code display row
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

        # Manual Fallback Card for Codex
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
            text="Вставьте токен или JSON авторизации OpenAI вручную:",
            font=Theme.font_caption(),
            text_color=Theme.TEXT_SECONDARY,
            anchor="w",
        ).pack(fill="x", padx=10, pady=(0, 4))

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
            width=200,
            command=self._submit_manual_codex,
        ).pack(anchor="w", padx=10, pady=(0, 8))

        # Status label
        self.codex_status_lbl = ctk.CTkLabel(
            self.body,
            text="Подготовка сессии OpenAI...",
            font=Theme.font_body_bold(),
            text_color=Theme.STATUS_WARNING,
        )
        self.codex_status_lbl.pack(pady=(4, 0))

        HubButton(self.footer, text="⬅ Назад", variant="secondary", width=100, command=self._show_step_1_provider).pack(side="left")

        # Start session
        self._init_codex_oauth_session()

    def _on_codex_mode_toggle(self):
        self.codex_auth_mode = self.codex_mode_var.get()
        self._show_step_2_auth()

    def _init_codex_oauth_session(self):
        try:
            from antigravity_provider.router.codex_oauth import start_codex_oauth
            self.codex_session_id, self.codex_url, self.codex_user_code = start_codex_oauth(self.target_slot)
            self.codex_url_entry.configure(state="normal")
            self.codex_url_entry.delete(0, "end")
            self.codex_url_entry.insert(0, self.codex_url)
            self.codex_url_entry.configure(state="readonly")
            self.codex_code_lbl.configure(text=self.codex_user_code)
            self.codex_status_lbl.configure(
                text="✓ Сессия готова. Введите код на странице OpenAI в браузере...",
                text_color=Theme.STATUS_HEALTHY,
            )
            self._polling_active = True
            threading.Thread(target=self._poll_codex_oauth, daemon=True).start()
        except Exception as e:
            self.codex_status_lbl.configure(
                text=f"Ошибка запуска сессии OpenAI: {e}",
                text_color=Theme.STATUS_ERROR,
            )

    def _open_codex_browser(self):
        if self.codex_url:
            webbrowser.open(self.codex_url)
            self.codex_status_lbl.configure(
                text="🌐 Браузер открыт. Введите код подтверждения...",
                text_color=Theme.ACCENT,
            )

    def _copy_codex_url(self):
        if self.codex_url:
            self.clipboard_clear()
            self.clipboard_append(self.codex_url)
            self.codex_status_lbl.configure(
                text="✓ Ссылка скопирована в буфер обмена",
                text_color=Theme.STATUS_HEALTHY,
            )

    def _copy_codex_code(self):
        if self.codex_user_code:
            self.clipboard_clear()
            self.clipboard_append(self.codex_user_code)
            self.codex_status_lbl.configure(
                text=f"✓ Код {self.codex_user_code} скопирован",
                text_color=Theme.STATUS_HEALTHY,
            )

    def _submit_manual_codex(self):
        raw = self.codex_manual_entry.get().strip()
        if not raw:
            self.codex_status_lbl.configure(
                text="❌ Пожалуйста, вставьте токен или JSON авторизации.",
                text_color=Theme.STATUS_ERROR,
            )
            return

        from antigravity_provider.router.codex_oauth import get_codex_oauth_session
        session = get_codex_oauth_session(self.codex_session_id)
        if not session:
            self.codex_status_lbl.configure(
                text="❌ Сессия не найдена. Повторите попытку.",
                text_color=Theme.STATUS_ERROR,
            )
            return

        ok, msg = session.handle_manual_input(raw)
        if ok:
            info = getattr(session, "completed_profile_info", {}) or {}
            self.discovered_identity = info.get("email") or "ChatGPT Account"
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
                self.discovered_models = ["gpt-4o", "o3-mini", "gpt-4o-mini", "codex"]
                self.is_verified = True
                self.after(0, self._show_step_3_validation)
                return
            elif status in ("error", "failed", "cancelled"):
                err_msg = getattr(session, "error_msg", None) or "Авторизация не удалась"
                self.after(0, lambda m=err_msg: self.codex_status_lbl.configure(text=f"❌ {m}", text_color=Theme.STATUS_ERROR))
                return
            elif status == "timeout":
                self.after(0, lambda: self.codex_status_lbl.configure(text="❌ Время ожидания авторизации истекло", text_color=Theme.STATUS_ERROR))
                return

    # ─────────────────────────────────────────────────────────────
    #  API KEY FLOW (Codex API Key / OpenCode Go)
    # ─────────────────────────────────────────────────────────────

    def _build_api_key_flow(self):
        # If Codex, show mode switcher
        if self.selected_provider == "openai-codex":
            mode_card = HubCard(self.body, fg_color="transparent")
            mode_card.pack(fill="x", pady=(0, 8))

            self.codex_mode_var = ctk.StringVar(value="api_key")

            rb1 = ctk.CTkRadioButton(
                mode_card,
                text="OAuth — OpenAI / ChatGPT аккаунт (Рекомендуется)",
                value="oauth",
                variable=self.codex_mode_var,
                font=Theme.font_body(),
                fg_color=Theme.ACCENT,
                command=self._on_codex_mode_toggle,
            )
            rb1.pack(anchor="w", padx=4, pady=2)

            rb2 = ctk.CTkRadioButton(
                mode_card,
                text="API Key — OpenAI API (sk-...)",
                value="api_key",
                variable=self.codex_mode_var,
                font=Theme.font_body_bold(),
                fg_color=Theme.ACCENT,
                command=self._on_codex_mode_toggle,
            )
            rb2.pack(anchor="w", padx=4, pady=2)

        prompt_text = (
            "Введите ключ OpenAI API (sk-...):"
            if self.selected_provider == "openai-codex"
            else "Введите ключ API / Bearer Token для OpenCode Go:"
        )

        ctk.CTkLabel(
            self.body,
            text=prompt_text,
            font=Theme.font_body(),
            text_color=Theme.TEXT_SECONDARY,
        ).pack(anchor="w", pady=(0, 6))

        entry_row = ctk.CTkFrame(self.body, fg_color="transparent")
        entry_row.pack(fill="x", pady=(0, 8))

        placeholder = "sk-..." if self.selected_provider == "openai-codex" else "opencode-..."
        self.key_entry = HubEntry(
            entry_row,
            placeholder_text=placeholder,
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

            # Perform real key verification
            is_valid = False
            masked_id = None
            models: List[str] = []

            if self.selected_provider == "openai-codex":
                is_valid, masked_id, models = ProfileAuthManager.verify_codex_token(k)
            elif self.selected_provider == "opencode-go":
                is_valid, masked_id, models = ProfileAuthManager.verify_opencode_token(k)

            # Save auth data safely
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

        HubButton(self.footer, text="⬅ Назад", variant="secondary", width=100, command=self._show_step_1_provider).pack(side="left")
        HubButton(self.footer, text="Проверить и сохранить ➔", variant="primary", width=200, command=_save_key).pack(side="right")

    def _paste_into_entry(self, target_entry: Any):
        """Read clipboard cleanly, strip whitespace, and insert into target entry widget."""
        try:
            val = self.clipboard_get()
            if val is not None:
                cleaned = str(val).strip()
                if cleaned:
                    target_entry.delete(0, "end")
                    target_entry.insert(0, cleaned)
                    if hasattr(self, "key_status_lbl"):
                        self.key_status_lbl.configure(text="")
                    return
            if hasattr(self, "key_status_lbl"):
                self.key_status_lbl.configure(text="Буфер обмена пуст.")
        except Exception as e:
            if hasattr(self, "key_status_lbl"):
                self.key_status_lbl.configure(text="Не удалось прочитать буфер обмена.")

    # ═══════════════════════════════════════════════════════════════
    #  STEP 3: Validation & Duplicate Detection
    # ═══════════════════════════════════════════════════════════════

    def _show_step_3_validation(self):
        self._clear_body()
        self._polling_active = False
        self.title_lbl.configure(text="Шаг 3 из 4: Валидация аккаунта")

        # Check duplicate
        dup_pid = AutoAssigner.check_duplicate_identity(self.selected_provider, self.discovered_identity, exclude_profile_id=self.target_slot)

        if dup_pid:
            dname, _, _ = AutoAssigner.get_display_name_and_role(dup_pid)
            warn_card = HubCard(self.body, border_color=Theme.STATUS_WARNING, fg_color="#3B2610")
            warn_card.pack(fill="x", pady=(0, 12))

            ctk.CTkLabel(
                warn_card,
                text=f"⚠️ Внимание: Этот аккаунт ({self.discovered_identity}) уже подключён к слоту «{dname}» ({dup_pid}).",
                font=Theme.font_body_bold(),
                text_color=Theme.STATUS_WARNING,
                wraplength=500,
                justify="left",
            ).pack(padx=14, pady=10, anchor="w")

        info_card = HubCard(self.body)
        info_card.pack(fill="x", pady=(0, 12))

        p_name = "Google Antigravity" if self.selected_provider == "antigravity" else (
            "OpenAI Codex" if self.selected_provider == "openai-codex" else "OpenCode Go"
        )
        status_text = "✓ Проверен и готов к работе" if self.is_verified else "⚠ НЕ ПРОВЕРЕН (Сохранён офлайн)"
        status_color = Theme.STATUS_HEALTHY if self.is_verified else Theme.STATUS_WARNING

        ctk.CTkLabel(info_card, text=f"Провайдер: {p_name}", font=Theme.font_body(), text_color=Theme.TEXT_PRIMARY).pack(anchor="w", padx=14, pady=(10, 2))
        ctk.CTkLabel(info_card, text=f"Идентификатор: {self.discovered_identity}", font=Theme.font_body_bold(), text_color=Theme.TEXT_PRIMARY).pack(anchor="w", padx=14, pady=2)
        ctk.CTkLabel(info_card, text=f"Статус: {status_text}", font=Theme.font_body_bold(), text_color=status_color).pack(anchor="w", padx=14, pady=2)

        if self.discovered_models:
            models_str = ", ".join(self.discovered_models[:4])
            if len(self.discovered_models) > 4:
                models_str += f" (+{len(self.discovered_models)-4})"
            ctk.CTkLabel(info_card, text=f"Доступные модели: {models_str}", font=Theme.font_caption(), text_color=Theme.TEXT_SECONDARY).pack(anchor="w", padx=14, pady=(2, 10))
        else:
            ctk.CTkLabel(info_card, text="", font=Theme.font_caption()).pack(pady=(0, 6))

        HubButton(self.footer, text="⬅ Назад", variant="secondary", width=100, command=self._show_step_2_auth).pack(side="left")
        HubButton(self.footer, text="Далее к назначению ➔", variant="primary", width=180, command=self._show_step_4_assignment).pack(side="right")

    # ═══════════════════════════════════════════════════════════════
    #  STEP 4: Role Assignment & Confirmation
    # ═══════════════════════════════════════════════════════════════

    def _show_step_4_assignment(self):
        self._clear_body()
        self.title_lbl.configure(text="Шаг 4 из 4: Назначение роли")

        rec_role, rec_reason = AutoAssigner.recommend_role_for_new_account(self.selected_provider, self.target_slot)

        rec_card = HubCard(self.body, border_color=Theme.ACCENT)
        rec_card.pack(fill="x", pady=(0, 12))

        role_labels = {
            "orchestrator": "Оркестратор (Главный агент)",
            "coder": "Разработчик (Coder)",
            "reviewer": "Ревьюер (Reviewer)",
            "researcher": "Исследователь (Research)",
            "general": "Общий пул (General)",
            "spare": "Только резерв (Cold Spare)",
        }

        ctk.CTkLabel(
            rec_card,
            text=f"💡 Рекомендованное назначение: {role_labels.get(rec_role, rec_role)}",
            font=Theme.font_body_bold(),
            text_color=Theme.ACCENT,
        ).pack(anchor="w", padx=14, pady=(10, 2))

        ctk.CTkLabel(
            rec_card,
            text=rec_reason,
            font=Theme.font_caption(),
            text_color=Theme.TEXT_SECONDARY,
            wraplength=520,
            justify="left",
        ).pack(anchor="w", padx=14, pady=(0, 10))

        ctk.CTkLabel(
            self.body,
            text="Выберите роль в многоагентной цепочке маршрутизации:",
            font=Theme.font_body(),
            text_color=Theme.TEXT_PRIMARY,
        ).pack(anchor="w", pady=(4, 6))

        role_var = ctk.StringVar(value=rec_role)

        for val, lbl in role_labels.items():
            ctk.CTkRadioButton(
                self.body,
                text=lbl,
                variable=role_var,
                value=val,
                font=Theme.font_body(),
                text_color=Theme.TEXT_PRIMARY,
                fg_color=Theme.ACCENT,
                hover_color=Theme.ACCENT_HOVER,
            ).pack(anchor="w", padx=8, pady=3)

        def _finish():
            chosen = role_var.get()
            target_role = "orchestrator" if chosen == "orchestrator" else (
                "coder" if chosen == "coder" else (
                    "reviewer" if chosen == "reviewer" else (
                        "researcher" if chosen == "researcher" else (
                            "spare" if chosen == "spare" else "general"
                        )
                    )
                )
            )

            # Apply role to live config
            ok, msg = AutoAssigner.assign_profile_to_role(self.target_slot, target_role, is_primary=(chosen != "spare"))
            if not ok:
                EventLogService.get().log(
                    "account",
                    f"Ошибка назначения профиля {self.target_slot}: {msg}",
                    level="warning",
                )
                return

            EventLogService.get().log(
                "account",
                f"Подключён аккаунт {self.discovered_identity} ({self.selected_provider}). {msg}.",
                level="success",
            )
            self.destroy()
            if self.on_complete:
                self.on_complete({
                    "provider": self.selected_provider,
                    "slot": self.target_slot,
                    "identity": self.discovered_identity,
                    "role": target_role,
                })

        HubButton(self.footer, text="Готово (Завершить)", variant="primary", width=180, command=_finish).pack(side="right")
