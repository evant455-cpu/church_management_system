# church_management_system

A simple, scalable church management platform offered as a 
self-service SaaS product for congregations of all sizes.

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

Each congregation activates only the features they need. The 
dashboard surfaces only what is enabled — keeping the interface 
clean for staff regardless of church size or complexity.

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

Modules can be toggled on or off at any time by a congregation 
admin. The dashboard adapts automatically to show only active 
modules.

## Module Management

Module selection is not a one-time choice. Congregation admins 
can enable or disable any module at any time from their settings 
panel.

- Enabling a module makes it immediately available on the dashboard
- Disabling a module hides it from the dashboard but **preserves all data**
- Re-enabling a module restores full access to existing records

This keeps the system flexible as a congregation grows, 
restructures, or changes how they operate.

## Product Model

church_management_system is offered as a Software as a Service 
(SaaS).

- Congregations sign up and manage their own account
- Each congregation's data is fully isolated from all others
- Module access is self-managed by the congregation's admin
- Billing is handled per congregation based on their subscription

## Subscription Model

church_management_system operates on a single subscription tier.

- One subscription gives a congregation access to the entire system
- Billing may be offered on a monthly or annual basis
- Module usage is entirely the congregation's choice — not gated by plan
- A lapsed subscription places the account in **read-only mode**
- Full access is restored immediately upon renewal

## Data Ownership

All data entered into the system belongs to the congregation — 
not the platform.

- Data is never deleted due to a lapsed subscription
- Congregations in read-only mode can view all existing records
  but cannot add or update anything until payment is renewed
- Congregations retain the right to export their data at any time

## Goals

- Simple enough for a small congregation with no IT staff
- Scalable enough to handle a large church's complexity
- Role-based access so staff only see what they need
- Self-service from signup to daily operation

## Stack

- **Language** — Python
- **Framework** — Django
- **Database** — PostgreSQL
- **Editor** — Cursor

## Database Design

church_management_system uses PostgreSQL as its database.
Tables are organized around the core domains of the system:

- **congregations** — each church using the platform as a tenant
- **subscriptions** — billing status and cycle per congregation
- **congregation_modules** — which modules each congregation has enabled
- **congregation_module_history** — full audit trail of module changes
- **users** — staff and admins with role-based access
- **people** — congregation members and contacts
- **households** — family units linked to people
- **staff** — staff records linked to people
- **services** — individual church services
- **attendance** — attendance records per person per service
- **schedules** — staff and volunteer scheduling
- **announcements** — congregation-wide communications
- **giving** — individual donation records
- **funds** — designated budget categories
- **budgets** — budget tracking per fund

All tables include a congregation_id ensuring complete data 
isolation between congregations.

## Module Registry

The module registry is the core of the modular system. It maintains 
a master list of all available modules in code, and tracks which 
modules each congregation has enabled in the database.

Each module definition includes:
- **name** — unique identifier
- **label** — display name
- **description** — shown to congregation admins
- **icon** — displayed on module cards
- **enabled_by_default** — whether it activates on signup

All modules are always visible to congregation admins — including 
disabled ones — so they always know what options are available. 
Modules are presented as cards with descriptions and a simple 
toggle. The Manage Modules panel is accessible directly from 
the dashboard.

## Onboarding Flow

New congregations go through a five step self-service onboarding:

1. **Create Account** — admin name, email, password, terms of service
2. **Congregation Profile** — name, address, phone, approximate size
3. **Subscription** — billing cycle selection and payment
4. **Choose Modules** — select which modules to activate, 
   pre-suggested based on congregation size, changeable at any time
5. **Welcome Dashboard** — dashboard loads with chosen modules active,
   brief tooltip tour, Manage Modules prominently accessible

## Getting Started

> Setup instructions coming as the project takes shape

## Status

Early planning / scaffolding phase
