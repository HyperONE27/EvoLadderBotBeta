from backend.config import MMR

_DEFAULT_MMR: int = MMR["default"]
_DIVISOR: int = MMR["divisor"]
_K_FACTOR: int = MMR["k_factor"]

# ----------------
# Internal helpers
# ----------------


def _calculate_actual_score(result: int) -> tuple[float, float]:
    if result == 1:
        return 1.0, 0.0
    elif result == 2:
        return 0.0, 1.0
    else:  # result == 0
        return 0.5, 0.5


def _calculate_expected_score(player_1_mmr: int, player_2_mmr: int) -> float:
    differential = player_2_mmr - player_1_mmr
    return 1 / (1 + 10 ** (differential / _DIVISOR))


def _calculate_rating_changes(
    player_1_mmr: int, player_2_mmr: int, result: int
) -> tuple[int, int]:
    actual_score_1, actual_score_2 = _calculate_actual_score(result)
    expected_score_1 = _calculate_expected_score(player_1_mmr, player_2_mmr)
    expected_score_2 = _calculate_expected_score(player_2_mmr, player_1_mmr)
    rating_change_1 = _K_FACTOR * (actual_score_1 - expected_score_1)
    rating_change_2 = _K_FACTOR * (actual_score_2 - expected_score_2)
    return round(rating_change_1), round(rating_change_2)


def _validate_match_result(match_result: int) -> None:
    if match_result not in [0, 1, 2]:
        raise ValueError(
            f"Invalid match result code: {match_result}\n"
            "Must be 0 for draw, 1 for win, or 2 for loss."
        )


def _validate_mmr(mmr: int) -> None:
    if not isinstance(mmr, int):
        raise ValueError(f"Invalid MMR: {mmr}\nMust be an integer.")


# ----------------
# Public API
# ----------------


def get_default_mmr() -> int:
    return _DEFAULT_MMR


def get_potential_rating_changes(
    player_1_mmr: int, player_2_mmr: int
) -> tuple[int, int, int]:
    """
    Get the potential rating changes for a 1v1 match.
    Rating changes are calculated from the perspective of player 1.
    Returns the rating changes for a win, loss, and draw, in that order.
    """
    _validate_mmr(player_1_mmr)
    _validate_mmr(player_2_mmr)
    rating_change_win = _calculate_rating_changes(player_1_mmr, player_2_mmr, 1)[0]
    rating_change_loss = _calculate_rating_changes(player_1_mmr, player_2_mmr, 2)[0]
    rating_change_draw = _calculate_rating_changes(player_1_mmr, player_2_mmr, 0)[0]
    return rating_change_win, rating_change_loss, rating_change_draw


def get_new_ratings(
    player_1_mmr: int, player_2_mmr: int, match_result: int
) -> tuple[int, int]:
    _validate_mmr(player_1_mmr)
    _validate_mmr(player_2_mmr)
    _validate_match_result(match_result)
    player_1_mmr_change, player_2_mmr_change = _calculate_rating_changes(
        player_1_mmr, player_2_mmr, match_result
    )
    new_player_1_mmr = player_1_mmr + player_1_mmr_change
    new_player_2_mmr = player_2_mmr + player_2_mmr_change
    return new_player_1_mmr, new_player_2_mmr
