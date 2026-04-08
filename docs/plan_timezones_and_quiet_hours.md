# Plan: Timezones + Quiet Hours

## Goal

Let players configure a personal timezone and a set of "quiet hours" during which the bot will suppress queue-activity DM notifications. The configuration UI lives entirely inside the standalone `/notifications` command — no changes to `/setup`.

## Scope

- New timezone column on `players`.
- New quiet-hours bitmask column on `notifications`.
- `/notifications` command grows to four dropdowns (timezone, quiet hours, 1v1 timer, 2v2 timer) plus the existing confirm/cancel row.
- DST is handled automatically via IANA tz names (`zoneinfo`).
- Existing players who haven't picked a timezone are silently exempt — they continue to receive notifications at all hours, just like today.

`/setup` and `/setcountry` are explicitly **not** touched.

## Design decisions (locked)

| Decision | Choice |
|---|---|
| Where the UI lives | `/notifications` only |
| Quiet-hours semantics | Blacklist (selected hours = silenced) |
| Quiet-hours storage | Single `INTEGER` bitmask, 24 bits, shared across modes |
| Timezone storage | IANA tz **name** (`TEXT`) on `players`, e.g. `"America/New_York"` |
| DST handling | Automatic via Python's `zoneinfo` |
| Auto-fill for single-tz regions | Render the dropdown as `disabled=True` with the value preselected |
| Legacy players (no tz) | Silently skipped — full notification cadence preserved |
| `/setcountry` | Out of scope; remains nationality-only |

## Why IANA names instead of fixed minute offsets

The user explicitly wants DST to "just work." A fixed `timezone_offset_minutes` cannot do this — `America/New_York` is UTC−05:00 in winter and UTC−04:00 in summer, and the player's "9 PM local" shifts in absolute terms. Storing the IANA name and resolving the offset *at notification time* via `ZoneInfo` is the only correct approach.

### Library choice

- **`zoneinfo`** — stdlib since Python 3.9. The project is on Python 3.14 (per `CLAUDE.md`), so it's available with no new dependency. It reads the system tzdata.
- **`tzdata`** (PyPI) — pure-Python tzdata payload. Should be added to `pyproject.toml` as a defensive dependency so the bot doesn't depend on whatever tzdata version Railway's base image happens to ship. Tiny (~500 KB), pure-Python, no compiled extensions, used by `zoneinfo` automatically when present.

No third-party tz library (`pytz`, `pendulum`, `arrow`) is needed.

## Schema changes

### `players`

```sql
ALTER TABLE players ADD COLUMN timezone TEXT;
-- IANA tz name, e.g. "America/New_York". NULL means "not configured yet".
-- No CHECK constraint — validation happens in the API layer against the
-- canonical list in data/core/timezones.json.
```

### `notifications`

```sql
ALTER TABLE notifications ADD COLUMN notify_quiet_hours_local_mask INTEGER NOT NULL DEFAULT 0
    CHECK (notify_quiet_hours_local_mask BETWEEN 0 AND 16777215);
-- 24-bit mask interpreted in the player's local timezone.
-- Bit i set ⇒ hour i (00:00-00:59 local) is silenced.
-- Default 0 ⇒ no quiet hours, current behavior preserved.
```

Both columns are nullable / default-zero so the migration is non-breaking and no backfill is required. Polars schemas in `backend/domain_types/dataframes.py` get matching `Utf8` / `Int32` entries.

## Static data: `data/core/timezones.json`

A new JSON file mapping geographic region codes (from `regions.json`) to a sorted list of IANA tz names supported within that region. Schema:

```json
{
  "NAW": ["America/Los_Angeles", "America/Phoenix"],
  "NAC": ["America/Denver", "America/Chicago"],
  "NAE": ["America/New_York", "America/Halifax"],
  "KRJ": ["Asia/Seoul"],
  "CHN": ["Asia/Shanghai"],
  "USB": ["Asia/Yekaterinburg", "Asia/Omsk", "Asia/Krasnoyarsk", "Asia/Irkutsk"],
  ...
}
```

