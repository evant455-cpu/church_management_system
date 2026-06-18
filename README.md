# church_management_system

A simple, scalable church management platform offered as a self-service 
SaaS product for congregations of all sizes.

## What It Does

Gives church staff and leadership a single place to manage:

- **People & Staff** — member directory, households, staff records and roles
- **Attendance** — service check-in, headcounts, trends
- **Scheduling** — staff and volunteer scheduling
- **Services** — service planning, order of worship
- **Announcements** — church-wide communications
- **Finances** — giving records, budgets, fund tracking

## Design Philosophy

church_management_system is built around **optional modules**.

Each congregation activates only the features they need. The dashboard
surfaces only what is enabled — keeping the interface clean for staff
regardless of church size or complexity.

### Available Modules

| Module        | Description                              |
|---------------|------------------------------------------|
| People        | Member directory, households, contacts   |
| Staff         | Staff records and roles                  |
| Attendance    | Check-in, headcounts, trends             |
| Scheduling    | Staff and volunteer scheduling           |
| Services      | Service planning, order of worship       |
| Announcements | Church-wide communications               |
| Finances      | Giving, budgets, fund tracking           |

Modules can be toggled on or off at any time by a congregation admin.
The dashboard adapts automatically to show only active modules.

## Module Management

Module selection is not a one-time choice. Congregation admins can
enable or disable any module at any time from their settings panel.

- Enabling a module makes it immediately available on the dashboard
- Disabling a module hides it from the dashboard but **preserves all data**
- Re-enabling a module restores full access to existing records

This keeps the system flexible as a congregation grows, restructures,
or changes how they operate.

## Product Model

church_management_system is offered as a Software as a Service (SaaS).

- Congregations sign up and manage their own account
- Each congregation's data is fully isolated from all others
- Module access is self-managed by the congregation's admin
- Billing is handled per congregation based on their subscription

## Goals

- Simple enough for a small congregation with no IT staff
- Scalable enough to handle a large church's complexity
- Role-based access so staff only see what they need
- Self-service from signup to daily operation

## Stack

- **Backend**: Python 3.14 / Django 6.0 (LTS-track)
- **Database**: PostgreSQL 18, shared-schema multi-tenancy (`congregation_id` row-level tenancy + Postgres RLS)
- **Dependency/env management**: [uv](https://docs.astral.sh/uv/)
- **Settings**: single `config/settings.py`, configured entirely via environment variables (`django-environ`) — see `.env.example`
- **Local Postgres**: Docker Compose
- **Payments**: Stripe (subscriptions mirrored into the app via webhooks)

Full architecture decisions (multi-tenancy, roles & permissions, module system, billing state machine, per-module schemas) are documented in `docs/`.

## Project Structure

```
config/             Django project package — settings, urls, wsgi/asgi
apps/
  tenancy/           congregations, owner relationship, signup orchestration
  billing/           subscriptions, subscription_events (Stripe-mirrored)
  module_system/     modules, module_dependencies, congregation_modules
  permissions/       permissions, roles, role_permissions, user_roles, overrides
  accounts/          custom User model (AUTH_USER_MODEL)
  people/             people, households, person_households       [toggleable module]
  staff/              staff records, position history              [toggleable module]
  attendance/         attendance_session, attendance_checkin        [toggleable module]
  scheduling/         schedule_template, schedule_slot, assignment  [toggleable module]
  services/           services, service_elements, templates         [toggleable module]
  announcements/      announcements                                 [toggleable module]
  finances/           funds, giving, expenses, budgets               [toggleable module]
docs/                Architecture & schema docs (source of truth for design decisions)
```

`tenancy`, `billing`, `module_system`, `permissions`, and `accounts` are always-on platform concerns — distinct from the seven feature modules a congregation can toggle on/off.

## Getting Started

**Prerequisites**: [uv](https://docs.astral.sh/uv/getting-started/installation/) installed, [Docker Desktop](https://www.docker.com/products/docker-desktop/) running.

```bash
# 1. Install dependencies (uv manages the Python interpreter + venv itself)
uv sync

# 2. Copy env template and fill in real values
cp .env.example .env
# .env already has working local defaults that match docker-compose.yml,
# but you'll need to generate your own DJANGO_SECRET_KEY:
uv run python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"

# 3. Start Postgres
docker compose up -d

# 4. Run migrations
uv run python manage.py migrate

# 5. Create an admin user (optional, for /admin/)
uv run python manage.py createsuperuser

# 6. Run the dev server
uv run python manage.py runserver
```

Then visit `http://127.0.0.1:8000/admin/`.

## Status

Phase 0 complete: project scaffold running locally (Django project structure, domain-driven app layout, env-based settings, Docker Compose Postgres). No models/business logic implemented yet — that's next.
