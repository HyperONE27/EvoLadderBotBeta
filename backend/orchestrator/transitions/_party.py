"""Party system transitions for 2v2: invite, accept/decline, leave."""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl
import structlog

from backend.domain_types.ephemeral import PartyEntry2v2, PendingPartyInvite2v2
from common.datetime_helpers import utc_now

if TYPE_CHECKING:
    from backend.orchestrator.transitions import TransitionManager

logger = structlog.get_logger(__name__)


# ==================================================================
# Invite
# ==================================================================


def create_party_invite(
    self: TransitionManager,
    inviter_discord_uid: int,
    inviter_player_name: str,
    invitee_discord_uid: int,
    invitee_player_name: str,
) -> tuple[bool, str | None]:
    """Validate and store a pending party invite.

    Returns ``(success, error_message)``.
    """
    # --- Guard: can't invite yourself ---
    if inviter_discord_uid == invitee_discord_uid:
        return False, "You cannot invite yourself to a party."

    # --- Guard: inviter status ---
    inviter_row = self._state_manager.players_df.filter(
        pl.col("discord_uid") == inviter_discord_uid
    )
    if inviter_row.is_empty():
        return False, "Inviter player not found."
    inviter_status: str = inviter_row.row(0, named=True).get("player_status", "")

    if inviter_status == "in_party":
        # Already in a party — only allow if they are the leader with no member
        # (re-inviting after previous member left).
        party = self._state_manager.parties_2v2.get(inviter_discord_uid)
        if party is not None:
            return False, "You cannot invite other users while in a party."
        # inviter has in_party status but no party entry — stale status, reset
        self._set_player_status(
            inviter_discord_uid, "idle", match_mode=None, match_id=None
        )
    elif inviter_status not in ("idle",):
        return (
            False,
            f"You cannot send a party invite while your status is '{inviter_status}'.",
        )

    # --- Guard: invitee status ---
    invitee_row = self._state_manager.players_df.filter(
        pl.col("discord_uid") == invitee_discord_uid
    )
    if invitee_row.is_empty():
        return False, "Invited player not found."
    invitee_status: str = invitee_row.row(0, named=True).get("player_status", "")

    if invitee_status != "idle":
        return (
            False,
            f"That player cannot be invited right now (status: '{invitee_status}').",
        )

    # --- Store invite (overwrites any existing invite for this invitee) ---
    invite: PendingPartyInvite2v2 = {
        "inviter_discord_uid": inviter_discord_uid,
        "inviter_player_name": inviter_player_name,
        "invitee_discord_uid": invitee_discord_uid,
        "invitee_player_name": invitee_player_name,
        "invited_at": utc_now(),
    }
    self._state_manager.pending_party_invites_2v2[invitee_discord_uid] = invite

    logger.info(
        f"Party invite created: {inviter_player_name} ({inviter_discord_uid}) "
        f"→ {invitee_player_name} ({invitee_discord_uid})"
    )
    return True, None


# ==================================================================
# Respond (accept / decline)
# ==================================================================


def respond_to_party_invite(
    self: TransitionManager,
    invitee_discord_uid: int,
    accepted: bool,
) -> tuple[bool, str | None, PendingPartyInvite2v2 | None]:
    """Accept or decline a pending party invite.

    Returns ``(success, error_message, invite)``.  On success the invite
    dict is returned so the caller knows who the inviter was.
    """
    invite = self._state_manager.pending_party_invites_2v2.pop(
        invitee_discord_uid, None
    )
    if invite is None:
        return False, "No pending party invite found.", None

    if not accepted:
        logger.info(
            f"Party invite declined by {invitee_discord_uid} "
            f"(from {invite['inviter_discord_uid']})"
        )
        return True, None, invite

    # --- Accept path: validate both players are still idle ---
    inviter_uid = invite["inviter_discord_uid"]

    inviter_row = self._state_manager.players_df.filter(
        pl.col("discord_uid") == inviter_uid
    )
    invitee_row = self._state_manager.players_df.filter(
        pl.col("discord_uid") == invitee_discord_uid
    )

    if inviter_row.is_empty():
        return False, "Inviter no longer exists.", invite
    if invitee_row.is_empty():
        return False, "Your player profile was not found.", invite

    inviter_status: str = inviter_row.row(0, named=True).get("player_status", "")
    invitee_status: str = invitee_row.row(0, named=True).get("player_status", "")

    if inviter_status != "idle":
        return (
            False,
            f"The inviter is no longer available (status: '{inviter_status}').",
            invite,
        )
    if invitee_status != "idle":
        return (
            False,
            f"You are no longer available to join a party (status: '{invitee_status}').",
            invite,
        )

    # --- Form the party ---
    now = utc_now()
    party: PartyEntry2v2 = {
        "leader_discord_uid": inviter_uid,
        "leader_player_name": invite["inviter_player_name"],
        "member_discord_uid": invitee_discord_uid,
        "member_player_name": invite["invitee_player_name"],
        "created_at": now,
    }
    self._state_manager.parties_2v2[inviter_uid] = party

    # Set both players to in_party.
    self._set_player_status(inviter_uid, "in_party", match_mode="2v2", match_id=None)
    self._set_player_status(
        invitee_discord_uid, "in_party", match_mode="2v2", match_id=None
    )

    logger.info(f"Party formed: leader={inviter_uid} member={invitee_discord_uid}")
    return True, None, invite


