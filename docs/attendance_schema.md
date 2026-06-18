## Attendance

### Overview

Attendance has no module dependency on People — it must remain fully functional whether or not People is enabled. It supports both a simple aggregate headcount and an optional per-person check-in layer, and the two can coexist independently (e.g. a manual total headcount for the whole congregation alongside named check-in for children's ministry specifically).

---

### `attendance_session`

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | PK | — | |
| `congregation_id` | FK → congregations | not null | |
| `service_id` | FK → services | nullable | Optional link if Services is enabled and this ties to a specific service |
| `label` | varchar(150) | nullable | e.g. "Sunday Morning Worship", "Wednesday Youth Group" — independent of Services |
| `occurred_date` | date | not null | |
| `headcount_total` | integer | nullable | Manually recorded aggregate total |
| `notes` | text | nullable | |
| `recorded_by_id` | FK → users | not null | |
| `created_at` / `updated_at` | timestamp | not null | |

---

### `attendance_checkin`

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | PK | — | |
| `congregation_id` | FK → congregations | not null | |
| `session_id` | FK → attendance_session | not null | |
| `person_id` | FK → people | not null | |
| `checked_in_at` | timestamp | not null | |
| `checked_in_by_id` | FK → users | not null | Who ran the check-in |
| `created_at` | timestamp | not null | |

*Constraint:* unique on `(session_id, person_id)`.

A session can have a `headcount_total`, zero or more `attendance_checkin` rows, or both at once — the two aren't reconciled against each other, since they're often answering different questions (a rough total attendance count vs. a specific, secured list of who's accounted for). When People is disabled, sessions simply never accumulate check-in rows; headcount tracking continues to work without any special-case logic.
