#!/usr/bin/env python3
"""Webshare folder inventory and persistent manual statuses. Python 3.11+."""
from collections import Counter
import argparse
import csv
import io
import json
import os
from pathlib import Path
import re
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

DEFAULT = 'https://webshare.cz/#/folder/QFWv3mjitp/xbox360cz'
STATUSES = ('nové', 'rozpracováno', 'hotovo', 'přeskočeno', 'problém')


def folder_id(value):
    match = re.search(r'(?:#/folder/|/folder/)([A-Za-z0-9]+)', value)
    if match:
        return match[1]
    if re.fullmatch(r'[A-Za-z0-9]+', value):
        return value
    raise ValueError('Neplatný odkaz nebo ID složky.')


def api(ident, offset, limit):
    payload = urlencode(dict(ident=ident, offset=offset, limit=limit, subfolders=1)).encode()
    for attempt in range(4):
        try:
            req = Request('https://webshare.cz/api/folder/', data=payload,
                          headers={'Accept': 'text/xml', 'User-Agent': 'WebshareInventory/1.0'})
            with urlopen(req, timeout=60) as response:
                root = ET.fromstring(response.read())
            if root.findtext('status') != 'OK':
                raise ValueError(f"Webshare: {root.findtext('code')}: {root.findtext('message')}")
            return root
        except (OSError, ET.ParseError):
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)


def crawl(ident, fetch=api):
    result, visited = {}, set()
    pending = [(ident, '')]
    while pending:
        current, parent = pending.pop()
        if current in visited:
            continue
        visited.add(current)
        offset, signatures = 0, set()
        while True:
            root = fetch(current, offset, 100)
            path = parent or root.findtext('name', current)
            entries = [e for e in root if e.tag in ('file', 'folder')]
            if not entries:
                total = root.findtext('total')
                if total and offset < int(total):
                    raise ValueError('API vrátilo neúplný seznam; výstup nebyl změněn.')
                break
            signature = tuple((e.tag, e.findtext('ident')) for e in entries)
            if signature in signatures:
                raise ValueError('API opakuje stránku; výstup nebyl změněn.')
            signatures.add(signature)
            for entry in entries:
                fid = entry.findtext('ident')
                if not fid or not re.fullmatch(r'[A-Za-z0-9]+', fid):
                    raise ValueError('Chybné ID ve výsledku API.')
                name = entry.findtext('name', fid)
                if entry.tag == 'folder':
                    pending.append((fid, path + '/' + name))
                else:
                    record = result.setdefault(fid, dict(id=fid, name=name,
                        url='https://webshare.cz/#/file/' + fid,
                        size_bytes=entry.findtext('size', '0'), folders=[]))
                    if path not in record['folders']:
                        record['folders'].append(path)
            offset += len(entries)
            total = root.findtext('total')
            if total and offset >= int(total):
                break
            time.sleep(0.2)
    return result


CHECK_FIELDS = ('download_status', 'download_code', 'download_message', 'checked_at')


def request_download(ident):
    params = dict(ident=ident, download_type='file_download', force_https=1)
    token = os.environ.get('WEBSHARE_WST')
    if token:
        params['wst'] = token
    req = Request('https://webshare.cz/api/file_link/', data=urlencode(params).encode(),
                  headers={'Accept': 'text/xml', 'User-Agent': 'WebshareInventory/2.0'})
    with urlopen(req, timeout=20) as response:
        return ET.fromstring(response.read())


def check_download(ident, request=request_download):
    now = datetime.now(timezone.utc).isoformat()
    try:
        root = request(ident)
        code = root.findtext('code', '')
        message = root.findtext('message', '')
        if root.findtext('status') == 'OK' and root.findtext('link'):
            status = 'odkaz_vydán'
            message = 'Webshare povolil požadavek na stažení; přenos souboru nebyl ověřen.'
        else:
            status = {
                'FILE_LINK_FATAL_1': 'nenalezen',
                'FILE_LINK_FATAL_3': 'vyžaduje_heslo',
                'FILE_LINK_FATAL_4': 'dočasně_nedostupný',
                'FILE_LINK_FATAL_5': 'limit_stahování',
                'FILE_LINK_FATAL_6': 'neveřejný',
            }.get(code, 'neověřeno')
        return dict(download_status=status, download_code=code,
                    download_message=message, checked_at=now)
    except (OSError, ET.ParseError):
        # Do not log URLs or exception text: they might contain a token.
        return dict(download_status='chyba_kontroly', download_code='NETWORK_OR_XML',
                    download_message='Síťová chyba, HTTP chyba nebo neplatná odpověď; zkusit znovu.',
                    checked_at=now)


