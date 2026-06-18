## Roles & Permissions

### Overview

Access control is built from two layers that combine at query time:

1. **Roles** — named bundles of permissions, scoped per congregation. Each congregation gets its own copy of the system default roles at signup, which it can then rename, edit, or leave alone. Congregations can also create entirely custom roles.
2. **Per-user overrides** — individual grants or revokes layered on top of whatever role(s) a user holds, for cases where a role is *almost* right but one person needs an exception.

A user's **effective permissions** = (union of all permissions from all roles assigned to them) **plus** any override-granted permissions **minus** any override-revoked permissions.

Permissions themselves are expressed as `(module, action)` pairs (e.g. `finances.edit`, `attendance.checkin`) and are **not** tenant-scoped — the catalog of possible actions is the same for every congregation, since it's derived from the module registry already defined in code (`AVAILABLE_MODULES`). Roles, role assignments, and overrides *are* tenant-scoped, like every other operational table, and carry `congregation_id` for row-level tenancy + RLS.

---

### `permissions`
*Global, system-wide catalog. Not tenant-scoped.*

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | PK | — | |
| `module` | varchar(50) | not null | Matches a key in the `AVAILABLE_MODULES` registry (e.g. `finances`, `attendance`) |
| `action` | varchar(50) | not null | e.g. `view`, `edit`, `manage`, `checkin`, `publish` |
| `code` | varchar(100) | not null, unique | `{module}.{action}`, e.g. `finances.edit` — convenience field for lookups/checks in code |
| `description` | text | nullable | Human-readable explanation, shown in the permission-editing UI |
| `created_at` | timestamp | not null | |

---

### `roles`
*Tenant-scoped. Includes both congregation-customized copies of system defaults and fully custom roles.*

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | PK | — | |
| `congregation_id` | FK → congregations | not null | Tenant scope |
| `name` | varchar(100) | not null | Display name, editable by the congregation (e.g. "Staff", "Children's Ministry Lead") |
| `slug` | varchar(50) | not null | Stable identifier set at creation (e.g. `owner`, `admin`, `staff`, `finance`, `volunteer`, or a generated slug for custom roles) — used for business rules, not display |
| `is_system_default` | boolean | not null, default `false` | True if this role originated from the system template set (still independently editable per congregation) |
| `is_deletable` | boolean | not null, default `true` | False for `owner` — every congregation must always have an Owner role |
| `created_at` | timestamp | not null | |
| `updated_at` | timestamp | not null | |

*Constraint:* unique on `(congregation_id, slug)` — prevents duplicate system-role copies within one congregation, while still allowing the same slug across different congregations.

---

### `role_permissions`
*Join table: which permissions a role grants.*

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | PK | — | |
| `role_id` | FK → roles | not null | |
| `permission_id` | FK → permissions | not null | |
| `created_at` | timestamp | not null | |

*Constraint:* unique on `(role_id, permission_id)`.

---

### `user_roles`
*Which role(s) a user holds. A user may hold more than one role (e.g. Staff + Finance).*

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | PK | — | |
| `user_id` | FK → users | not null | |
| `role_id` | FK → roles | not null | |
| `congregation_id` | FK → congregations | not null | Denormalized from `role.congregation_id` for fast RLS filtering and to guard against cross-tenant assignment bugs |
| `created_at` | timestamp | not null | |

*Constraint:* unique on `(user_id, role_id)`. Application-level check: `user.congregation_id == role.congregation_id` before insert (defense alongside RLS).

---

### `user_permission_overrides`
*Per-user exceptions layered on top of role-derived permissions.*

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | PK | — | |
| `user_id` | FK → users | not null | |
| `permission_id` | FK → permissions | not null | |
| `congregation_id` | FK → congregations | not null | Denormalized for RLS, same rationale as above |
| `effect` | varchar(10) | not null, choices: `grant`, `revoke` | |
| `created_by_id` | FK → users | not null | Audit trail — who made this override |
| `created_at` | timestamp | not null | |
| `updated_at` | timestamp | not null | |

*Constraint:* unique on `(user_id, permission_id)` — one override record per user/permission pair; updating it changes `effect` rather than inserting a duplicate.

---

### Enforcing exactly one Owner

Rather than relying on a count of `user_roles` rows (which could drift), the single-Owner rule is anchored on the `congregations` table itself:

| Field added to `congregations` | Type | Constraints | Description |
|---|---|---|---|
| `owner_user_id` | FK → users | not null | The single source of truth for ownership |

The Owner *role* is still assigned normally via `user_roles` (so Owner participates in the same permission-resolution logic as every other role, with no special-cased code path) — but `congregations.owner_user_id` is what's actually checked anywhere "is this the owner?" matters (billing, account deletion, transferring ownership). Transferring ownership becomes: update `owner_user_id`, then adjust `user_roles` for the old and new owner accordingly.

---

### Default system roles (copied into every congregation at signup)

| Role (`slug`) | Default permissions |
|---|---|
| `owner` | All permissions across all enabled modules, plus billing/account settings (handled outside the module-permission system) |
| `admin` | All permissions across all enabled modules (not billing/account settings) |
| `staff` | `people.*`, `attendance.*`, `scheduling.*`, `services.*`, `announcements.*` — not `finances.*` |
| `finance` | `finances.*` only |
| `volunteer` | `attendance.checkin` only |

These are starting points, fully editable per congregation — editing a congregation's copy of "Staff" never affects any other congregation's "Staff" role, since each congregation owns its own row in `roles`.
