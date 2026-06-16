# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Status

Early planning / scaffolding phase. The technology stack has not yet been chosen. No build, test, or run commands exist yet — update this file as the stack is decided and scaffolding is added.

## What This Is

A self-service SaaS platform for church management. Congregations sign up, configure their own account, and manage staff, members, and operations through a single dashboard. Each congregation's data is fully isolated from all others (multi-tenant).

## Core Architectural Constraints

These decisions are already made and must be honored by all implementation choices:

**Multi-tenant isolation**: Every data record belongs to a congregation. No query should ever return data across congregation boundaries. Enforce tenancy at the data layer, not just the UI.

**Modular feature flags**: The system is built around seven optional modules. A congregation admin can enable or disable any module at any time. Disabling a module hides it from the dashboard and blocks access to its routes/APIs, but **must never delete or alter the underlying data**. Re-enabling restores full access to existing records.

**Dashboard adapts to active modules**: The dashboard only surfaces enabled modules. Navigation, widgets, and quick-actions must be dynamically driven by the set of active modules for the authenticated congregation.

**Role-based access**: Staff only see what their role permits within a congregation.

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
- Billing is per congregation based on subscription tier
