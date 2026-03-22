"""TransitionManager — assembled from per-domain modules.

Each sub-module defines module-level functions whose first parameter is
``self: TransitionManager``.  This file imports them and binds them as
methods on the class so that the rest of the codebase can keep using
``TransitionManager`` exactly as before.
"""

from backend.database.database import DatabaseWriter
from backend.orchestrator.state import StateManager

# -- domain modules ----------------------------------------------------------
from backend.orchestrator.transitions import (
    _admin,
    _base,
    _leaderboard,
    _match,
    _mmr,
    _notifications,
    _party,
    _player,
    _queue,
    _replay,
)


class TransitionManager:
    def __init__(self, state_manager: StateManager, db_writer: DatabaseWriter) -> None:
        self._state_manager = state_manager
        self._db_writer = db_writer
        # Track match confirmations: match_id → set of discord_uids
        self._confirmations: dict[int, set[int]] = {}
        # Whether the leaderboard was rebuilt since the last read.
        self._leaderboard_dirty: bool = False

    # -- base helpers (_base.py) ---------------------------------------------
    _handle_missing_player = _base._handle_missing_player
    _set_player_status = _base._set_player_status
    _get_match_row = _base._get_match_row
    _update_match_cache = _base._update_match_cache
    _get_player_location = _base._get_player_location
    _get_player_nationality = _base._get_player_nationality
    _get_player_letter_rank = _base._get_player_letter_rank

    # -- player transitions (_player.py) -------------------------------------
    set_country_for_player = _player.set_country_for_player
    setup_player = _player.setup_player
    set_tos_for_player = _player.set_tos_for_player
    reset_all_player_statuses = _player.reset_all_player_statuses
    upsert_preferences_1v1 = _player.upsert_preferences_1v1

    # -- queue transitions (_queue.py) ---------------------------------------
    join_queue_1v1 = _queue.join_queue_1v1
    leave_queue_1v1 = _queue.leave_queue_1v1

    # -- notifications (_notifications.py) -----------------------------------
    ensure_notification_row = _notifications.ensure_notification_row
    upsert_notifications_preferences = _notifications.upsert_notifications_preferences

    # -- MMR helpers (_mmr.py) -----------------------------------------------
    _handle_missing_mmr_1v1 = _mmr._handle_missing_mmr_1v1
    _compute_mmr_update = _mmr._compute_mmr_update
    _apply_mmr_cache_update = _mmr._apply_mmr_cache_update
    _set_mmr_cache_value = _mmr._set_mmr_cache_value
    _recalculate_game_stats = _mmr._recalculate_game_stats

    # -- match lifecycle (_match.py) -----------------------------------------
    # Note: the module function is named run_matchmaking_wave_method to avoid
    # shadowing the algorithm import; we bind it as run_matchmaking_wave here.
    run_matchmaking_wave = _match.run_matchmaking_wave_method
    confirm_match = _match.confirm_match
    is_match_confirmed = _match.is_match_confirmed
    abort_match = _match.abort_match
    handle_confirmation_timeout = _match.handle_confirmation_timeout
    report_match_result = _match.report_match_result
    _calculate_mmr_changes = _match._calculate_mmr_changes
    _apply_match_resolution = _match._apply_match_resolution

    # -- replay transitions (_replay.py) -------------------------------------
    insert_replay_1v1_pending = _replay.insert_replay_1v1_pending
    update_replay_status = _replay.update_replay_status
    update_match_replay_refs = _replay.update_match_replay_refs
    replay_auto_resolve_match = _replay.replay_auto_resolve_match

    # -- leaderboard (_leaderboard.py) ---------------------------------------
    rebuild_leaderboard = _leaderboard.rebuild_leaderboard
    consume_leaderboard_dirty = _leaderboard.consume_leaderboard_dirty

    # -- party transitions (_party.py) ----------------------------------------
    create_party_invite = _party.create_party_invite
    respond_to_party_invite = _party.respond_to_party_invite
    leave_party = _party.leave_party
    get_party = _party.get_party
    _purge_party_membership = _party.purge_party_membership

    # -- admin / owner (_admin.py) -------------------------------------------
    reset_player_status = _admin.reset_player_status
    toggle_ban = _admin.toggle_ban
    admin_resolve_match = _admin.admin_resolve_match
    admin_set_mmr = _admin.admin_set_mmr
    toggle_admin_role = _admin.toggle_admin_role
    get_queue_snapshot_1v1 = _admin.get_queue_snapshot_1v1
    get_active_matches_1v1 = _admin.get_active_matches_1v1
