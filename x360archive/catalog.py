from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import re
import unicodedata


HEADER_MAP = {
    "No": "number",
    "Official Game Name": "title",
    "Game Folder": "folder_name",
    "Subtitles (CZ)": "subtitles_cs",
    "Audio (CZ)": "audio_cs",
    "Official": "official_translation",
    "Title Update": "title_update",
    "DLC": "dlc",
    "Format": "format",
    "Status": "catalog_status",
    "Note": "note",
    "Popis (CZ)": "description_cs",
    "Kategorie": "categories",
    "PEGI": "pegi",
    "Hodnocení (0–100)": "rating",
    "Zdroj hodnocení": "rating_source",
    "Max. hráčů": "max_players",
    "Lokální multiplayer": "local_multiplayer",
    "Lokální hráči max.": "local_players_max",
    "Rok vydání": "release_year",
    "Datum vydání": "release_date",
    "Vývojář": "developer",
    "Vydavatel": "publisher",
    "Podpora Kinectu": "kinect_support",
    "Kinect povinný": "kinect_required",
    "Title ID": "title_id",
}


def slug(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def yes(value) -> bool:
    return str(value or "").strip().casefold() in {"yes", "ano", "true", "1"}


def json_value(value):
    if isinstance(value, (datetime, date)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    return value


def import_xlsx(source: Path, output: Path) -> dict:
    try:
        import openpyxl
    except ImportError as exc:
        raise RuntimeError("Chybí openpyxl. Spusťte: pip install -r requirements.txt") from exc
    workbook = openpyxl.load_workbook(source, data_only=True, read_only=False)
    if "Games List" not in workbook.sheetnames:
        raise ValueError("Sešit neobsahuje list 'Games List'.")
    sheet = workbook["Games List"]
    header_row = 2
    headers = {sheet.cell(header_row, column).value: column for column in range(1, sheet.max_column + 1)}
    missing = sorted(set(HEADER_MAP) - set(headers))
    if missing:
        raise ValueError("V Games List chybí sloupce: " + ", ".join(missing))
    games = []
    seen_assets = set()
    for row in range(header_row + 1, sheet.max_row + 1):
        raw = {target: json_value(sheet.cell(row, headers[source_name]).value)
               for source_name, target in HEADER_MAP.items()}
        if not raw["title"]:
            continue
        title_id = str(raw["title_id"] or "").strip().upper()
        if not re.fullmatch(r"[0-9A-F]{8}", title_id):
            raise ValueError(f"Řádek {row}: neplatné Title ID {title_id!r}.")
        raw["title_id"] = title_id
        raw["slug"] = slug(str(raw["title"]))
        raw["asset_id"] = f"{title_id.lower()}-{slug(str(raw['folder_name']))}"
        if raw["asset_id"] in seen_assets:
            raise ValueError(f"Řádek {row}: duplicitní asset ID {raw['asset_id']}.")
        seen_assets.add(raw["asset_id"])
        raw["expected_filename"] = str(raw["folder_name"]) + ".7z"
        raw["subtitles_cs"] = yes(raw["subtitles_cs"])
        raw["audio_cs"] = yes(raw["audio_cs"])
        raw["official_translation"] = yes(raw["official_translation"])
        raw["local_multiplayer"] = yes(raw["local_multiplayer"])
        raw["kinect_support"] = yes(raw["kinect_support"])
        raw["kinect_required"] = yes(raw["kinect_required"])
        raw["categories"] = [part.strip() for part in str(raw["categories"] or "").split(",") if part.strip()]
        games.append(raw)
    payload = {
        "schema_version": 1,
        "source": source.name,
        "game_count": len(games),
        "games": games,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def load_catalog(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("games"), list):
        raise ValueError("Nepodporovaný formát katalogu.")
    return data


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def remote_name(asset_id: str, sha256: str) -> str:
    return f"x360-{asset_id}-{sha256[:12]}.7z"
