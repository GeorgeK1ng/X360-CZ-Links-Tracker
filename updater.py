#!/usr/bin/env python3
from __future__ import annotations

from getpass import getpass
import json
import os
from pathlib import Path
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8")

from x360archive.catalog import load_catalog
from x360archive.providers import WebshareProvider
from x360archive.service import apply_plan, build_plan, save_json, scan_local, scan_remotes


ROOT = Path(__file__).resolve().parent


def read_json(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def main() -> int:
    print("\nX360 CZ – jednoduchá obnova Webshare\n")
    default_config = ROOT / "config.json"
    config = read_json(default_config, read_json(ROOT / "config.example.json", {}))

    suggested = (config.get("local_roots") or [""])[0]
    prompt = f"Cesta ke složce s archivy [{suggested}]: " if suggested else "Cesta ke složce s archivy: "
    entered = input(prompt).strip().strip('"')
    library = Path(entered or suggested)
    if not library.is_dir():
        print(f"Chyba: složka neexistuje: {library}")
        return 1

    username = input("Webshare jméno nebo e-mail: ").strip()
    password = getpass("Webshare heslo (nebude uloženo): ")
    if not username or not password:
        print("Chyba: jméno a heslo nesmí být prázdné.")
        return 1

    catalog = load_catalog(ROOT / config.get("catalog", "catalog/games.json"))
    aliases = read_json(ROOT / config.get("aliases", "catalog/local-aliases.json"), {})
    remote_aliases = read_json(ROOT / config.get("remote_aliases", "catalog/remote-aliases.json"), {})
    state_dir = ROOT / config.get("state_dir", ".archive-state")
    previous = read_json(state_dir / "local.json", None)

    print("\n1/3 Kontroluji lokální archivy…")
    local = scan_local(catalog, [str(library)], previous, False, aliases, remote_aliases)
    unavailable = [record for record in local["files"].values() if record.get("status") != "healthy"]
    print(f"Nalezeno lokálně: {len(local['files']) - len(unavailable)}/{len(local['files'])}")

    def show_progress(path: Path, sent: int, total: int):
        percent = sent * 100 / total if total else 100
        print(f"\r  {path.name}: {percent:6.2f}%", end="", flush=True)
        if sent >= total:
            print()

    provider_config = dict(config.get("providers", {}).get("webshare", {}))
    provider_config.update(enabled=True, upload_enabled=True, progress_callback=show_progress)
    provider = WebshareProvider(provider_config, env={
        "WEBSHARE_USERNAME": username,
        "WEBSHARE_PASSWORD": password,
    })

    print("2/3 Kontroluji Webshare…")
    remotes = scan_remotes({"webshare": provider})
    remote_state = remotes["providers"]["webshare"]
    if remote_state.get("status") != "ok":
        print(f"Chyba přihlášení nebo kontroly: {remote_state.get('error', 'neznámá chyba')}")
        return 1

    save_json(state_dir / "local.json", local)
    save_json(state_dir / "remotes.json", remotes)
    archive_sizes_path = ROOT / config.get("archive_sizes", "catalog/archive-sizes.json")
    archive_sizes = read_json(archive_sizes_path, {})
    archive_sizes.update({key: value["size"] for key, value in local["files"].items()
                          if value.get("status") == "healthy" and "size" in value})
    save_json(archive_sizes_path, archive_sizes)

    plan = build_plan(catalog, local, remotes, ["webshare"])
    print("\nChybějící kopie připravené k uploadu:")
    if not plan["actions"]:
        print("  Žádné – Webshare je aktuální.")
        return 0
    for number, action in enumerate(plan["actions"], 1):
        print(f"  {number}. {action['title']} ({action['size'] / 1024 ** 3:.2f} GiB)")
    total = sum(action["size"] for action in plan["actions"])
    print(f"\nCelkem: {len(plan['actions'])} souborů, {total / 1024 ** 3:.2f} GiB")
    if unavailable:
        print(f"Upozornění: {len(unavailable)} katalogových souborů nebylo lokálně nalezeno a nelze je nahrát.")

    confirmation = input("\nPro zahájení uploadu napište přesně UPLOAD: ")
    if confirmation != "UPLOAD":
        print("Upload zrušen. Nic se nezměnilo.")
        return 0

    print("\n3/3 Nahrávám. Nezavírejte okno…")
    result = apply_plan(plan, {"webshare": provider}, local, state_dir)
    uploaded = [item for item in result["results"] if item["status"] == "uploaded"]
    errors = [item for item in result["results"] if item["status"] == "error"]
    print(f"\nHotovo: nahráno {len(uploaded)}, chyb {len(errors)}.")
    for item in errors:
        print(f"  CHYBA {item['title_id']}: {item['error']}")
    print("Web se aktualizuje při příští denní kontrole GitHubu nebo po ručním spuštění workflow.")
    return 1 if errors else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyboardInterrupt, EOFError):
        print("\nZrušeno.")
        raise SystemExit(2)
    except Exception as exc:
        print(f"\nChyba: {exc}")
        raise SystemExit(1)
