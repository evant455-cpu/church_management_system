## Staff

### Overview

"Staff" means two different things in this system, worth keeping mentally separate even though the schema doesn't couple them:

- The `staff` table below — an HR/employment classification of a person (title, department, employment type). A person can be HR-staff without ever logging in (e.g. a part-time custodian).
- The `Staff` **role** in the permissions system (see Roles & Permissions) — determines what a logged-in user can access. A person can hold this role without being HR-staff.

They'll usually overlap in practice but are structurally independent.

**Out of scope:** compensation/payroll data. This module tracks who someone is and what they do, not what they're paid — payroll typically belongs in dedicated payroll software, and storing salary data here would add a sensitivity/access-control burden disproportionate to what this module is for.

---

### `staff`

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | PK | — | |
| `congregation_id` | FK → congregations | not null | |
| `person_id` | FK → people | not null, unique | One staff record per person — rehires reactivate the existing record |
| `position_title` | varchar(150) | not null | e.g. "Worship Pastor", "Office Administrator" |
| `department` | varchar(100) | nullable | e.g. "Worship", "Operations", "Children's Ministry" |
| `employment_type` | varchar(20) | not null | `full_time` / `part_time` / `contractor` / `volunteer_staff` |
| `employment_status` | varchar(20) | not null, default `active` | `active` / `on_leave` / `terminated` |
| `supervisor_staff_id` | FK → staff | nullable | Self-referential — enables an org chart / reporting line |
| `start_date` | date | not null | |
| `end_date` | date | nullable | |
| `created_at` / `updated_at` | timestamp | not null | |

---

### `staff_position_history`
*Append-only audit log — every change to title, department, or status, forever.*

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | PK | — | |
| `staff_id` | FK → staff | not null | |
| `congregation_id` | FK → congregations | not null | Denormalized for RLS |
| `position_title` | varchar(150) | not null | Snapshot value at the time of this change |
| `department` | varchar(100) | nullable | |
| `employment_status` | varchar(20) | not null | |
| `effective_date` | date | not null | |
| `changed_by_id` | FK → users | not null | |
| `created_at` | timestamp | not null | |

Every creation of a staff record, and every subsequent edit to title/department/status, writes a new snapshot row — so "what was this person's title on a given date" is always directly answerable rather than reconstructed from diffs.