- Order within each list is **west-to-east** (matching how the UI presents options).
- Single-element lists trigger the auto-fill / locked-dropdown UX.
- The display label for each option in the dropdown is computed at render time as `<short city name> (UTC±HH:MM)`, where the offset is the *current* offset (so it reflects DST automatically). The stored value is the IANA name.

**The explicit list of supported tz names per region is TBD and will be provided by the project owner.** Once decided it lives in this file and is loaded by `JSONLoader` alongside the other core JSON.

Loaded by `common/loader.py:JSONLoader`, exposed on both `StateManager` and `Cache` via the `StaticDataSource` protocol (`common/protocols.py`).

## Helper module: `common/timezone_helpers.py` (new)

Single source of truth, importable by both backend and bot:

```python
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

def get_zoneinfo(tz_name: str) -> ZoneInfo: ...           # cached lookup
def format_current_offset(tz_name: str, now_utc: datetime) -> str:
    """e.g. 'UTC-04:00' (uses ZoneInfo at the given instant — DST-aware)."""
def local_hour(tz_name: str, now_utc: datetime) -> int:
    """Return the player's local hour (0-23) at the given instant."""
def is_quiet_hour(mask: int, tz_name: str, now_utc: datetime) -> bool:
    return bool((mask >> local_hour(tz_name, now_utc)) & 1)
def is_valid_tz(tz_name: str) -> bool:
    """Validate against zoneinfo + the timezones.json allowlist."""
```

All timestamps stay UTC-aware everywhere except inside these helpers — consistent with the existing rule in `common/datetime_helpers.py`.

## UI: `/notifications` command

Five rows total (Discord's hard limit):

| Row | Component | Behavior |
|---|---|---|
| 0 | **Timezone** select | Always enabled. Options are **scoped to the player's geographic region** — looked up from `players.location` (via `cache.player_presets[uid]["location"]`) and used to index into `timezones.json`. Default selection = the player's stored `timezone` if it's still valid for their current region. If the region has exactly one tz, the dropdown is rendered `disabled=True` with that tz preselected (auto-fill UX). If the player has no `location` on file (shouldn't happen post-`/setup` but defensively), the timezone select is disabled and the rest of the view falls into legacy mode. |
| 1 | **Quiet hours** select | 24 options, `00:00 – 01:00` … `23:00 – 24:00`, `min_values=0`, `max_values=24`. Default = bits set in the player's current mask. Disabled if no timezone is set. |
| 2 | **1v1 frequency** select | Existing dropdown from `SetupNotificationView`. |
| 3 | **2v2 frequency** select | Existing dropdown from `SetupNotificationView`. |
| 4 | Confirm + Cancel buttons | Confirm is enabled when both frequency dropdowns have a value, regardless of timezone/quiet-hours state. |

### Interaction flow

- The view is constructed with whatever the player already has on file (`cache.player_presets[uid].get("timezone")` for the timezone, `cache.player_presets[uid].get("location")` for the region scoping the timezone dropdown, `cache.notification_presets` for the rest). `check_player(...)` in `notifications_command.py` already populates `player_presets` with the full row from `GET /players/{uid}`, so no extra round-trip is needed. The setup-flow path threads the region in directly via `SetupSelectionView.selected_region` (already passed to `SetupNotificationView` as `region=`).
- Changing the timezone dropdown rebuilds the quiet-hours dropdown so the labels reflect the new offset (the labels themselves are tz-independent — `00:00 – 01:00` is always literal local time — but enabling/disabling depends on whether a tz is now present).
- Confirm performs a single PUT to `/notifications` (existing endpoint) with the new payload fields, plus a separate PUT to `/players` to persist the timezone. Both writethroughs go through `TransitionManager` (Supabase first, then DataFrame).
- Standalone success embed (`NotificationsUpdatedEmbed`) gains a "Timezone" line and a "Quiet hours" line, formatted using the helpers above.

### Discord row-budget sanity check

5 rows max:
- 4 selects + 1 button row = 5. ✅ Exactly fits, no headroom for additional widgets later. If we ever need a fifth control, we'll have to fold the buttons into a pagination view or split the command into a wizard.

