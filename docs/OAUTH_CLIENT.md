# Google OAuth 2.0 Desktop Client Architecture & Security Decision

**Document Version:** 1.0.0  
**Date:** 2026-08-20  
**Status:** Approved Architectural Decision  
**Target Module:** `src/antigravity_provider/oauth.py`

---

## 1. Context & Threat Model

Hermes Hub acts as a local orchestrator and router for developer agents, connecting to Google Antigravity (Gemini Code Assist / CloudCode ecosystem) via OAuth 2.0.

Under **RFC 8252 (OAuth 2.0 for Native Apps)**:
- A desktop or command-line application is classified as a **Public Client** (RFC 6749 Section 2.1).
- Native desktop applications cannot securely store private client secrets against binary inspection or local debugging.
- Security of the authorization grant relies on **PKCE (RFC 7636)** and the **Loopback Interface Redirect URI** (`http://127.0.0.1:51121/oauth-callback`).

---

## 2. Decision: Documented Native Desktop Client

We utilize the standard Google CloudCode Desktop OAuth Client configuration intended for native developer desktop tooling.

### Configuration Specification

- **Client Type:** Native Application (Installed App)
- **Client ID:** `1071006060591-tmhssin2h21lcre235vtolojh4g403ep.apps.googleusercontent.com`
- **Client Secret:** `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` (Public client placeholder per Google Cloud SDK native tool standard)
- **Redirect URI:** `http://127.0.0.1:51121/oauth-callback`
- **Auth Endpoint:** `https://accounts.google.com/o/oauth2/v2/auth`
- **Token Endpoint:** `https://oauth2.googleapis.com/token`
- **Required Scopes:**
  - `https://www.googleapis.com/auth/cloud-platform`
  - `https://www.googleapis.com/auth/userinfo.email`
  - `https://www.googleapis.com/auth/userinfo.profile`
  - `https://www.googleapis.com/auth/cclog`
  - `https://www.googleapis.com/auth/experimentsandconfigs`

---

## 3. Transparency & Scanner Policy

1. **No Obfuscation:** The source code in `src/antigravity_provider/oauth.py` directly defines these public constants with explicit references to RFC 8252. Obfuscated string concatenation (`"abc" + "def"`) is strictly prohibited.
2. **Scanner Policy:** The security scanner treats the documented native public client constants as known standard constants, while strictly prohibiting live user API keys (`sk-...`, `opencode-...`), bearer tokens, private keys, and unauthorized secret assignments in source code.
3. **Local User Credential Isolation:** All runtime user tokens (`access_token`, `refresh_token`, expiration timestamps) are saved strictly inside the user's isolated local data directory (`%HERMES_HOME%/agy_profiles/<profile_id>/auth.json` or OS keychain) and are **never tracked in git or shared**.
