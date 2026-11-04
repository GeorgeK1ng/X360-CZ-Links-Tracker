#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8")

from x360archive.catalog import import_xlsx, load_catalog
from x360archive.providers import build_providers
from x360archive.service import (apply_plan, build_plan, load_config, load_env,
                                 save_json, scan_local, scan_remotes)
from x360archive.web import build_site


ROOT = Path(__file__).resolve().parent


def state_file(state_dir: Path, name: str):
    path = state_dir / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def print_plan(plan: dict):
    for item in plan.get("blocked_providers", []):
        print(f"BLOCKED {item['provider']}: {item['error']}")
    if not plan["actions"]:
        if plan.get("blocked_providers"):
            print("Plán není úplný, protože některá úložiště se nepodařilo zkontrolovat.")
        else:
            print("Není potřeba nic nahrávat.")
        return
    total = sum(item["size"] for item in plan["actions"])
    for item in plan["actions"]:
        gib = item["size"] / 1024 ** 3
        print(f"MISSING {item['provider']}: {item['title']} ({gib:.2f} GiB)")
    print(f"\nPlán: {len(plan['actions'])} uploadů, celkem {total / 1024 ** 3:.2f} GiB.")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Katalog, scanner a obnova replik Xbox 360 archivu.")
    parser.add_argument("--config", type=Path, default=ROOT / "config.json")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    sub = parser.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("import-xlsx", help="Převést Games List na katalog JSON.")
    imp.add_argument("xlsx", type=Path)
    imp.add_argument("--output", type=Path, default=ROOT / "catalog/games.json")
    scan = sub.add_parser("scan", help="Zkontrolovat lokální soubory a vzdálené repliky.")
    scan.add_argument("--hash", action="store_true", help="Spočítat SHA-256 všech lokálních archivů (může trvat dlouho).")
    scan.add_argument("--remote-only", action="store_true", help="Kontrolovat jen veřejné vzdálené repliky (pro GitHub Actions).")
    repair = sub.add_parser("repair", help="Naplánovat nebo provést upload chybějících replik.")
    repair.add_argument("--apply", action="store_true", help="Skutečně provést uploady z vypsaného plánu.")
    repair.add_argument("--id", help="Omezit plán na jeden asset ID nebo Xbox Title ID.")
    refresh = sub.add_parser("refresh", help="Importovat Excel, provést scan a aktualizovat web.")
    refresh.add_argument("--xlsx", type=Path, default=ROOT / "source/X360_CZ_GamesList_web_databaze.xlsx")
    refresh.add_argument("--remote-only", action="store_true", help="Přeskočit lokální disk a použít veřejný Webshare scan.")
    refresh.add_argument("--hash", action="store_true", help="Při lokálním refreshi spočítat všechny SHA-256.")
    sub.add_parser("build-site", help="Vygenerovat data statického webu.")
    args = parser.parse_args(argv)

    if args.command == "import-xlsx":
        data = import_xlsx(args.xlsx, args.output)
        print(f"Katalog vytvořen: {len(data['games'])} her → {args.output}")
        return 0

    if not args.config.exists():
        raise ValueError("Chybí config.json. Zkopírujte config.example.json na config.json a upravte ho.")
    load_env(args.env_file)
    config = load_config(args.config)
    catalog_path = ROOT / config.get("catalog", "catalog/games.json")
    if args.command == "refresh":
        imported = import_xlsx(args.xlsx, catalog_path)
        print(f"Katalog aktualizován: {len(imported['games'])} her.")
    catalog = load_catalog(catalog_path)
    state_dir = ROOT / config.get("state_dir", ".archive-state")
    archive_sizes_path = ROOT / config.get("archive_sizes", "catalog/archive-sizes.json")
    archive_sizes = json.loads(archive_sizes_path.read_text(encoding="utf-8")) if archive_sizes_path.exists() else {}
    cover_manifest_path = ROOT / "catalog/cover-sources.json"
    cover_manifest = json.loads(cover_manifest_path.read_text(encoding="utf-8")) if cover_manifest_path.exists() else {}
    providers = build_providers(config)

    if args.command in {"scan", "refresh"}:
        previous = state_file(state_dir, "local.json")
        aliases_path = ROOT / config.get("aliases", "catalog/local-aliases.json")
        aliases = json.loads(aliases_path.read_text(encoding="utf-8")) if aliases_path.exists() else {}
        remote_aliases_path = ROOT / config.get("remote_aliases", "catalog/remote-aliases.json")
        remote_aliases = json.loads(remote_aliases_path.read_text(encoding="utf-8")) if remote_aliases_path.exists() else {}
        remote_only = bool(getattr(args, "remote_only", False))
        local = None if remote_only else scan_local(
            catalog, config.get("local_roots", []), previous, args.hash, aliases, remote_aliases)
        remotes = scan_remotes(providers)
        if local is not None:
            save_json(state_dir / "local.json", local)
            archive_sizes.update({asset_id: record["size"] for asset_id, record in local["files"].items()
                                  if record.get("status") == "healthy" and "size" in record})
            save_json(archive_sizes_path, archive_sizes)
        save_json(state_dir / "remotes.json", remotes)
        if local is not None:
            local_counts = {}
            for item in local["files"].values():
                local_counts[item["status"]] = local_counts.get(item["status"], 0) + 1
            print("Lokální stav:", ", ".join(f"{key}={value}" for key, value in sorted(local_counts.items())))
            print(f"Lokální soubory mimo katalog: {len(local.get('extra_files', []))}")
        else:
            print("Lokální scan přeskočen (remote-only).")
        for name, remote in remotes["providers"].items():
            removed = sum(bool(item.get("removed")) for item in remote["files"])
            active = len(remote["files"]) - removed
            print(f"{name}: {remote['status']}, aktivní={active}, odstraněné={removed}")
        if args.command == "refresh":
            build_site(catalog, local, remotes, ROOT / "docs", remote_aliases, aliases, archive_sizes, cover_manifest)
            print("Webová data byla aktualizována.")
        return 0

    local = state_file(state_dir, "local.json")
    remotes = state_file(state_dir, "remotes.json")
    if args.command == "repair":
        if not local or not remotes:
            raise ValueError("Nejdřív spusťte: python archive_tool.py scan")
        plan = build_plan(catalog, local, remotes, list(providers))
        if args.id:
            wanted = args.id.casefold()
            plan["actions"] = [item for item in plan["actions"]
                               if item["asset_id"].casefold() == wanted or item["title_id"].casefold() == wanted]
            plan["action_count"] = len(plan["actions"])
        save_json(state_dir / "repair-plan.json", plan)
        print_plan(plan)
        if not args.apply:
            print("Dry-run: nic nebylo nahráno. Pro provedení použijte repair --apply.")
            return 0
        answer = input("Opravdu nahrát všechny položky z plánu? Napište UPLOAD: ")
        if answer != "UPLOAD":
            print("Zrušeno.")
            return 2
        result = apply_plan(plan, providers, local, state_dir)
        errors = sum(item["status"] == "error" for item in result["results"])
        print(f"Dokončeno: {len(result['results']) - errors} uploadů, {errors} chyb.")
        return 1 if errors else 0

    remote_aliases_path = ROOT / config.get("remote_aliases", "catalog/remote-aliases.json")
    remote_aliases = json.loads(remote_aliases_path.read_text(encoding="utf-8")) if remote_aliases_path.exists() else {}
    aliases_path = ROOT / config.get("aliases", "catalog/local-aliases.json")
    aliases = json.loads(aliases_path.read_text(encoding="utf-8")) if aliases_path.exists() else {}
    build_site(catalog, local, remotes, ROOT / "docs", remote_aliases, aliases, archive_sizes, cover_manifest)
    print("Webová data byla vygenerována do docs/data/games.json.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"Chyba: {exc}", file=sys.stderr)
        raise SystemExit(1)