## Backend filtering logic

`backend/orchestrator/queue_notify.py:compute_queue_activity_targets` already filters by per-mode cooldown. Extend it with a quiet-hours check:

```python
tz_name = row.get("timezone")
mask = int(row.get("notify_quiet_hours_local_mask") or 0)
if tz_name and mask and is_quiet_hour(mask, tz_name, now):
    continue  # silenced
# legacy: tz_name is None ⇒ feature disabled, fall through
```

`backend/lookups/notification_lookups.get_queue_activity_subscribers` must additionally select `timezone` from `players_df` and `notify_quiet_hours_local_mask` from `notifications_df` so those columns are present in the joined DataFrame.

## Files touched (high level)

**Schema / DB / DTOs**
- `backend/database/schema.sql`
- `backend/domain_types/dataframes.py` (`PlayersRow`, `NotificationsRow`, `TABLE_SCHEMAS`)
- `backend/api/models.py` (player upsert + notifications upsert payloads)
- `backend/api/endpoints.py`
- `backend/orchestrator/transitions/_player.py`
- `backend/orchestrator/transitions/_notifications.py`

**Backend logic**
- `backend/orchestrator/queue_notify.py`
- `backend/lookups/notification_lookups.py`
- `backend/core/bootstrap.py` / `common/loader.py` (register `timezones.json`)

**Static data**
- `data/core/timezones.json` *(new)*

**Shared helpers**
- `common/timezone_helpers.py` *(new)*
- `common/protocols.py` (extend `StaticDataSource`)
- `pyproject.toml` (add `tzdata` dependency)

**Bot**
- `bot/commands/user/notifications_command.py` (fetch player presets including timezone, build expanded view)
- `bot/components/views.py` — extend `SetupNotificationView` (or split a new `NotificationsView` if it becomes too tangled — TBD during implementation) with:
  - timezone select
  - quiet-hours select
  - thread mask + tz through to the standalone save helper
- `bot/components/embeds.py` — `NotificationsUpdatedEmbed` adds Timezone and Quiet Hours fields
- `bot/core/dependencies.py` / `bot/core/bootstrap.py` — `Cache` exposes the timezones static data

**Locales (all 6 files, lex order)**
- `notifications_view.placeholder.timezone`
- `notifications_view.placeholder.quiet_hours`
- `notifications_view.quiet_hours.locked.1`
- `notifications_view.quiet_hours.option.{00..23}`
- `notifications_updated_embed.field_name.timezone`
- `notifications_updated_embed.field_name.quiet_hours`
- `notifications_updated_embed.quiet_hours.none.1`

## Implementation phases

1. **Schema + helpers + static data scaffolding.** Add columns, write `common/timezone_helpers.py`, add `tzdata` dep, create empty/placeholder `timezones.json`. Unit-test the helpers (DST transitions, day-wrap at UTC midnight, half-hour zones like `Asia/Kolkata`, `Asia/Kathmandu`, `Australia/Adelaide`, southern-hemisphere DST flip in `Pacific/Auckland`).
2. **Backend filter wiring.** Extend the lookup join, plug `is_quiet_hour` into `queue_notify.py`, write an invariant test confirming a subscriber whose mask bit covers "now" in their tz is excluded.
3. **API surface.** Player and notifications upserts accept the new fields. Round-trip test via the existing endpoint tests (if any) or a new one.
4. **`/notifications` UI.** Add the two new dropdowns, the locked-dropdown UX for legacy users, and the success-embed updates.
5. **Locale fan-out** + `make quality` + commit.

## Open work (not yet decided)

1. **The explicit timezone list per region.** The project owner will provide the canonical mapping. The exact set determines the dropdown contents and the helper validation allowlist.
2. **Display label format.** `"New York (UTC-04:00)"` vs `"America/New_York"` vs `"🇺🇸 New York"`. Probably the first; finalize when locale strings are written.
3. **Legacy nudge.** When/where to prompt existing players to configure their timezone (e.g. a one-time DM, a banner inside `/notifications` itself, a reminder in `/profile`). Out of scope for this plan but worth tracking.
