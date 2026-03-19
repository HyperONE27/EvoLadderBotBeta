import json
from pathlib import Path
from typing import Any, cast

from common.json_types import CrossTableData, LoadedData, RegionData


class JSONLoader:
    """Loads all application data from JSON files."""

    def __init__(
        self,
        data_dir: Path = Path(Path(__file__).resolve().parent.parent / "data" / "core"),
    ) -> None:
        self.data_dir: Path = data_dir

    def load_core_data(self) -> LoadedData:
        """Loads all core JSON data into typed structures."""
        return {
            "countries": self._load_json("countries.json"),
            "cross_table": cast(
                CrossTableData,
                self._load_json("cross_table.json"),
            ),
            "emotes": self._load_json("emotes.json"),
            "maps": self._load_json("maps.json"),
            "mods": self._load_json("mods.json"),
            "races": self._load_json("races.json"),
            "regions": cast(
                RegionData,
                self._load_json("regions.json"),
            ),
        }

    def load_locale_data(self) -> dict[str, dict[str, str]]:
        """Load locale files and return ``{locale_code: {key: str}}``.

        ``enUS.json`` is the canonical English fallback.  Every other locale
        file contains only the keys it overrides; the result is merged so each
        locale starts from the full English set.

        ``base.json`` is a key schema (values are blank) used as a reference
        when adding new translation keys — it is not used as a string source.
        """
        locales_dir = self.data_dir.parent / "locales"

        # Load enUS as the canonical fallback.
        en_path = locales_dir / "enUS.json"
        en_strings: dict[str, str] = {}
        if en_path.exists():
            with open(en_path, encoding="utf-8") as f:
                en_strings = json.load(f)
            en_strings = {k: v for k, v in en_strings.items() if k}

        result: dict[str, dict[str, str]] = {"enUS": en_strings}

        for locale_file in sorted(locales_dir.glob("*.json")):
            if locale_file.stem in ("base", "enUS"):
                continue
            locale_code = locale_file.stem
            with open(locale_file, encoding="utf-8") as f:
                overrides: dict[str, str] = json.load(f)
            # Strip the ``{"": ""}`` sentinel used in empty locale stubs.
            overrides = {k: v for k, v in overrides.items() if k}
            result[locale_code] = {**en_strings, **overrides}

        return result

    def _load_json(self, file_name: str) -> dict[str, Any]:
        file_path = self.data_dir / file_name
        if not file_path.exists():
            raise FileNotFoundError(f"Required JSON file not found: {file_path}")

        with open(file_path, "r", encoding="utf-8") as f:
            return cast(dict[str, Any], json.load(f))
