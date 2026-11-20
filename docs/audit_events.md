# Audit Events

Every audit entry includes `request_id` when it is created in an HTTP request.

| Event | Source file:line | Details fields |
|---|---|---|
| `authentication-failed` | `backend/app/auth.py` | `path`, `request_id` |
| `permission-denied` | `backend/app/auth.py` | `capability`, `route`, `method`, `request_id` |
| `login-failed` | `backend/app/main.py` | `email`, `ip`, `request_id` |
| `login-rate-limited` | `backend/app/main.py` | `email`, `ip`, `request_id` |
| `login` | `backend/app/main.py` | `email`, `success`, `request_id` |
| `logout` | `backend/app/main.py` | `request_id` |
| `renewals-read` | `backend/app/main.py` | `request_id` |
| `renewal-created` | `backend/app/main.py` | `request_id` |
| `renewal-deleted` | `backend/app/main.py` | `request_id` |
| `health-insight-generated` | `backend/app/main.py` | `request_id` |
| `investment-proposal` | `backend/app/main.py` | `request_id` |
| `investment-mfa-failed` | `backend/app/main.py` | `proposalId`, `reason`, `provider`, `request_id` |
| `investment-mfa-verified` | `backend/app/main.py` | `proposalId`, `provider`, `request_id` |
| `investment-approval-awaiting-mfa` | `backend/app/main.py` | `proposalId`, `state`, `request_id` |
| `investment-execution-denied` | `backend/app/main.py` | `proposalId`, `reason`, `mfa_verified`, `request_id` |
| `approval-state-transition` | `backend/app/main.py` | `proposalId`, `from`, `to`, `request_id` |
| `investment-confirmation` | `backend/app/main.py` | `proposalId`, `approved`, `request_id` |
| `cross-user-access-denied` | `backend/app/main.py` | `resource_type`, `resource_id`, `request_id` |
| `supervisor-validation-failed` | `backend/app/main.py` | `query_length`, `query_sha256`, `reason`, `request_id` |
| `supervisor-policy-denied` | `backend/app/main.py` | `query_length`, `query_sha256`, `reason`, `request_id` |
| `supervisor-routed` | `backend/app/main.py` | `query_length`, `query_sha256`, `routing_path`, `fallback_reason`, `agent`, `capability`, `policy_verdict`, `workflow`, `request_id` |
| `agent-tool-call` | `backend/app/main.py` | `tool`, `ok`, `request_id` |

## Detection rule event mapping

| Rule | Audit events read |
|---|---|
| `brute-force-login` | `login-failed`, per IP |
| `repeated-capability-denials` | `permission-denied` and `supervisor-policy-denied`, per user |
| `cross-user-resource-access` | `cross-user-access-denied`, per user |
| `repeated-mfa-failures` | `investment-mfa-failed`, per user |
