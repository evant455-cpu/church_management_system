## Announcements

### Overview

Broadcast-only for v1 — every announcement is visible to the whole congregation, with no audience/role targeting.

---

### `announcements`

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | PK | — | |
| `congregation_id` | FK → congregations | not null | |
| `title` | varchar(200) | not null | |
| `body` | text | not null | |
| `image_url` | varchar(500) | nullable | |
| `status` | varchar(20) | not null, default `draft` | `draft` / `published` / `archived` |
| `publish_at` | timestamp | nullable | Supports scheduling ahead of time |
| `expires_at` | timestamp | nullable | Auto-hide after an event/date passes |
| `created_by_id` | FK → users | not null | |
| `created_at` / `updated_at` | timestamp | not null | |
