## Services

### Overview

Services covers service planning and the order of worship. It supports reusable templates so a new week's order of worship doesn't have to be built from scratch every time.

---

### `services`

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | PK | — | |
| `congregation_id` | FK → congregations | not null | |
| `template_id` | FK → service_template | nullable | Lineage only — which template (if any) this was created from; no functional binding afterward |
| `title` | varchar(150) | not null | e.g. "Sunday Morning Worship" |
| `service_date` | date | not null | |
| `start_time` | time | not null | |
| `location` | varchar(150) | nullable | |
| `service_type` | varchar(50) | nullable | e.g. `regular` / `special` / `holiday` |
| `notes` | text | nullable | |
| `created_by_id` | FK → users | not null | |
| `created_at` / `updated_at` | timestamp | not null | |

---

### `service_elements`
*The order of worship — an ordered list of items within a service.*

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | PK | — | |
| `congregation_id` | FK → congregations | not null | |
| `service_id` | FK → services | not null | |
| `sequence_order` | integer | not null | Position within the service |
| `element_type` | varchar(50) | nullable | e.g. `song` / `sermon` / `announcement` / `communion` / `prayer` |
| `title` | varchar(150) | not null | e.g. "Sermon: Faith in Action" |
| `duration_minutes` | integer | nullable | Planned timing |
| `assigned_person_id` | FK → people | nullable | Who's leading this element — loosely coupled, no hard dependency |
| `notes` | text | nullable | |
| `created_at` / `updated_at` | timestamp | not null | |

*Constraint:* unique on `(service_id, sequence_order)`.

---

### `service_template`

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | PK | — | |
| `congregation_id` | FK → congregations | not null | |
| `name` | varchar(150) | not null | e.g. "Standard Sunday Service" |
| `created_by_id` | FK → users | not null | |
| `created_at` / `updated_at` | timestamp | not null | |

---

### `service_template_elements`

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | PK | — | |
| `congregation_id` | FK → congregations | not null | |
| `template_id` | FK → service_template | not null | |
| `sequence_order` | integer | not null | |
| `element_type` | varchar(50) | nullable | |
| `title` | varchar(150) | not null | |
| `duration_minutes` | integer | nullable | |
| `notes` | text | nullable | |

No `assigned_person_id` here — different people lead each week, so that's only filled in on the actual instantiated service. Creating a new service "from a template" is a one-time **copy**: the template's elements get duplicated into real `service_elements` rows tied to that specific service, with `assigned_person_id` left blank for the admin to fill in. Editing the template afterward never retroactively touches services already created from it.

**Independence note:** `assigned_person_id` here and `schedule_assignment` (Scheduling module) are two independent ways of recording "who's doing what." They aren't cross-wired — deliberate, to keep both modules independently functional regardless of which is enabled.
