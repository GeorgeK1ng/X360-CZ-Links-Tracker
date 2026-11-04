# X360 CZ Archive

Pečlivě sestavený katalog her pro Xbox 360 s českou lokalizací, informacemi o obsahu a aktuální dostupností archivních kopií.

**Veřejný katalog:** [georgek1ng.github.io/X360-CZ-Links-Tracker](https://georgek1ng.github.io/X360-CZ-Links-Tracker/)

Zdrojová databáze je vedena v Excelu `source/X360_CZ_GamesList_web_databaze.xlsx`. Katalog JSON a web se z ní automaticky generují. Lokální archivy se při kontrole ani uploadu nepřejmenovávají.

## Co projekt dělá

- vytváří webový katalog z listu `Games List` ve zdrojovém Excelu,
- zobrazuje popisy, hodnocení, PEGI, žánry, češtinu, DLC, Title Update a obaly her,
- kontroluje dostupnost archivních kopií na Webshare,
- porovnává katalog s lokálními `.7z` archivy,
- připraví a po potvrzení nahraje pouze chybějící soubory,
- nahrává soubory pod jednoznačným technickým názvem, aniž by změnil jejich lokální název,
- každý den automaticky aktualizuje stav katalogu pomocí GitHub Actions.

Podpora dalších úložišť je připravená v konfiguraci, ale zatím není aktivní.

## Přidání nebo úprava her

1. Upravte `source/X360_CZ_GamesList_web_databaze.xlsx`, především list `Games List`.
2. Změnu commitněte a pushněte do větve `main` pomocí GitHub Desktopu.
3. GitHub Actions automaticky:
   - převede Excel do katalogu,
   - zkontroluje Webshare,
   - stáhne dostupné obaly,
   - spustí testy,
   - aktualizuje veřejný web.

Workflow lze spustit také ručně přes **GitHub → Actions → Denní kontrola a publikace katalogu → Run workflow**. Jinak se spouští automaticky každý den v 05:15 UTC a po změně zdrojových dat nebo scanneru.

## Oprava chybějících souborů

1. V GitHub Desktopu použijte **Fetch origin** a následně **Pull origin**, pokud je dostupný.
2. Dvakrát klikněte na `SPUSTIT-UPDATER.bat`.
3. Zadejte cestu ke složce s lokálními `.7z` archivy.
4. Zadejte Webshare jméno nebo e-mail a heslo. Heslo se při psaní nezobrazuje a nikam se neukládá.
5. Updater provede lokální i vzdálenou kontrolu a vypíše chybějící hry i jejich celkovou velikost.
6. Upload začne až po napsání přesného potvrzení `UPLOAD`.

Po dokončení lze počkat na další denní kontrolu, nebo workflow spustit ručně. Web se potom aktualizuje automaticky. Strojově čitelný seznam problémů se ukládá do `docs/data/missing.json`.

Lokální soubor, například `Fallout 3 - Game of the Year Edition.7z`, zůstává beze změny. Vzdálená kopie dostane technický název odvozený od interního ID a hashe, například:

```text
x360-425307d5-fallout-3-game-of-the-year-edition-a91f38c2e741.7z
```

Technické názvy slouží k jednoznačnému párování a verzování. Nesmí se používat k obcházení oprávněných odstranění nebo podmínek služby.

## První spuštění na novém počítači

Vyžaduje Python 3.11 nebo novější. V PowerShellu spusťte:

```powershell
cd C:\Users\Administrator\Documents\GitHub\X360-CZ-Links-Tracker
python -m pip install -r requirements.txt
Copy-Item config.example.json config.json
Copy-Item .env.example .env
```

`config.json` a `.env` Git ignoruje. Hesla ani tokeny se nesmí commitovat.

## Pokročilé příkazy

Tyto příkazy nejsou při běžném používání potřeba:

```powershell
# Kompletní lokální kontrola
python archive_tool.py scan

# Kontrola včetně SHA-256 všech archivů
python archive_tool.py scan --hash

# Pouze zobrazit plán opravy
python archive_tool.py repair

# Provést upload po následném ručním potvrzení
python archive_tool.py repair --apply

# Ručně znovu vytvořit katalog a web
python archive_tool.py refresh
```

Stav lokální kontroly se ukládá do `.archive-state/` a neposílá se na GitHub. Odlišné fyzické názvy archivů lze zapsat do `catalog/local-aliases.json`, takže není nutné přejmenovávat lokální soubory.
