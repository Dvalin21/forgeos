# ForgeOS Phase 2: Authentication & Security Design

**Date:** 2026-04-29  
**Branch:** feature/phase2-security-monitoring  
**Status:** Design Complete - Ready for Implementation

---

## 1. Authentication & Security (2FA + OAuth + API Keys)

### 1.1 Two-Factor Authentication (2FA)

**Approach:** Use `pyotp` + `qrcode` libraries for TOTP-based 2FA.

**Storage:** Extend `/etc/forgeos/api-users.json` with 2FA fields:
```json
{
  "admin": {
    "hash": "$2b$12$xxxxxxxxxxxx",
    "role": "admin",
    "totp_secret": "JBSWY3DPEHPK3PXP",
    "totp_enabled": true,
    "backup_codes": ["a1b2c3d4", "e5f6g7h8"],
    "created": "2026-04-29T00:00:00Z"
  }
}
```

**API Endpoints:**
- `POST /api/auth/login` - Modified to require OTP when 2FA enabled
- `POST /api/auth/totp/setup` - Generate secret + QR code URI
- `POST /api/auth/totp/verify` - Verify TOTP code during login
- `POST /api/auth/totp/enable` - Enable 2FA after verification
- `POST /api/auth/totp/disable` - Disable 2FA (requires password + TOTP)
- `POST /api/auth/backup-codes` - Generate new backup codes

**Flow:**
1. User logs in with username/password
2. If 2FA enabled → return `{"requires_2fa": true, "temp_token": "..."}`
3. User submits TOTP code with temp_token
4. On success → return full JWT token (12h expiry)

### 1.2 OAuth2 / OpenID Connect

**Approach:** Use `authlib` or `fastapi-oauth2` for OAuth integration.

**Supported Providers (Phase 2):**
- Google (OAuth2)
- GitHub (OAuth2)
- Generic OIDC (for corporate SSO)

**Storage:** Add OAuth credentials to user JSON:
```json
{
  "oauth_providers": {
    "google": {"sub": "12345", "email": "user@gmail.com"},
    "github": {"sub": "67890", "username": "user"}
  }
}
```

**API Endpoints:**
- `GET /api/auth/oauth/{provider}/login` - Redirect to provider
- `GET /api/auth/oauth/{provider}/callback` - OAuth callback handler
- `POST /api/auth/oauth/{provider}/link` - Link OAuth to existing account
- `DELETE /api/auth/oauth/{provider}/unlink` - Unlink OAuth provider

### 1.3 API Keys System

**Approach:** Generate cryptographically secure API keys with rate limiting.

**Storage:** New file `/etc/forgeos/api-keys.json`:
```json
{
  "keys": [
    {
      "id": "key_abc123",
      "user": "admin",
      "name": "CI/CD Pipeline",
      "key_hash": "sha256_hash",
      "permissions": ["read", "write"],
      "rate_limit": 1000,
      "created": "2026-04-29T00:00:00Z",
      "last_used": "2026-04-29T01:00:00Z",
      "expires": "2027-04-29T00:00:00Z"
    }
  ]
}
```

**API Endpoints:**
- `POST /api/auth/keys` - Create new API key
- `GET /api/auth/keys` - List user's API keys
- `DELETE /api/auth/keys/{key_id}` - Revoke API key
- `GET /api/auth/keys/{key_id}/usage` - View usage stats

**Authentication:** API keys passed via `Authorization: Bearer key_xxx` or `X-API-Key: key_xxx` header.

### 1.4 Rate Limiting Middleware

**Approach:** Use `slowapi` or custom middleware with Redis/InMemory storage.

**Limits:**
- Auth endpoints: 5 req/min per IP
- API calls: 1000 req/hour per user (configurable per API key)
- WebSocket: 10 connections per user

**Implementation:** FastAPI middleware that checks rate limits before processing requests.

### 1.5 Audit Logging

**Approach:** Log all authentication events, privileged actions, and API calls.

**Storage:** `/var/log/forgeos/audit.log` (JSON format, rotated daily).

**Events Logged:**
- Login success/failure (with IP, user agent)
- 2FA enable/disable
- OAuth link/unlink
- API key create/revoke
- Container operations (start/stop/exec)
- File operations (upload/delete)
- Settings changes

**API Endpoints:**
- `GET /api/audit/logs` - View audit logs (admin only)
- `GET /api/audit/export` - Export logs (JSON/CSV)

---

## 2. Implementation Priority

1. **2FA (pyotp + qrcode)** - Foundation for secure auth
2. **Rate limiting middleware** - Protect auth endpoints
3. **API keys system** - Enable programmatic access
4. **Audit logging** - Compliance and debugging
5. **OAuth2/OIDC** - Convenience (depends on 2FA being stable)

---

## 3. Dependencies to Install

```bash
pip3 install pyotp qrcode[pil] authlib slowapi redis
```

---

## 4. Files to Modify

- `src/forgeos-api.py` - Add 2FA, OAuth, API keys, rate limiting, audit logs
- `src/auth_2fa.py` - New module for 2FA logic
- `src/auth_oauth.py` - New module for OAuth handlers
- `src/api_keys.py` - New module for API key management
- `web/desktop/settings/security.html` - New settings page for auth management
- `web/desktop/js/2fa-setup.js` - Frontend for 2FA QR code setup

---

## 5. Success Criteria

- [ ] User can enable/disable 2FA via WebGUI
- [ ] QR code displays for Google Authenticator setup
- [ ] Backup codes generated and downloadable
- [ ] Login requires TOTP when 2FA enabled
- [ ] API keys can be created with permissions
- [ ] Rate limiting blocks brute-force attempts
- [ ] Audit log shows all auth events
- [ ] OAuth login works with GitHub/Google (stretch)