def check_records(data, only=None, request=request_download, delay=0.5):
    if only and only not in data['files']:
        raise ValueError('Neznámé ID souboru.')
    rows = [data['files'][only]] if only else [r for r in data['files'].values() if r['present']]
    for index, row in enumerate(rows):
        row.update(check_download(row['id'], request))
        print(f"Kontrola {index + 1}/{len(rows)}: {row['id']} → {row['download_status']}", flush=True)
        if index + 1 < len(rows):
            time.sleep(delay)


def atomic(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(text, encoding='utf-8')
    os.replace(temp, path)


def merge(old, found, now):
    records = {k: dict(v, present=False) for k, v in old.items()}
    for fid, item in found.items():
        previous = records.get(fid, {})
        records[fid] = dict(item, **{k: previous[k] for k in CHECK_FIELDS if k in previous}, status=previous.get('status', 'nové'),
            note=previous.get('note', ''), first_seen=previous.get('first_seen', now),
            last_seen=now, present=True)
    return records


README_START = '<!-- WEBShare-STATUS:START -->'
README_END = '<!-- WEBShare-STATUS:END -->'


def md(value):
    return str(value).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('|', '&#124;').replace('\\', '&#92;').replace('[', '&#91;').replace(']', '&#93;').replace('\r', ' ').replace('\n', ' ')


def render_summary(data):
    rows = sorted(data['files'].values(), key=lambda r: r['name'].casefold())
    current = [r for r in rows if r['present']]
    counts = Counter(r.get('download_status') or 'nekontrolováno' for r in current)
    problems = [r for r in current if r.get('download_status') not in (None, '', 'odkaz_vydán')]
    checks = [r['checked_at'] for r in current if r.get('checked_at')]
    lines = ['## Aktuální přehled Webshare', '',
             f"Poslední načtení složky: **{md(data.get('scanned_at', 'dosud neproběhlo'))}**.",
             f"Poslední dokončený průchod kontrolou: **{md(data.get('download_check_completed_at', 'dosud neproběhl'))}**.",
             f"Nejnovější kontrola jednotlivého souboru: {md(max(checks) if checks else 'dosud neproběhla')}. Časy jsou v UTC.", '',
             f"**{len(current)} souborů ve složce · {len(problems)} výsledků k prověření · {len(rows) - len(current)} dříve evidovaných položek mimo aktuální seznam.**", '',
             '| Výsledek kontroly | Počet |', '| --- | ---: |']
    for status, count in sorted(counts.items()):
        lines.append(f'| {md(status)} | {count} |')
    lines += ['', '`odkaz_vydán` znamená, že server vydal download URL; celý soubor ani jeho integrita nejsou ověřeny. `nenalezen` je odpověď download API, nikoli tvrzení, že odkaz chybí ve složce. Každý řádek této tabulky byl nalezen ve složce při posledním načtení. Síťová chyba nebo limit neznamenají poškozený soubor. Starší kontrolu poznáš podle času u položky.', '',
              '### Položky k prověření', '']
    if problems:
        lines += ['| Soubor | Výsledek | Kód / zpráva |', '| --- | --- | --- |']
        for r in problems:
            lines.append(f"| [{md(r['name'])}]({r['url']}) | {md(r['download_status'])} | {md(r.get('download_code', ''))}: {md(r.get('download_message', ''))} |")
    else:
        lines.append('Žádné zaznamenané problémy. Položky bez kontroly najdeš v tabulce níže.')
    lines += ['', '### Aktuální obsah složky', '',
              '| Soubor | ID | Ve složce | Stažení | Ruční stav | Poznámka | Kontrola (UTC) |',
              '| --- | --- | --- | --- | --- | --- | --- |']
    for r in current:
        present = 'ano' if r['present'] else 'ne'
        lines.append(f"| [{md(r['name'])}]({r['url']}) | {md(r['id'])} | {present} | {md(r.get('download_status') or 'nekontrolováno')} | {md(r.get('status', 'nové'))} | {md(r.get('note', ''))} | {md(r.get('checked_at', '—'))} |")
    lines += ['', 'Změna ručního stavu: **Actions → Webshare seznam → Run workflow** → vyplň ID z tabulky, stav a poznámku. Prázdné ID načte složku a zkontroluje všechny aktuální soubory.', '']
    return '\n'.join(lines)


def update_readme(data, directory):
    summary = render_summary(data)
    path = directory.parent / 'README.md'
    # README is a generated snapshot, never append to a previous snapshot.
    text = ('# Webshare — aktuální seznam\n\n'
            'Tento soubor se při každém úspěšném exportu celý přegeneruje. '
            'Návod: [USAGE.md](USAGE.md). Historie a ruční stavy: [inventory.json](data/inventory.json).\n\n'
            + README_START + '\n' + summary + README_END + '\n')
    atomic(path, text)
    step_summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if step_summary:
        with open(step_summary, 'a', encoding='utf-8') as stream:
            stream.write(summary + '\n')


def export(data, directory):
    rows = sorted((r for r in data['files'].values() if r['present']), key=lambda x: x['name'].casefold())
    out = io.StringIO(newline='')
    columns = ['id', 'name', 'url', 'size_bytes', 'folders', 'status', 'note', 'present', 'first_seen', 'last_seen', *CHECK_FIELDS]
    writer = csv.DictWriter(out, fieldnames=columns)
    writer.writeheader()
    for row in rows:
        safe = dict({k: row.get(k, '') for k in columns}, folders=' / '.join(row['folders']))
        # Prevent formula evaluation when opening external names/notes in Excel.
        for key, value in safe.items():
            if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
                safe[key] = "'" + value
        writer.writerow(safe)
    atomic(directory / 'inventory.csv', '\ufeff' + out.getvalue())
    atomic(directory / 'links.txt', '\n'.join(r['url'] for r in rows if r['present']) + '\n')
    atomic(directory / 'inventory.json', json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    update_readme(data, directory)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=Path('data'))
    sub = parser.add_subparsers(dest='command', required=True)
    scan = sub.add_parser('scan')
    scan.add_argument('--folder', default=DEFAULT)
    scan.add_argument('--check-downloads', action='store_true')
    check = sub.add_parser('check')
    check.add_argument('--id', default=None)
    edit = sub.add_parser('status')
    edit.add_argument('id')
    edit.add_argument('status', choices=STATUSES)
    edit.add_argument('--note', default=None)
    args = parser.parse_args()
    target = args.data_dir / 'inventory.json'
    data = json.loads(target.read_text(encoding='utf-8')) if target.exists() else {'files': {}}
    if args.command == 'scan':
        ident = folder_id(args.folder)
        if data.get('folder_id', ident) != ident:
            raise ValueError('Pro jinou složku použij jiný --data-dir.')
        found = crawl(ident)  # No output mutation until the entire crawl succeeds.
        now = datetime.now(timezone.utc).isoformat()
        data.update(folder_id=ident, source=args.folder, scanned_at=now,
                    files=merge(data['files'], found, now))
        print(f'Nalezeno {len(found)} souborů.')
        data.pop('download_check_completed_at', None)
        data.pop('checked_scan_at', None)
        if args.check_downloads:
            check_records(data)
            data['download_check_completed_at'] = datetime.now(timezone.utc).isoformat()
            data['checked_scan_at'] = data.get('scanned_at')
    elif args.command == 'check':
        if 'folder_id' not in data:
            raise ValueError('Nejdřív spusť scan.')
        check_records(data, args.id)
        if not args.id:
            data['download_check_completed_at'] = datetime.now(timezone.utc).isoformat()
            data['checked_scan_at'] = data.get('scanned_at')
    else:
        if args.id not in data['files']:
            raise ValueError('Neznámé ID souboru. Nejdřív spusť scan.')
        data['files'][args.id]['status'] = args.status
        if args.note is not None:
            data['files'][args.id]['note'] = args.note
    export(data, args.data_dir)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, ET.ParseError) as exc:
        print(f'Chyba: {exc}', file=sys.stderr)
        sys.exit(1)
