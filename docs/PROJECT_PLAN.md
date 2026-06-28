# Project Plan — church_management_system

## How to use this document

Each phase below gets its own chat. A phase isn't "done" until its
deliverables are actually verified (real tests/manual runs, not just code
that looks right) and committed to git — only then does the next phase's
chat start. This exists specifically to prevent scope creep: if a phase
chat starts drifting into another phase's territory, this doc is the thing
to point back at.

Update the checklist below as phases complete.

- [x] Phase 0 — Project Scaffold
- [x] Phase 1 — Accounts, People & Tenancy (core data models)
- [x] Phase 2 — Module System Mechanics
- [x] Phase 3 — Roles & Permissions Engine
- [x] Phase 4 — Billing & Subscription State
- [x] Phase 5 — Onboarding & Signup Sequence
- [ ] Phase 6 — People & Households (feature module)
- [ ] Phase 7 — Staff
- [ ] Phase 8 — Attendance
- [ ] Phase 9 — Scheduling
- [ ] Phase 10 — Services
- [ ] Phase 11 — Announcements
- [ ] Phase 12 — Finances
- [ ] Phase 13 — Dashboard & cross-module polish / deployment prep

---

## Phase 0 — Project Scaffold ✅ Complete

**Goal:** a working Django project running locally.

**Delivered:** domain-driven app layout (`apps/tenancy`, `billing`,
`module_system`, `permissions`, `accounts`, plus the seven feature-module
apps), single `config/settings.py` reading config via `django-environ`,
Docker Compose Postgres, Windows Python/PATH situation resolved (turned out
to be mostly a non-issue — `uv` install + PowerShell `where`-alias
confusion), `uv` toolchain confirmed working end-to-end against real
Postgres with the dev server serving requests.

---

## Phase 1 — Accounts, People & Tenancy (core data models) ✅ Complete

**Goal:** the foundational "who exists in the system" data layer and basic
auth — no signup wizard yet.

