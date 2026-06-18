## Scheduling

### Overview

Scheduling has a hard module dependency on People (see Module System Mechanics) — `schedule_assignment.person_id` is `NOT NULL`. Supports two features beyond simple one-off assignment: recurring needs (a template that generates concrete occurrences ahead of time) and partially-filled open slots (e.g. "need 3 greeters, 1 filled").

Three tables, each with a distinct job: a recurrence definition, a concrete dated occurrence, and a specific person filling one position within that occurrence.

---

### `schedule_template`
*Defines a recurring need.*

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | PK | — | |
| `congregation_id` | FK → congregations | not null | |
| `role_or_position` | varchar(150) | not null | e.g. "Greeter", "Sound Tech" |
| `service_id` | FK → services | nullable | |
| `recurrence_rule` | varchar(255) | not null | Standard iCalendar RRULE string (e.g. `FREQ=MONTHLY;BYDAY=1SU` for "every 1st Sunday") |
| `default_start_time` | time | not null | |
| `duration_minutes` | integer | nullable | |
| `slots_needed` | integer | not null, default 1 | How many people this recurring need requires each occurrence |
| `recurrence_start_date` | date | not null | |
| `recurrence_end_date` | date | nullable | Null = runs indefinitely |
| `is_active` | boolean | not null, default `true` | Pause without deleting |
| `created_by_id` | FK → users | not null | |
| `created_at` / `updated_at` | timestamp | not null | |

---

### `schedule_slot`
*A concrete, dated occurrence of a need — generated from a template or created one-off.*

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | PK | — | |
| `congregation_id` | FK → congregations | not null | |
| `template_id` | FK → schedule_template | nullable | Null if created directly, not from recurrence |
| `role_or_position` | varchar(150) | not null | |
| `service_id` | FK → services | nullable | |
| `start_time` | timestamp | not null | |
| `end_time` | timestamp | nullable | |
| `slots_needed` | integer | not null, default 1 | |
| `is_canceled` | boolean | not null, default `false` | Skip one occurrence of a recurring template without touching the template |
| `created_by_id` | FK → users | not null | |
| `created_at` / `updated_at` | timestamp | not null | |

A background job materializes upcoming slots from active templates on a rolling horizon (e.g. the next 8 weeks) — the same pattern calendar apps use for recurring events. This matters because it gives each occurrence a real, stable row that can be individually edited or canceled, which computing recurrence on the fly can't support cleanly.

---

### `schedule_assignment`
*A specific person filling one position within a slot.*

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | PK | — | |
| `congregation_id` | FK → congregations | not null | |
| `slot_id` | FK → schedule_slot | not null | |
| `person_id` | FK → people | not null | |
| `status` | varchar(20) | not null, default `scheduled` | `scheduled` / `confirmed` / `declined` / `completed` / `no_show` |
| `signed_up_at` | timestamp | not null | |
| `notes` | text | nullable | |
| `created_at` / `updated_at` | timestamp | not null | |

"3 needed, 1 filled" is `slot.slots_needed = 3` against a count of non-declined `schedule_assignment` rows pointing at that slot — no separate placeholder rows for unfilled positions.

**Permissions note:** open-slot self-signup means a regular volunteer needs to claim a slot for *themselves* without being able to edit anyone else's assignment or the underlying templates. The Scheduling module's permission set should include a `scheduling.signup` action distinct from `scheduling.edit` when permissions are seeded for this module.

**Independence note:** `service_id` here and `assigned_person_id` on `service_elements` (Services module) are two independent ways of recording "who's doing what." Assigning a worship leader in the order of worship doesn't automatically create a Scheduling record, and vice versa — deliberate, to keep the modules independently functional.
