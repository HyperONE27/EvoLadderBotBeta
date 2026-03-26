# SC: Evo Complete Ladder Bot • Command Reference

All commands must be used in **DMs with the bot.**

---

## Getting Started

**`/setup`**
First-time registration. You must complete this to use the rest of the bot.

Walks you through:
- Language selection
- Terms of Service
- User ID selection
- BattleTag
- Nationality
- Location
- Notification preferences.

You can return to this command at any time to change your settings.

---

## Playing

**`/queue`**
Join the ranked matchmaking queue. Select your game mode (1v1 or 2v2), races, and map vetoes. The matchmaker runs every 60 seconds. 2v2 requires an active party.

**`/party invite <player>`**
Invite another registered player to form a 2v2 party. Find them by User ID, Discord username, or Discord snowflake (UID).

**`/party leave`**
Leave your current 2v2 party.

**`/party status`**
Check who is in your current 2v2 party.

---

## Stats & Leaderboard

**`/profile`**
View your player profile: MMR by race, win/loss record, rank, and match history summary.

**`/leaderboard`**
View the ranked MMR leaderboard. Accepts an optional `game_mode` argument (1v1 or 2v2).

**`/activity`**
View a chart of queue join attempts over the past 24 hours, 7 days, or 30 days.

===

ℹ️ SC: Evo Complete Ladder Bot • Command Reference

All commands must be used in **DMs with the bot.**

**Getting Started**
- `/setup` — First-time registration: language, Terms of Service, player name, BattleTag, nationality, location, and notification preferences.
  - You must complete this to access the rest of the bot.
  - You can return to this command at any time to revoke consent to the Terms of Service, or to change your settings.
- `/setcountry {country}` — Select your country here if it is not listed in `/setup`.

**Playing**
- `/queue {game_mode}` — Join the matchmaking queue. Configure race selections and map vetoes. 2v2 requires an active party.
- `/party invite {player}` — Invite a registered player to your 2v2 party. Find them by player name, Discord username, or Discord ID.
- `/party leave` — Leave your current 2v2 party.
- `/party status` — Check your current 2v2 party and whether your partner has accepted.

**Stats & Leaderboard**
- `/profile` — View your MMR by gamemode, rank, and match history statistics.
- `/leaderboard {game_mode}` — View the ranked MMR leaderboard.
- `/activity {game_mode}` — View a chart of recent queue join attempts.