# ==================================================================
# Leave
# ==================================================================


def leave_party(
    self: TransitionManager,
    discord_uid: int,
) -> tuple[bool, str | None, int | None]:
    """Remove a player from their party.

    Handles both leader and member leaving.  If either player is currently
    queueing, they are removed from the queue first.

    Returns ``(success, error_message, partner_discord_uid)``.
    """
    # Find the party this player belongs to (as leader or member).
    party: PartyEntry2v2 | None = None
    leader_uid: int | None = None

    # Check if player is a leader.
    if discord_uid in self._state_manager.parties_2v2:
        party = self._state_manager.parties_2v2[discord_uid]
        leader_uid = discord_uid
    else:
        # Check if player is a member in any party.
        for l_uid, p in self._state_manager.parties_2v2.items():
            if p["member_discord_uid"] == discord_uid:
                party = p
                leader_uid = l_uid
                break

    if party is None or leader_uid is None:
        return False, "You are not in a party.", None

    partner_uid = (
        party["member_discord_uid"]
        if discord_uid == leader_uid
        else party["leader_discord_uid"]
    )

    # Remove both players from the 2v2 queue if they are in it.
    _remove_from_queue_2v2(self, discord_uid)
    _remove_from_queue_2v2(self, partner_uid)

    # Remove the party.
    del self._state_manager.parties_2v2[leader_uid]

    # Reset both players to idle.
    self._set_player_status(discord_uid, "idle", match_mode=None, match_id=None)
    self._set_player_status(partner_uid, "idle", match_mode=None, match_id=None)

    logger.info(f"Party disbanded: {discord_uid} left (partner: {partner_uid})")
    return True, None, partner_uid


# ==================================================================
# Get party info
# ==================================================================


def get_party(
    self: TransitionManager,
    discord_uid: int,
) -> PartyEntry2v2 | None:
    """Return the party this player belongs to, or None."""
    # Check as leader.
    if discord_uid in self._state_manager.parties_2v2:
        return self._state_manager.parties_2v2[discord_uid]
    # Check as member.
    for party in self._state_manager.parties_2v2.values():
        if party["member_discord_uid"] == discord_uid:
            return party
    return None


# ==================================================================
# Admin helper: purge party membership
# ==================================================================


def purge_party_membership(
    self: TransitionManager,
    discord_uid: int,
) -> int | None:
    """Remove a player from any party without the full leave flow.

    Used by ``/admin statusreset``.  Resets the partner to idle if they
    were in the party.

    Returns the partner's discord_uid if a party was found, else None.
    """
    party: PartyEntry2v2 | None = None
    leader_uid: int | None = None

    if discord_uid in self._state_manager.parties_2v2:
        party = self._state_manager.parties_2v2[discord_uid]
        leader_uid = discord_uid
    else:
        for l_uid, p in self._state_manager.parties_2v2.items():
            if p["member_discord_uid"] == discord_uid:
                party = p
                leader_uid = l_uid
                break

    if party is None or leader_uid is None:
        return None

    partner_uid = (
        party["member_discord_uid"]
        if discord_uid == leader_uid
        else party["leader_discord_uid"]
    )

    # Remove from queue if applicable.
    _remove_from_queue_2v2(self, discord_uid)
    _remove_from_queue_2v2(self, partner_uid)

    del self._state_manager.parties_2v2[leader_uid]

    # Reset partner to idle (the target player is already being reset by the admin).
    self._set_player_status(partner_uid, "idle", match_mode=None, match_id=None)

    # Also clear any pending invites involving this player.
    _purge_pending_invites(self, discord_uid)

    logger.info(
        f"Admin purge: removed {discord_uid} from party (partner {partner_uid} reset to idle)"
    )
    return partner_uid


# ==================================================================
# Internal helpers
# ==================================================================


def _remove_from_queue_2v2(self: TransitionManager, discord_uid: int) -> None:
    """Remove the 2v2 queue entry for the party containing this player.

    Under the leader-picks-all model each entry is keyed by the leader's
    discord_uid.  This helper removes any entry where the player appears as
    either the leader or the member, so admin resets work correctly regardless
    of which role the target player holds.
    """
    self._state_manager.queue_2v2 = [
        e
        for e in self._state_manager.queue_2v2
        if e["discord_uid"] != discord_uid
        and e["party_member_discord_uid"] != discord_uid
    ]


def _purge_pending_invites(self: TransitionManager, discord_uid: int) -> None:
    """Remove any pending invites where this player is inviter or invitee."""
    invites = self._state_manager.pending_party_invites_2v2

    # Remove if they are the invitee.
    invites.pop(discord_uid, None)

    # Remove any invites they sent (keyed by invitee uid).
    to_remove = [
        invitee_uid
        for invitee_uid, inv in invites.items()
        if inv["inviter_discord_uid"] == discord_uid
    ]
    for uid in to_remove:
        del invites[uid]
