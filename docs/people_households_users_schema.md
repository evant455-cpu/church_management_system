## People, Households & Users

### Overview

Three related but distinct concepts:

- A **user** is a login account — credentials and system access. Every user belongs to exactly one congregation and must correspond to a real person.
- A **person** is a directory entry — a member, regular attender, or visitor. Most people never log into anything.
- A **household** groups people together (typically a family) for mailing/communication purposes. A person can belong to more than one household (e.g. blended families, custody arrangements), so the relationship is many-to-many.

---

### `users`

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | PK | — | |
| `congregation_id` | FK → congregations | not null | One congregation per user |
| `person_id` | FK → people | not null | Every login belongs to a real person — no identity fields are duplicated on `users` |
| `email` | varchar(255) | not null, unique | Used for login |
| `password_hash` | varchar(255) | not null | |
| `is_active` | boolean | not null, default `true` | Deactivate a login without touching the person record or any historical data |
| `created_at` / `updated_at` | timestamp | not null | |

---

### `people`

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | PK | — | |
| `congregation_id` | FK → congregations | not null | |
| `first_name` | varchar(100) | not null | |
| `last_name` | varchar(100) | not null | |
| `preferred_name` | varchar(100) | nullable | |
| `email` | varchar(255) | nullable | A person's contact email — distinct from `users.email`, which only exists if they also log in |
| `phone` | varchar(30) | nullable | |
| `date_of_birth` | date | nullable | |
| `membership_status` | varchar(30) | not null, default `visitor` | `member` / `visitor` / `regular_attender` / `inactive` |
| `join_date` | date | nullable | |
| `notes` | text | nullable | |
| `is_archived` | boolean | not null, default `false` | Soft lifecycle flag — see deletion policy below |
| `archived_at` | timestamp | nullable | |
| `created_at` / `updated_at` | timestamp | not null | |

---

### `households`

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | PK | — | |
| `congregation_id` | FK → congregations | not null | |
| `name` | varchar(150) | not null | e.g. "The Smith Family" |
| `address_line1` | varchar(255) | nullable | |
| `address_line2` | varchar(255) | nullable | |
| `city` | varchar(100) | nullable | |
| `state` | varchar(100) | nullable | |
| `postal_code` | varchar(20) | nullable | |
| `country` | varchar(100) | nullable | |
| `primary_contact_person_id` | FK → people | nullable, `ON DELETE SET NULL` | Who mail/communications address by default |

---

### `person_households`
*Join table — a person can belong to more than one household.*

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | PK | — | |
| `person_id` | FK → people | not null, `ON DELETE CASCADE` | |
| `household_id` | FK → households | not null, `ON DELETE CASCADE` | |
| `congregation_id` | FK → congregations | not null | Denormalized for RLS |
| `household_role` | varchar(30) | nullable | e.g. `head` / `spouse` / `child` / `other` — per-relationship, since the same person can hold a different role in each household |
| `is_primary` | boolean | not null, default `false` | Which household is the "main" one for this person |
| `created_at` | timestamp | not null | |

*Constraints:* unique on `(person_id, household_id)`; partial unique index on `person_id` where `is_primary = true`.

---

### Deletion policy

A person is **archived by default**, and only hard-deletable when no historical data references them. This is enforced through foreign key behavior rather than custom logic — each referencing table declares a deliberate `ON DELETE` rule:

| Referencing table | FK behavior | Why |
|---|---|---|
| `staff.person_id` | `RESTRICT` | Can't delete a person while a staff record depends on them |
| `schedule_assignment.person_id` | `RESTRICT` | Preserves scheduling history |
| `giving.person_id` (when populated) | `RESTRICT` | Preserves giving history |
| `attendance_checkin.person_id` | `RESTRICT` | Preserves attendance history |
| `users.person_id` | `RESTRICT` | Can't delete a person who has a login |
| `person_households.person_id` / `household_id` | `CASCADE` | Just a relationship record, not historical data |

The application pre-checks for references before attempting a delete, so the person sees a clear "Archive instead?" message rather than a raw database error — the FK constraints are the actual backstop, the pre-check is just good UX around it.
