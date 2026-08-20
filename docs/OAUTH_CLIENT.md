# OAuth 2.0 Native & Device Client Architecture & Security Decision

**Document Version:** 1.1.0  
**Date:** 2026-08-21  
**Status:** Approved Architectural Decision  
**Scope:** `src/antigravity_provider/router/*_oauth.py`

---

## 1. Executive Summary & Threat Model

Hermes Hub is a local desktop orchestrator and router for developer agents running on the user's workstation. To connect seamlessly to multi-provider accounts without requiring users to create custom cloud console client applications, Hermes Hub implements standard native desktop and device authorization flows per IETF RFC specifications.

### Applicable Standards
- **RFC 8252 (OAuth 2.0 for Native Apps):** Native desktop applications are Public Clients (RFC 6749 Section 2.1). They cannot securely protect embedded client secrets against binary extraction or local debugging.
- **RFC 7636 (Proof Key for Code Exchange / PKCE):** Protects authorization code grants against interception by dynamically generating cryptographic code verifiers and challenges.
- **RFC 8628 (OAuth 2.0 Device Authorization Grant):** Allows browserless or secondary-screen authorization via standard user verification codes and polling.

---

## 2. Documented Provider Clients

### 2.1 Google Antigravity Native Desktop Client
- **Protocol:** RFC 8252 (Native App) + RFC 7636 (PKCE S256) + Loopback Interface Redirect (`http://127.0.0.1:51121/oauth-callback`)
- **Module:** `src/antigravity_provider/router/profile_oauth.py`
- **Origin:** Google CloudCode / Gemini Code Assist standard native tool client
- **Client Type:** Native Application (Public Client)
- **Client ID:** `1071006060591-tmhssin2h21lcre235vtolojh4g403ep.apps.googleusercontent.com`
- **Client Secret:** `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` (Public client placeholder per Google Cloud SDK native tool standard)
- **Required Scopes:**
  - `https://www.googleapis.com/auth/cloud-platform`
  - `https://www.googleapis.com/auth/userinfo.email`
  - `https://www.googleapis.com/auth/userinfo.profile`
  - `https://www.googleapis.com/auth/cclog`
  - `https://www.googleapis.com/auth/experimentsandconfigs`

### 2.2 OpenAI Codex Device Flow Client
- **Protocol:** RFC 8628 (OAuth 2.0 Device Authorization Grant)
- **Module:** `src/antigravity_provider/router/codex_oauth.py`
- **Origin:** OpenAI Codex / ChatGPT developer tooling public client
- **Client Type:** Native Device Client (Public Client)
- **Client ID:** `app_EMoamEEZ73f0CkXaXp7hrann`
- **Endpoints:**
  - User Code Request: `https://auth.openai.com/deviceauth/usercode`
  - User Verification: `https://auth0.openai.com/activate`
  - Device Token Poll: `https://auth.openai.com/deviceauth/token`
- **Security Invariant:** User codes must originate from the OpenAI authorization server. If the server is unreachable, an immediate error is presented to the user. Mock session generation is strictly gated behind `HERMES_HUB_DEV_MODE=1` with visible UI badging.

### 2.3 xAI Grok Device Authorization Client
- **Protocol:** RFC 8628 (OAuth 2.0 Device Authorization Grant)
- **Module:** `src/antigravity_provider/router/grok_oauth.py`
- **Origin:** xAI Grok developer desktop tooling public client
- **Client Type:** Native Device Client (Public Client)
- **Client ID:** `b1a00492-073a-47ea-816f-4c329264a828`
- **Endpoints:**
  - Device Code Request: `https://auth.x.ai/oauth2/device/code`
  - Verification URL: Complete URI provided by xAI server or `https://auth.x.ai/device`
  - Token Poll: `https://auth.x.ai/oauth2/token`
- **Required Scope:** `openid profile email offline_access`
- **Security Invariant:** Device codes must originate from xAI. In standard operation, network failures abort authorization immediately. Mock codes are permitted only under `HERMES_HUB_DEV_MODE=1`.

### 2.4 Anthropic Claude Desktop OAuth Client
- **Protocol:** RFC 8252 (Native App) + RFC 7636 (PKCE S256) + Manual Code/Token Paste
- **Module:** `src/antigravity_provider/router/claude_oauth.py`
- **Origin:** Claude desktop developer tooling public client
- **Client Type:** Native Application (Public Client)
- **Client ID:** `9d1c250a-e274-4630-9742-1e96a2202eb8`
- **Endpoints:**
  - Auth URL: `https://claude.ai/oauth/authorize`
  - Token Exchange: `https://claude.ai/api/auth/oauth/token` (and official fallback exchange endpoints)
- **Redirect URI:** `https://claude.ai/oauth/callback`
- **Required Scope:** `openid profile email`
- **Security Invariant:** Network exchange failures return explicit error messages. Manual fallback is strictly restricted to valid API tokens or `HERMES_HUB_DEV_MODE=1`.

---

## 3. Transparency, Credentials Isolation & Scanner Policy

1. **Explicit Constants:** All public client identifiers and standard endpoints are defined clearly and explicitly in code. Obfuscated string concatenation is strictly prohibited.
2. **Local Credential Storage:** Runtime credentials (`access_token`, `refresh_token`, expiration timestamps) are stored in the user's isolated local profile store (`%HERMES_HOME%/*_profiles/<profile_id>/auth.json` or Windows Credential Manager) with restricted file permissions (`0o600`) and are excluded from git.
3. **AST Secret Scanner Policy:** The scanner verifies that no live user API keys (`sk-...`, `sk-ant-...`, `xai-...`), private tokens, or obfuscated secret assignments exist in the codebase, while allowing documented public client constants compliant with RFC 8252/8628.
