# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.x     | Yes       |
| < 1.0   | No        |

---

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Please report security issues by emailing the maintainer directly. Include:

1. A description of the vulnerability and its potential impact
2. Steps to reproduce (proof-of-concept if available)
3. Any suggested mitigations

You can expect an acknowledgement within **72 hours** and a patch or mitigation plan within **14 days** for confirmed vulnerabilities.

---

## Security Design Notes

The following controls are implemented in DeepRouter. If you discover a bypass or weakness in any of these, please report it.

| Control | Implementation |
|---------|---------------|
| API key storage | SHA-256 hash only — plaintext key shown once at provisioning, never stored |
| Key validation | Redis fast path + Postgres authoritative fallback; `revoked` flag + `expires_at` enforced |
| Rate limiting | Atomic Redis Lua script, per-user token buckets keyed on authenticated `user_id` (not client-supplied header) |
| Admin access | `X-Admin-Secret` header + IP allowlist (CIDR) enforced in production; bypassed only in `ENV=development` |
| TLS | Nginx terminates TLS 1.2/1.3 only; HTTP redirected 301 → HTTPS; HSTS-ready |
| CORS | Explicit allowlist via `ALLOWED_ORIGINS` env var |
| Dev key isolation | `DEV_API_KEY` rejected when `ENV=production` |
| Request tracing | `X-Request-ID` propagated end-to-end for audit correlation |

---

## Responsible Disclosure

We follow a coordinated disclosure model. Once a fix is released, we will publicly credit the reporter (unless they prefer to remain anonymous) in the relevant release notes.
