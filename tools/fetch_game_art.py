#!/usr/bin/env python3
"""Synchronize XboxUnity cover variants and create optimized local WebP assets."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
from pathlib import Path
import sys

from PIL import Image, ImageOps
import requests


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "catalog/games.json"
OUTPUT = ROOT / "docs/assets/covers"
MANIFEST = ROOT / "catalog/cover-sources.json"
BASE = "https://raw.githubusercontent.com/UncreativeXenon/XboxUnity-Scraper/master"


def get_json(url: str) -> dict:
    response = requests.get(url, timeout=45, headers={"User-Agent": "X360CZCatalog/1.0"})
    if response.status_code == 404:
        return {}
    response.raise_for_status()
    return response.json()


def cover_sort_key(cover: dict):
    rating = int(cover.get("Rating") or 0)
    official = int(cover.get("Official") or 0)
    return (-official, -rating, int(cover.get("CoverID") or 0))


def download_cover(game: dict, cover: dict) -> dict:
    title_id = game["title_id"].upper()
    cover_id = str(cover["CoverID"])
    destination = OUTPUT / f"{game['asset_id']}-{cover_id}.webp"
    source_url = f"{BASE}/Covers/{title_id}/Large/{cover_id}.png"
    if not destination.exists():
        response = requests.get(source_url, timeout=60, headers={"User-Agent": "X360CZCatalog/1.0"})
        response.raise_for_status()
        image = Image.open(BytesIO(response.content)).convert("RGB")
        image = ImageOps.contain(image, (438, 600), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (438, 600), "#111713")
        canvas.paste(image, ((438 - image.width) // 2, (600 - image.height) // 2))
        canvas.save(destination, "WEBP", quality=82, method=6)
    return {
        "cover_id": cover_id,
        "file": f"assets/covers/{destination.name}",
        "official": cover.get("Official") == "1",
        "rating": int(cover.get("Rating") or 0),
        "source_url": source_url,
    }


def sync_game(game: dict) -> tuple[str, dict]:
    title_id = game["title_id"].upper()
    metadata_url = f"{BASE}/Covers/{title_id}/metadata.json"
    metadata = get_json(metadata_url)
    covers = sorted(metadata.get("Covers", []), key=cover_sort_key)
    records = []
    for cover in covers:
        try:
            records.append(download_cover(game, cover))
        except (requests.RequestException, OSError, ValueError) as exc:
            print(f"VAROVÁNÍ {game['title']}: cover {cover.get('CoverID')}: {exc}")
    return game["asset_id"], {
        "title": game["title"],
        "title_id": title_id,
        "metadata_url": metadata_url,
        "covers": records,
    }


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    games = json.loads(CATALOG.read_text(encoding="utf-8"))["games"]
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = dict(executor.map(sync_game, games))

    referenced = {Path(cover["file"]).name for game in results.values() for cover in game["covers"]}
    for path in OUTPUT.glob("*.webp"):
        if path.name not in referenced:
            path.unlink()

    total = sum(len(game["covers"]) for game in results.values())
    MANIFEST.write_text(json.dumps({
        "source": "XboxUnity-Scraper by UncreativeXenon",
        "source_url": "https://github.com/UncreativeXenon/XboxUnity-Scraper",
        "license_note": "Metadata archive: CC BY-NC 4.0. Original XboxUnity images remain property of their respective owners.",
        "game_count": sum(bool(game["covers"]) for game in results.values()),
        "cover_count": total,
        "games": results,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    covered = sum(bool(game["covers"]) for game in results.values())
    print(f"Synchronizovano {total} obalu pro {covered}/{len(games)} her.")


if __name__ == "__main__":
    main()
