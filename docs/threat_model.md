# PersonalOS Threat Model

MITRE IDs below are **closest match, approximate** identifiers because the repository has application-level controls rather than a formal MITRE ATT&CK threat assessment.

| Category | Asset | Threat | Control in this repository | Residual gap |
|---|---|---|---|---|
| Spoofing | JWT-authenticated user identity | An attacker uses or forges another user's bearer identity | Short-lived JWT verification and active-user lookup are enforced in `backend/app/auth.py`; logout adds the token JTI to `RevokedToken` in `backend/app/auth.py` and `backend/app/models.py`. | JWT secret strength and token storage are deployment concerns; there is no refresh-token rotation or hardware-backed MFA for login. |
| Tampering | Renewal, health, document, proposal, and audit records | An attacker modifies records belonging to another owner or changes a routed action | Owner scoping and cross-owner denial are implemented in `backend/app/repositories.py` and `backend/app/main.py`; routed operations re-check capabilities in `backend/app/agents/base.py`, `backend/app/routing/policy.py`, and `backend/app/routing/supervisor.py`. | No database-level row-level security, append-only audit storage, or audit log signature is implemented. |
| Repudiation | Audit trail and investment decisions | A user denies actions or the audit trail cannot show which principal or request performed them | Audit entries store `user_id`, event details, and request IDs in `backend/app/audit.py`, `backend/app/repositories.py`, and `backend/app/audit_context.py`; `backend/app/main.py` emits route, document, approval, and logout events. | Audit data can be changed through normal database access; timestamps and event integrity are not externally attested. |
| Information disclosure | Passwords, private documents, health and finance data | Sensitive data is returned or placed in logs outside the owner's scope | Passwords are Argon2/bcrypt hashes in `backend/app/auth.py`; repository queries filter owner IDs in `backend/app/repositories.py`; document search is owner-scoped in `backend/app/main.py` and `backend/app/agents/document.py`. Audit details omit raw document text and raw query content by hashing or length-based fields in `backend/app/main.py` and `backend/app/repositories.py`. | Backups, database access, browser storage, TLS termination, and secret-at-rest protections remain deployment responsibilities. |
| DoS | Login endpoint and server resources | Repeated invalid logins exhaust accounts or oversized requests consume resources | Per-process login throttling limits failures to five in 60 seconds in `backend/app/main.py`; document uploads are capped at 200 KB in `backend/app/main.py`; route query length is capped in `backend/app/schemas.py`. | The login limiter is in-memory and per-process, and there is no global rate limiting or request concurrency protection. |
| Elevation of privilege | Permission checks and investment execution | A user obtains extra capabilities or executes an investment without approval | Route dependencies call `require_permission` in `backend/app/auth.py`; `backend/app/routing/policy.py` denies missing capabilities and requires explicit approval/MFA for execution; MFA state and transitions are enforced in `backend/app/approval.py`. | MFA is mock-development code with no external provider, and existing databases require re-seeding for document capabilities as noted in `README.md`. |

## Approximate MITRE ATT&CK closest matches

- Spoofing: **T1078 - Valid Accounts** (closest match, approximate).
- Tampering: **T1565 - Data Manipulation** (closest match, approximate).
- Repudiation: **T1070 - Indicator Removal** (closest match, approximate).
- Information disclosure: **T1552 - Unsecured Credentials** and **T1530 - Data from Cloud Storage** (closest matches, approximate).
- DoS: **T1499 - Endpoint Denial of Service** (closest match, approximate).
- Elevation of privilege: **T1068 - Exploitation for Privilege Escalation** and **T1078 - Valid Accounts** (closest matches, approximate).