**Delivered:** `accounts.User(AbstractBaseUser, PermissionsMixin,
TenantScopedModel)` replacing the Phase 0 placeholder (email-as-login,
required `congregation`/`person` FKs, PermissionsMixin kept in full as a
platform-operator Django Admin escape hatch, deliberately separate from
Phase 3's RBAC); `apps/tenancy.Congregation` with nullable `owner_user`
per the documented circular-dependency resolution, plus a shared
`TenantScopedModel` abstract base; `apps/people` models (`Person`,
`Household`, `PersonHousehold`) with the documented FK on_delete
behaviors and the partial-unique primary-household constraint; working
login/logout/password-reset views with real templates (catching and
fixing a template-shadowing bug from `django.contrib.admin` along the
way); custom Django Admin forms so admin-based test-data creation
actually works end to end. 34 tests passing against real Postgres (not
sqlite), run both in the build sandbox and locally.

**Builds:**
- Finalize `accounts.User` (replace the Phase 0 placeholder): email-as-login,
  `congregation_id`/`person_id` FKs per `people_households_users_schema.md`,
  decide on dropping the username field and whether `PermissionsMixin` is
  needed given the app's own RBAC system (Phase 3)
- `people`, `households`, `person_households` models, including the
  deletion/archival policy FK behaviors (`RESTRICT` / `CASCADE` per the
  documented table)
- `congregations` model (`tenancy` app), `owner_user_id` nullable per the
  documented circular-dependency resolution
- Basic login / logout / password reset views

**Depends on:** Phase 0

**Out of scope:** signup wizard (Phase 5), roles/permissions (Phase 3), any
module gating (Phase 2). Congregations and users can be created via Django
admin/shell for testing purposes in this phase.

---

## Phase 2 — Module System Mechanics

**Goal:** the module registry, per-congregation enablement, and the first
layer of the access gate.

**Builds:**
- `modules`, `module_dependencies` (synced from the code registry)
- `congregation_modules`, `congregation_module_history`
- Access gate layer 1: "is this module enabled for this congregation"
- Dependency enforcement: People → Staff/Scheduling at the application
  layer, the cascade-disable confirmation flow, and the Postgres trigger
  backstop

**Depends on:** Phase 1 (congregations must exist)

**Out of scope:** permission checks (Phase 3), billing checks (Phase 4) —
the access gate is intentionally partial after this phase.

---

## Phase 3 — Roles & Permissions Engine

**Goal:** the full RBAC layer and the second layer of the access gate.

**Builds:**
- `permissions` global catalog, seeded from the module registry
- `roles`, `role_permissions`, `user_roles`, `user_permission_overrides`
- Effective-permissions resolution (union of role permissions, plus
  override-grants, minus override-revokes)
- Default-system-roles-copy as a reusable service (owner / admin / staff /
  finance / volunteer)
- Access gate layer 2: permission check

**Depends on:** Phase 2 (module registry exists for the permission catalog
to reference)

**Out of scope:** billing checks (Phase 4), wiring any of this into a real
signup flow (Phase 5).

---

## Phase 4 — Billing & Subscription State

**Goal:** the Stripe-backed subscription state machine and the third/final
layer of the access gate.

**Builds:**
- `subscriptions`, `subscription_events`
- Stripe SetupIntent → Customer → Subscription flow scaffolding
- Webhook handler + Stripe-status → app-status mapping
- Access gate layer 3: billing-status check, including the Owner
  billing-area carve-out

**Depends on:** Phase 1 (congregations)

**Out of scope:** the actual signup wizard UI (Phase 5).

---

## Phase 5 — Onboarding & Signup Sequence

**Goal:** the first true end-to-end flow — a real congregation can sign up,
log in, and land on a dashboard.

**Builds:**
- Multi-step signup wizard (account → congregation profile →
  subscription/card → module selection)
- The one atomic transaction tying together congregations, people, users,
  roles, congregation_modules, subscriptions, subscription_events, and
  congregation_module_history
- Compensating Stripe-cancellation logic if the local transaction fails
  after the Stripe calls already succeeded

**Depends on:** Phases 1–4, all complete

**Out of scope:** feature-module UI (Phases 6–12) — the post-signup
dashboard can be a stub at this point.

---

## Phase 6 — People & Households (feature module)

**Goal:** the actual People directory feature, on top of Phase 1's models.

**Builds:** directory CRUD, search, household management UI, archive/
restore flows enforcing the deletion policy.

**Depends on:** Phase 5 (need a real congregation/login to test against),
Phase 2 (module gating), Phase 3 (permission gating)

---

## Phase 7 — Staff

**Goal:** the HR/employment-classification feature.

**Builds:** staff CRUD, position-history audit log, org chart
(`supervisor_staff_id` self-reference).

**Depends on:** Phase 6 (People module enabled — Staff has a hard module
dependency on People)

---

## Phase 8 — Attendance

**Goal:** headcount + check-in feature.

**Builds:** `attendance_session`, `attendance_checkin`, the unique
constraint on `(session_id, person_id)`, confirmed working with or without
People enabled.

**Depends on:** Phase 5 (no module dependency on People — can be built any
time after onboarding exists)

---

## Phase 9 — Scheduling

**Goal:** recurring needs + slot-filling feature.

**Builds:** `schedule_template`, `schedule_slot` (with the background
materialization job), `schedule_assignment`, open-slot self-signup (the
`scheduling.signup` permission distinct from `scheduling.edit`), the
"3 needed, 1 filled" counting logic.

**Depends on:** Phase 7 (People hard dependency)

---

## Phase 10 — Services

**Goal:** order-of-worship planning.

**Builds:** `services`, `service_elements`, `service_template`,
`service_template_elements`, the template → service copy-on-create logic.

**Depends on:** Phase 5

---

## Phase 11 — Announcements

**Goal:** broadcast communications.

**Builds:** announcements CRUD, scheduling (`publish_at` / `expires_at`).

**Depends on:** Phase 5

---

## Phase 12 — Finances

**Goal:** the giving/expense/budget ledger.

**Builds:** `funds`, `giving`, `giving_batch`, `expenses`, `budget`,
`budget_line_item`, computed fund-balance and budget-actuals logic.

**Depends on:** Phase 5

---

## Phase 13 — Dashboard & cross-module polish / deployment prep

**Goal:** tie everything together for a real launch.

**Builds:** module-aware dashboard, cross-module integration check,
production deployment checklist (real Stripe keys, real
`DJANGO_SECRET_KEY`, `ALLOWED_HOSTS`, static file serving, etc.)

**Depends on:** all prior phases
