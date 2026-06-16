# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Status

Early planning / scaffolding phase. No build, test, or run commands exist yet — update this file as scaffolding is added.

## What This Is

A self-service SaaS platform for church management. Congregations sign up, configure their own account, and manage staff, members, and operations through a single dashboard. Each congregation's data is fully isolated from all others (multi-tenant).

## Tech Stack

- **Language** — Python
- **Framework** — Django
- **Database** — PostgreSQL
- **Editor** — Cursor

## Core Architectural Constraints

These decisions are already made and must be honored by all implementation choices:

**Multi-tenant isolation**: Every data record belongs to a congregation. No query should ever return data across congregation boundaries. Enforce tenancy at the data layer, not just the UI.

**Modular feature flags**: The system is built around seven optional modules. A congregation admin can enable or disable any module at any time. Disabling a module hides it from the dashboard and blocks access to its routes/APIs, but **must never delete or alter the underlying data**. Re-enabling restores full access to existing records.

**Dashboard adapts to active modules**: The dashboard only surfaces enabled modules. Navigation, widgets, and quick-actions must be dynamically driven by the set of active modules for the authenticated congregation.

**Role-based access**: Staff only see what their role permits within a congregation.

**Subscription read-only mode**: A lapsed subscription locks the account to read-only — no creates or updates until payment is renewed. Full access restores immediately on renewal. Data is never deleted due to a lapsed subscription.

**Data ownership**: All data belongs to the congregation. Congregations must always be able to export their data.

## Modules

| Module        | Description                                      |
|---------------|--------------------------------------------------|
| People        | Member directory, households, contacts           |
| Staff         | Staff records and roles                          |
| Attendance    | Check-in, headcounts, trends                     |
| Scheduling    | Staff and volunteer scheduling                   |
| Services      | Service planning, order of worship               |
| Announcements | Church-wide communications                       |
| Finances      | Giving records, budgets, fund tracking           |

## Key Design Goals

- Simple enough for a small congregation with no IT staff
- Scalable to large church complexity
- Self-service from signup through daily operation
- Single subscription tier — all modules available to every congregation, no feature gating by plan

## Database Tables

Tables are implemented as Django models. Each table includes a 
`congregation_id` foreign key to enforce data isolation between 
tenants. Tables:

```
congregations, subscriptions, congregation_modules,
congregation_module_history, users, people, households,
staff, services, attendance, schedules, announcements,
giving, funds, budgets
```

Run migrations with:
```bash
python manage.py makemigrations
python manage.py migrate
```

## Module Registry

Defined in `src/modules/registry/`. Contains:

- `AVAILABLE_MODULES` — master list of all modules in code
- Each module has: name, label, description, icon, 
  enabled_by_default
- Runtime logic checks `congregation_modules` table to determine
  what to render on the dashboard
- All modules always visible to admins, enabled or not
- Changes logged to `congregation_module_history`

## Onboarding Flow

Lives in `src/platform/onboarding/`. Five steps:

1. Create Account
2. Congregation Profile
3. Subscription & Billing
4. Module Selection
5. Welcome Dashboard

Congregation size collected at step 2 is used to pre-suggest 
modules at step 4.

## Key Conventions

- Every model includes `congregation_id` for tenant isolation
- Module enable/disable always writes to audit history
- Data is never hard deleted — use `is_active` flags
- Lapsed subscriptions trigger read-only mode, never data loss
