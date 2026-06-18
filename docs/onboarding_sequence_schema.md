## Onboarding & Signup Sequence

### Overview

Signup is the one moment where nearly every other piece of this system has to interlock correctly for the first time. Two structural wrinkles surfaced while designing it, both resolved deliberately rather than discovered later:

1. **A circular dependency**: `congregations.owner_user_id` and `users.congregation_id`/`users.person_id` are all `NOT NULL`, but a congregation needs a user to exist before it can be created, and a user needs a congregation to exist before *it* can be created. Postgres can defer foreign key checks within a transaction, but not `NOT NULL` checks. Resolution: `congregations.owner_user_id` is nullable at the schema level — the "always has exactly one owner" guarantee shifts from a database constraint to an application invariant, enforced by having exactly one code path (the signup service) permitted to insert a `congregations` row, which always sets `owner_user_id` before committing. Transaction isolation means no other part of the system ever observes a congregation row without an owner.

2. **Stripe calls are external HTTP requests, not part of our database transaction.** Since `subscriptions.stripe_subscription_id` is `NOT NULL`, the Stripe customer/subscription must be created *before* the local transaction — which risks an orphaned Stripe subscription if the local transaction then fails. Resolution: validate the card early via a Stripe SetupIntent (no recurring subscription created yet), and defer actual Customer/Subscription creation to the final atomic commit step. An abandoned signup before that point leaves nothing dangerous on either side — no database rows, and only an unused SetupIntent on Stripe's side, which Stripe expires on its own.

---

### `congregations`
*Previously referenced throughout the schema but not yet fielded.*

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | PK | — | |
| `name` | varchar(200) | not null | |
| `owner_user_id` | FK → users | nullable | Application guarantees this is always set immediately after creation — see above |
| `timezone` | varchar(50) | not null | Needed to correctly interpret service/schedule/attendance timestamps |
| `address_line1` / `address_line2` / `city` / `state` / `postal_code` / `country` | varchar | nullable | |
| `size_category` | varchar(30) | nullable | e.g. `1-50`, `51-200` — optional, for onboarding personalization |
| `created_at` / `updated_at` | timestamp | not null | |

---

### Signup sequence

**Steps 1–4 of the wizard (Create account → Congregation profile → Subscription → Module selection)** collect data into session state only — nothing is written to the database yet. Step 3 specifically: the card is collected via Stripe Elements and confirmed as a **SetupIntent**, validating it and returning a reusable PaymentMethod, without creating a Stripe Customer or Subscription.

**On "Finish" (the transition into the welcome dashboard):**

1. Create the Stripe Customer, attach the validated PaymentMethod as default.
2. Create the Stripe Subscription on that customer with `trial_period_days` set.
3. *(If either call fails: show an error, let the user retry — nothing local exists yet, fully safe.)*
4. Begin one local database transaction:
   - Insert `congregations` (`owner_user_id` temporarily unset)
   - Insert `people` for the owner (`congregation_id` now valid)
   - Insert `users` (`congregation_id` and `person_id` now valid)
   - `UPDATE congregations SET owner_user_id = <new user>`
   - Copy the 5 system default roles and their `role_permissions` into this congregation
   - Insert `user_roles`: assign the new user the **Owner** role (its permission set already covers everything Admin would — no separate Admin role assignment needed)
   - Insert `congregation_modules` for every module in the system registry — `is_enabled = true` only for whatever was selected in Step 4
   - Insert `subscriptions`, using the real Stripe IDs from steps 1–2, `status = 'trialing'`
   - Insert `subscription_events` (`event_type = 'trial_started'`, `source = 'admin_action'`)
   - Insert `congregation_module_history` for each enabled module
   - Commit
5. **If the local transaction fails after step 2 already succeeded:** compensate by canceling the just-created Stripe subscription, logging the action — retried via a backstop cleanup job if the cancellation itself fails. Same defense-in-depth pattern used elsewhere in this system: an application-level compensating action backed by a periodic reconciliation job that catches anything the immediate compensation missed.
6. On success: log the user in, redirect to the welcome dashboard.
