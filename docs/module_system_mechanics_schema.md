## Module System Mechanics

### Overview

Two things make up the module system: a **registry** of what modules exist (canonical source: code, mirrored into the database for referential integrity), and **per-congregation state** tracking which modules are enabled, when, by whom, and what depends on what.

Module code itself (views, models, business logic) only exists because it's been written and deployed — no amount of database configuration substitutes for that. What the database layer adds is: a real FK target for `permissions.module` and dependency relationships, an audit trail of every toggle, and enforced consistency for the small number of modules that have genuine structural dependencies on each other.

---

### `modules`
*System-wide, auto-synced from the code registry on migrate. Not tenant-scoped.*

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | PK | — | |
| `key` | varchar(50) | not null, unique | Stable identifier matching the code registry (`people`, `staff`, `attendance`, `scheduling`, `services`, `announcements`, `finances`) |
| `name` | varchar(100) | not null | Display name |
| `description` | text | nullable | Shown on the module toggle card |
| `sort_order` | integer | not null, default 0 | Controls dashboard/toggle-list ordering |
| `is_retired` | boolean | not null, default `false` | For if a module is ever sunset — preserves history and FK integrity without deleting the row |
| `created_at` | timestamp | not null | |

---

### `module_dependencies`
*System-wide, auto-synced from the code registry alongside `modules`.*

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | PK | — | |
| `module_id` | FK → modules | not null | The dependent module (e.g. Scheduling) |
| `depends_on_module_id` | FK → modules | not null | The prerequisite (e.g. People) |
| `created_at` | timestamp | not null | |

*Constraints:* unique on `(module_id, depends_on_module_id)`; check `module_id != depends_on_module_id`.

**Seeded relationships (v1):**

| Module | Depends on |
|---|---|
| Staff | People |
| Scheduling | People |

Attendance and Finances have no module-level dependency — they remain independently toggleable. (Finances may end up wanting *some* donor-identity concept for giving statements, but that's a question for Finances' own internal data model, not a module-dependency question.)

---

### `congregation_modules`
*Tenant-scoped. One row per (congregation, module) pair, created eagerly at signup for every module.*

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | PK | — | |
| `congregation_id` | FK → congregations | not null | Tenant scope |
| `module_id` | FK → modules | not null | |
| `is_enabled` | boolean | not null, default `false` | |
| `enabled_at` | timestamp | nullable | |
| `enabled_by_id` | FK → users | nullable | |
| `disabled_at` | timestamp | nullable | |
| `disabled_by_id` | FK → users | nullable | |

*Constraint:* unique on `(congregation_id, module_id)`.

*Row lifecycle:* every congregation gets one row per module at signup (`is_enabled=false`, except whatever was selected during onboarding's module-selection step). When a new module ships in the future, a migration backfills a disabled row for every existing congregation — there's never an "absent" state to special-case in queries.

---

### `congregation_module_history`
*Tenant-scoped, append-only audit log — every toggle event, forever.*

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | PK | — | |
| `congregation_id` | FK → congregations | not null | |
| `module_id` | FK → modules | not null | |
| `action` | varchar(10) | not null, choices: `enabled`, `disabled` | |
| `changed_by_id` | FK → users | not null | |
| `changed_at` | timestamp | not null | |

---

### The access gate

Every request to a module-owned view passes through two sequential checks, in this order:

1. **Is the module enabled for this congregation?** (`congregation_modules.is_enabled`) — if not, the feature is inaccessible regardless of who's asking.
2. **Does this user have the relevant permission?** (role + override resolution from the auth layer.)

Module-gate-first means a user's `finances.edit` permission simply sits inert while Finances is disabled, rather than needing to be actively stripped and restored on every toggle. Disabling a module never touches `roles`, `user_roles`, or any data row — it's purely a flag flip on `congregation_modules`.

---

### Dependency enforcement

**Enabling** Scheduling or Staff is blocked at the application layer unless People is already enabled for that congregation, with a clear validation message (e.g. "Enable People before enabling Scheduling.").

**Disabling** People while a dependent module is enabled triggers a confirmation flow rather than a dead-end error:

1. App detects Scheduling and/or Staff are currently enabled for this congregation
2. User sees a confirmation prompt: *"Disabling People will also disable: Scheduling, Staff. Continue?"*
3. On confirm, all affected modules are disabled in a single transaction — dependents first, then People — with a `congregation_module_history` row logged for each
4. On cancel, nothing changes

**Database-level backstop:** a Postgres trigger on `congregation_modules` rejects any update that would leave the system in an inconsistent state — a prerequisite disabled while a dependent is still enabled — regardless of which code path issued the update. This guards against a future bug or a direct database edit bypassing the cascade logic above; it should never fire in normal operation, since the application logic always disables dependents before the prerequisite within the same transaction. Sketch of the enforcement logic:

```sql
-- Illustrative — refine field names/exception handling during implementation
CREATE OR REPLACE FUNCTION check_module_dependency_consistency()
RETURNS TRIGGER AS $$
BEGIN
  IF NEW.is_enabled = false AND OLD.is_enabled = true THEN
    IF EXISTS (
      SELECT 1
      FROM congregation_modules cm
      JOIN module_dependencies md ON md.module_id = cm.module_id
      WHERE cm.congregation_id = NEW.congregation_id
        AND md.depends_on_module_id = NEW.module_id
        AND cm.is_enabled = true
    ) THEN
      RAISE EXCEPTION 'Cannot disable this module while a dependent module is still enabled';
    END IF;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER enforce_module_dependency_consistency
BEFORE UPDATE ON congregation_modules
FOR EACH ROW
EXECUTE FUNCTION check_module_dependency_consistency();
```

---

### Structural consequences

Because People is now a guaranteed prerequisite for Staff and Scheduling, the tables that reference a person from within those modules no longer need a nullable fallback:

- `staff.person_id` — `FK → people`, **not null**
- `schedule_assignment.person_id` — `FK → people`, **not null**

Attendance and Finances, having no module dependency on People, keep any person-reference fields **nullable** where they exist, since those modules must remain fully functional whether or not People is enabled.
