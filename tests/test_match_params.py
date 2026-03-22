"""Invariant tests for match parameter resolution (1v1 and 2v2).

Covers _available_maps, _resolve_server, and _resolve_server_for_group.
"""

import pytest

from backend.algorithms.match_params import _available_maps, _resolve_server
from backend.algorithms.match_params_2v2 import _resolve_server_for_group
from common.json_types import CrossTableData, GameModeData

# ---------------------------------------------------------------------------
# Fixtures — minimal static data
# ---------------------------------------------------------------------------

MAPS: dict[str, GameModeData] = {
    "1v1": {
        "season_alpha": {
            "Map A": {
                "short_name": "a",
                "name": "Map A",
                "author": "",
                "am_link": "",
                "eu_link": "",
            },
            "Map B": {
                "short_name": "b",
                "name": "Map B",
                "author": "",
                "am_link": "",
                "eu_link": "",
            },
            "Map C": {
                "short_name": "c",
                "name": "Map C",
                "author": "",
                "am_link": "",
                "eu_link": "",
            },
            "Map D": {
                "short_name": "d",
                "name": "Map D",
                "author": "",
                "am_link": "",
                "eu_link": "",
            },
        },
    },
    "2v2": {
        "season_alpha": {
            "Map X": {
                "short_name": "x",
                "name": "Map X",
                "author": "",
                "am_link": "",
                "eu_link": "",
            },
            "Map Y": {
                "short_name": "y",
                "name": "Map Y",
                "author": "",
                "am_link": "",
                "eu_link": "",
            },
        },
    },
}

CROSS_TABLE: CrossTableData = {
    "region_order": ["NA", "EU", "KR", "CN"],
    "mappings": {
        "NA": {"NA": "US West", "EU": "US East", "KR": "US West", "CN": "US West"},
        "EU": {"EU": "Europe", "KR": "Europe", "CN": "Europe"},
        "KR": {"KR": "Korea", "CN": "Korea"},
        "CN": {"CN": "China"},
    },
    "pings": {},
}


# ---------------------------------------------------------------------------
# _available_maps
# ---------------------------------------------------------------------------


class TestAvailableMaps:
    def test_no_vetoes_returns_all(self) -> None:
        result = _available_maps(MAPS, "1v1", "season_alpha", [], [])
        assert set(result) == {"Map A", "Map B", "Map C", "Map D"}

    def test_vetoes_excluded(self) -> None:
        result = _available_maps(MAPS, "1v1", "season_alpha", ["Map A"], ["Map C"])
        assert "Map A" not in result
        assert "Map C" not in result
        assert "Map B" in result
        assert "Map D" in result

    def test_veto_union(self) -> None:
        """Both players' vetoes are combined, not intersected."""
        result = _available_maps(
            MAPS, "1v1", "season_alpha", ["Map A", "Map B"], ["Map C"]
        )
        assert set(result) == {"Map D"}

    def test_overlapping_vetoes(self) -> None:
        """Duplicate vetoes don't cause issues."""
        result = _available_maps(MAPS, "1v1", "season_alpha", ["Map A"], ["Map A"])
        assert "Map A" not in result
        assert len(result) == 3

    def test_all_vetoed_returns_empty(self) -> None:
        result = _available_maps(
            MAPS,
            "1v1",
            "season_alpha",
            ["Map A", "Map B"],
            ["Map C", "Map D"],
        )
        assert result == []

    def test_non_vetoed_preserved(self) -> None:
        """Every map not in either veto list is present in the result."""
        p1_vetoes = ["Map A"]
        p2_vetoes = ["Map B"]
        result = set(_available_maps(MAPS, "1v1", "season_alpha", p1_vetoes, p2_vetoes))
        all_maps = set(MAPS["1v1"]["season_alpha"].keys())
        expected = all_maps - set(p1_vetoes) - set(p2_vetoes)
        assert result == expected

    def test_missing_game_mode_raises(self) -> None:
        with pytest.raises(KeyError, match="3v3"):
            _available_maps(MAPS, "3v3", "season_alpha", [], [])

    def test_missing_season_raises(self) -> None:
        with pytest.raises(KeyError, match="season_beta"):
            _available_maps(MAPS, "1v1", "season_beta", [], [])

    def test_2v2_game_mode(self) -> None:
        result = _available_maps(MAPS, "2v2", "season_alpha", ["Map X"], [])
        assert result == ["Map Y"]


# ---------------------------------------------------------------------------
# _resolve_server — canonical ordering (symmetry)
# ---------------------------------------------------------------------------


class TestResolveServer:
    def test_symmetry(self) -> None:
        """_resolve_server(a, b) == _resolve_server(b, a)."""
        regions = CROSS_TABLE["region_order"]
        for r1 in regions:
            for r2 in regions:
                assert _resolve_server(CROSS_TABLE, r1, r2) == _resolve_server(
                    CROSS_TABLE, r2, r1
                )

    def test_known_pairs(self) -> None:
        assert _resolve_server(CROSS_TABLE, "NA", "NA") == "US West"
        assert _resolve_server(CROSS_TABLE, "NA", "EU") == "US East"
        assert _resolve_server(CROSS_TABLE, "EU", "EU") == "Europe"
        assert _resolve_server(CROSS_TABLE, "KR", "KR") == "Korea"

    def test_unknown_region_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown region"):
            _resolve_server(CROSS_TABLE, "NA", "MARS")


# ---------------------------------------------------------------------------
# _resolve_server_for_group (2v2)
# ---------------------------------------------------------------------------


class TestResolveServerForGroup:
    def test_single_region(self) -> None:
        """All players in same region → self-pair lookup."""
        result = _resolve_server_for_group(CROSS_TABLE, ["NA", "NA", "NA", "NA"])
        assert result == "US West"

    def test_four_identical_same_as_single(self) -> None:
        """Deduplication: 4× same region behaves like 1×."""
        single = _resolve_server_for_group(CROSS_TABLE, ["EU"])
        four = _resolve_server_for_group(CROSS_TABLE, ["EU", "EU", "EU", "EU"])
        assert single == four

    def test_none_locations_filtered(self) -> None:
        """None locations are ignored."""
        result = _resolve_server_for_group(CROSS_TABLE, [None, "KR", None, "KR"])
        assert result == "Korea"

    def test_all_none_raises(self) -> None:
        with pytest.raises(ValueError, match="No location data"):
            _resolve_server_for_group(CROSS_TABLE, [None, None, None, None])

    def test_two_regions_uses_pair_lookup(self) -> None:
        """Two distinct regions → cross-table lookup for that pair."""
        result = _resolve_server_for_group(CROSS_TABLE, ["NA", "EU", "NA", "EU"])
        assert result == _resolve_server(CROSS_TABLE, "NA", "EU")

    def test_three_regions_majority_wins(self) -> None:
        """With 3 unique regions, the server appearing in most pairs wins.

        NA-EU → US East, NA-KR → US West, EU-KR → Europe.
        All different — 3-way tie, any is valid.
        """
        result = _resolve_server_for_group(CROSS_TABLE, ["NA", "EU", "KR", None])
        assert result in {"US East", "US West", "Europe"}
