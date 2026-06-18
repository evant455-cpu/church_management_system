## Subscription & Billing State

### Overview

The product has a single subscription tier — no plan comparison logic needed, just whether a congregation's account is current. Payment processing is handled by **Stripe**, which also provides built-in dunning (automatic retries on a failed card, reminder emails, a defined grace window) — the app doesn't reimplement any of that, it just mirrors Stripe's subscription status into its own `subscriptions` table via webhooks.

Signup includes a free trial, but a card is required upfront: a real Stripe subscription object is created at signup with `trial_period_days` set, rather than deferring card collection until the trial ends.

### Status model

| Status | Meaning | App access |
|---|---|---|
| `trialing` | In the free trial period | Full access |
| `active` | Paying, current | Full access |
| `past_due` | A charge failed, Stripe is retrying | Full access + billing warning banner — **not** read-only |
| `read_only` | Stripe's retries exhausted | Read-only, data fully preserved |
| `canceled` | Congregation canceled and the paid period has now ended | Read-only, data fully preserved |

Voluntary cancellation does **not** cause an immediate access change — Stripe doesn't end a subscription early just because cancellation was requested, so `status` correctly stays `active` until the paid period genuinely ends, at which point a webhook flips it to `canceled`. No special-case logic is needed in the access gate to support "keep access until period end."

---

### `subscriptions`

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | PK | — | |
| `congregation_id` | FK → congregations | not null, unique | One subscription per congregation |
| `stripe_customer_id` | varchar(255) | not null | |
| `stripe_subscription_id` | varchar(255) | not null | Created at signup, with trial period set via Stripe |
| `status` | varchar(20) | not null | `trialing` / `active` / `past_due` / `read_only` / `canceled` |
| `cancel_at_period_end` | boolean | not null, default `false` | Display-only flag (e.g. "your subscription ends on [date]") — access logic relies on `status`, not this field |
| `trial_ends_at` | timestamp | nullable | |
| `current_period_start` | timestamp | nullable | |
| `current_period_end` | timestamp | nullable | |
| `canceled_at` | timestamp | nullable | |
| `created_at` | timestamp | not null | |
| `updated_at` | timestamp | not null | |

---

### `subscription_events`
*Append-only audit log, same pattern as `congregation_module_history`.*

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | PK | — | |
| `congregation_id` | FK → congregations | not null | |
| `event_type` | varchar(50) | not null | e.g. `trial_started`, `payment_succeeded`, `payment_failed`, `canceled`, `reactivated` |
| `source` | varchar(20) | not null | `stripe_webhook` or `admin_action` |
| `stripe_event_id` | varchar(255) | nullable | For idempotency — Stripe can redeliver the same webhook |
| `occurred_at` | timestamp | not null | |

Stripe's own status vocabulary is richer than the app's 5-state model (it distinguishes `incomplete`, `unpaid`, etc.) — the webhook handler maps the incoming Stripe status down to one of the 5 app statuses for `subscriptions.status`, while logging the original Stripe event type into `subscription_events` for full audit fidelity.

---

### Where this sits in the access gate

Billing state is checked **first**, before tenant scoping matters for "can this person write anything at all":

1. **Subscription status** — if `read_only` or `canceled`, all write operations are blocked account-wide. Reads still work.
2. **Module enabled?**
3. **Permission check?**

**Exception:** the Owner must always be able to reach billing/account-management endpoints (re-enter a card, reactivate) even while everything else is locked — so the read-only gate explicitly carves out the billing area rather than blocking it like every other write.
