from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Iterable

from .catalog import remote_name, sha256_file


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_env(path: Path):
    if not path.exists():
        return
    import os
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def index_local(roots: Iterable[str]) -> dict[str, list[Path]]:
    index = {}
    for root_value in roots:
        root = Path(root_value)
        if not root.exists():
            continue
        for path in root.rglob("*.7z"):
            index.setdefault(path.name.casefold(), []).append(path)
    return index


def scan_local(catalog: dict, roots: list[str], previous: dict | None = None,
               hash_all: bool = False, aliases: dict | None = None,
               remote_aliases: dict | None = None) -> dict:
    previous_files = (previous or {}).get("files", {})
    local_index = index_local(roots)
    records = {}
    matched_paths = set()
    aliases = aliases or {}
    remote_aliases = remote_aliases or {}
    for game in catalog["games"]:
        asset_id = game["asset_id"]
        local_filename = aliases.get(asset_id, game["expected_filename"])
        candidates = local_index.get(local_filename.casefold(), [])
        record = {"asset_id": asset_id, "title_id": game["title_id"],
                  "expected_filename": game["expected_filename"], "local_filename": local_filename,
                  "remote_filenames": remote_aliases.get(asset_id, [])}
        if len(candidates) == 1:
            path = candidates[0]
            matched_paths.add(str(path.resolve()).casefold())
            stat = path.stat()
            record.update(status="healthy", path=str(path), size=stat.st_size, mtime_ns=stat.st_mtime_ns)
            old = previous_files.get(asset_id, {})
            if old.get("size") == stat.st_size and old.get("mtime_ns") == stat.st_mtime_ns and old.get("sha256"):
                record["sha256"] = old["sha256"]
            elif hash_all:
                record["sha256"] = sha256_file(path)
        elif not candidates:
            record["status"] = "missing"
        else:
            record.update(status="ambiguous", candidates=[str(path) for path in candidates])
        records[asset_id] = record
    extras = sorted(str(path) for candidates in local_index.values() for path in candidates
                    if str(path.resolve()).casefold() not in matched_paths)
    return {"scanned_at": utc_now(), "roots": roots, "files": records, "extra_files": extras}


def scan_remotes(providers: dict) -> dict:
    data = {"scanned_at": utc_now(), "providers": {}}
    for name, provider in providers.items():
        try:
            files = [item.json() for item in provider.list_files()]
            data["providers"][name] = {"status": "ok", "files": files}
        except Exception as exc:
            data["providers"][name] = {"status": "error", "error": str(exc), "files": []}
    return data


def match_remote(record: dict, remote_files: list[dict]) -> dict | None:
    expected_size = record.get("size")

    def size_matches(item: dict) -> bool:
        return expected_size is None or int(item.get("size", 0)) in {0, int(expected_size)}

    digest = record.get("sha256")
    if digest:
        expected = remote_name(record["asset_id"], digest).casefold()
        for item in remote_files:
            if item["name"].casefold() == expected and not item.get("removed"):
                if size_matches(item):
                    return item

    # GitHub Actions does not have the local archive hash. The asset ID is stable and
    # the uploader puts it into every anonymized name, so the public scan can still
    # reconcile the file safely. The tracked size prevents a partial/wrong upload
    # from being accepted as healthy.
    technical_name = re.compile(
        rf"^x360-{re.escape(record['asset_id'])}-[0-9a-f]{{12}}\.7z$",
        re.IGNORECASE,
    )
    for item in remote_files:
        if technical_name.fullmatch(item["name"]) and not item.get("removed") and size_matches(item):
            return item

    # Compatibility with the old human-readable uploads.
    legacy_names = {record["expected_filename"].casefold(),
                    record.get("local_filename", record["expected_filename"]).casefold()}
    legacy_names.update(name.casefold() for name in record.get("remote_filenames", []))
    for item in remote_files:
        item_name = item["name"].casefold()
        item_stem = Path(item_name).stem
        item_without_suffix = re.sub(r"\([a-z0-9]+\)$", "", item_stem) + Path(item_name).suffix
        if (item_name in legacy_names or item_without_suffix in legacy_names) and not item.get("removed"):
            if size_matches(item):
                return item
    return None


def build_plan(catalog: dict, local: dict, remotes: dict, provider_names: list[str]) -> dict:
    actions = []
    blocked = []
    games = {game["asset_id"]: game for game in catalog["games"]}
    for asset_id, local_record in local["files"].items():
        if local_record.get("status") != "healthy":
            continue
        for provider_name in provider_names:
            provider_state = remotes.get("providers", {}).get(provider_name, {})
            if provider_state.get("status") != "ok":
                if not any(item["provider"] == provider_name for item in blocked):
                    blocked.append({"provider": provider_name,
                                    "error": provider_state.get("error", "Provider nebyl úspěšně zkontrolován.")})
                continue
            if not match_remote(local_record, provider_state.get("files", [])):
                actions.append({
                    "action": "upload",
                    "provider": provider_name,
                    "asset_id": asset_id,
                    "title_id": games[asset_id]["title_id"],
                    "title": games[asset_id]["title"],
                    "local_path": local_record["path"],
                    "size": local_record["size"],
                })
    return {"created_at": utc_now(), "action_count": len(actions),
            "blocked_providers": blocked, "actions": actions}


def apply_plan(plan: dict, providers: dict, local_state: dict, state_dir: Path) -> dict:
    results = []
    for action in plan["actions"]:
        if action["action"] != "upload":
            continue
        provider = providers[action["provider"]]
        local_record = local_state["files"][action["asset_id"]]
        path = Path(action["local_path"])
        digest = local_record.get("sha256") or sha256_file(path)
        local_record["sha256"] = digest
        name = remote_name(action["asset_id"], digest)
        try:
            uploaded = provider.upload(path, name)
            results.append({"status": "uploaded", "asset_id": action["asset_id"], "title_id": action["title_id"],
                            "provider": action["provider"], "remote": uploaded.json()})
        except Exception as exc:
            results.append({"status": "error", "asset_id": action["asset_id"], "title_id": action["title_id"],
                            "provider": action["provider"], "error": str(exc)})
    save_json(state_dir / "local.json", local_state)
    result = {"completed_at": utc_now(), "results": results}
    save_json(state_dir / "last-repair.json", result)
    return result
