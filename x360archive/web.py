from __future__ import annotations

import json
from pathlib import Path


def build_site(catalog: dict, local: dict | None, remotes: dict | None, output: Path,
               remote_aliases: dict | None = None, local_aliases: dict | None = None,
               archive_sizes: dict | None = None):
    output.mkdir(parents=True, exist_ok=True)
    public_games = []
    local_files = (local or {}).get("files", {})
    remote_states = (remotes or {}).get("providers", {})
    remote_aliases = remote_aliases or {}
    local_aliases = local_aliases or {}
    archive_sizes = archive_sizes or {}
    for game in catalog["games"]:
        item = dict(game)
        local_record = local_files.get(game["asset_id"], {
            "asset_id": game["asset_id"],
            "expected_filename": game["expected_filename"],
            "local_filename": local_aliases.get(game["asset_id"], game["expected_filename"]),
            "remote_filenames": remote_aliases.get(game["asset_id"], []),
        })
        if "size" not in local_record and game["asset_id"] in archive_sizes:
            local_record["size"] = archive_sizes[game["asset_id"]]
        item["local_status"] = local_record.get("status", "unknown")
        item["providers"] = {}
        item["download_urls"] = {}
        for provider, state in remote_states.items():
            if state.get("status") != "ok":
                item["providers"][provider] = "error"
                continue
            from .service import match_remote
            matched = match_remote(local_record, state.get("files", []))
            item["providers"][provider] = "healthy" if matched else "missing"
            if matched and matched.get("url"):
                item["download_urls"][provider] = matched["url"]
        public_games.append(item)
    data_dir = output / "data"
    data_dir.mkdir(exist_ok=True)
    (data_dir / "games.json").write_text(json.dumps({"games": public_games}, ensure_ascii=False) + "\n", encoding="utf-8")
    missing = [{
        "asset_id": game["asset_id"],
        "title_id": game["title_id"],
        "title": game["title"],
        "expected_filename": game["expected_filename"],
    } for game in public_games if game.get("providers", {}).get("webshare") == "missing"]
    (data_dir / "missing.json").write_text(json.dumps({
        "count": len(missing), "games": missing
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
