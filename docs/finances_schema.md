## Finances

### Overview

Finances has no module dependency on People — `giving.person_id` stays nullable, the same pattern used for Attendance's check-in. A congregation that wants per-donor giving statements needs People enabled and gifts linked to a person; a congregation that doesn't can still record and total giving, just without per-donor statements. There's no separate "donor" entity inside Finances — this avoids duplicating identity data while keeping the module independently functional.

Scoped as a full income-and-expense ledger: giving (income), expenses (disbursements), funds (designated accounts), and budgets (planned amounts compared against actuals on both sides).

**Out of scope:** an approval/request workflow for expenses (these are records of money already spent, not a purchase-approval chain), and vendor management beyond a free-text payee name.

---

### `funds`

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | PK | — | |
| `congregation_id` | FK → congregations | not null | |
| `name` | varchar(150) | not null | e.g. "General Fund", "Building Fund", "Missions" |
| `description` | text | nullable | |
| `is_active` | boolean | not null, default `true` | |
| `created_at` / `updated_at` | timestamp | not null | |

---

### `giving`

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | PK | — | |
| `congregation_id` | FK → congregations | not null | |
| `person_id` | FK → people | nullable | |
| `household_id` | FK → households | nullable | Joint gifts (e.g. a married couple) often attribute to the household rather than one individual |
| `fund_id` | FK → funds | not null | Every gift is allocated to a fund |
| `amount` | decimal(10,2) | not null | |
| `gift_date` | date | not null | |
| `payment_method` | varchar(30) | not null | `cash` / `check` / `ach` / `credit_card` / `stock` / `in_kind` / `other` |
| `check_number` | varchar(50) | nullable | |
| `batch_id` | FK → giving_batch | nullable | |
| `is_tax_deductible` | boolean | not null, default `true` | |
| `notes` | text | nullable | |
| `recorded_by_id` | FK → users | not null | |
| `created_at` / `updated_at` | timestamp | not null | |

---

### `giving_batch`
*Groups gifts entered together for reconciliation against a deposit.*

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | PK | — | |
| `congregation_id` | FK → congregations | not null | |
| `batch_date` | date | not null | |
| `expected_total` | decimal(10,2) | nullable | What the deposit slip/count says |
| `status` | varchar(20) | not null, default `open` | `open` / `reconciled` |
| `created_by_id` | FK → users | not null | |
| `created_at` / `updated_at` | timestamp | not null | |

---

### `expenses`

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | PK | — | |
| `congregation_id` | FK → congregations | not null | |
| `fund_id` | FK → funds | not null | Which fund this draws from |
| `budget_line_item_id` | FK → budget_line_item | nullable | Optional link to the specific budget category this counts against |
| `payee` | varchar(150) | not null | Free text — payees are usually not congregation members in the People directory |
| `amount` | decimal(10,2) | not null | |
| `expense_date` | date | not null | |
| `payment_method` | varchar(30) | not null | `check` / `ach` / `credit_card` / `cash` / `other` |
| `check_number` | varchar(50) | nullable | |
| `category` | varchar(150) | nullable | Useful even without a budget link |
| `receipt_url` | varchar(500) | nullable | |
| `notes` | text | nullable | |
| `recorded_by_id` | FK → users | not null | |
| `created_at` / `updated_at` | timestamp | not null | |

---

### `budget`

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | PK | — | |
| `congregation_id` | FK → congregations | not null | |
| `name` | varchar(150) | not null | e.g. "FY2026 Operating Budget" |
| `fiscal_year_start` | date | not null | |
| `fiscal_year_end` | date | not null | |
| `status` | varchar(20) | not null, default `draft` | `draft` / `active` / `closed` |
| `created_by_id` | FK → users | not null | |
| `created_at` / `updated_at` | timestamp | not null | |

---

### `budget_line_item`

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | PK | — | |
| `congregation_id` | FK → congregations | not null | |
| `budget_id` | FK → budget | not null | |
| `fund_id` | FK → funds | nullable | |
| `category` | varchar(150) | not null | e.g. "Utilities", "Staff Salaries", "Missions" |
| `line_type` | varchar(20) | not null | `income` / `expense` |
| `budgeted_amount` | decimal(10,2) | not null | |
| `notes` | text | nullable | |
| `created_at` / `updated_at` | timestamp | not null | |

---

### Fund balances are computed, not stored

A fund's balance is deliberately **not** a stored column — it's:

```
SUM(giving.amount WHERE fund_id = X) − SUM(expenses.amount WHERE fund_id = X)
```

computed from the transaction tables every time it's needed, rather than maintained as a running total that could drift out of sync with the rows that are supposed to back it. "Actual vs. budgeted" for a line item works the same way — sum the relevant `giving` or `expenses` rows over the budget's date range and compare against `budgeted_amount`, rather than caching a number that needs to be kept correct by hand.
