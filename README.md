# X360 CZ Archive

Katalog, scanner a obnova vzdálených kopií českého Xbox 360 archivu. Zdroj pravdy je `catalog/games.json`, nikoli obsah jednoho filehostingu. Lokální archivy se nepřejmenovávají ani nekopírují.

## Co projekt umí

- převést list `Games List` z Excelu na katalog JSON,
- najít očekávané `.7z` archivy v lokálních adresářích,
- řešit odlišné lokální názvy explicitními aliasy,
- přihlášeně načíst vlastní soubory z Webshare,
- načíst a nahrávat soubory na eDisk přes FTP,
- porovnat katalog, lokální archiv a vzdálené repliky,
- připravit bezpečný plán chybějících uploadů,
- provést upload jen s `repair --apply` a ručním potvrzením,
- publikovat prohledávatelný katalog přes GitHub Pages.

FastShare a Sdílej jsou v konfiguraci rezervované, ale zůstávají vypnuté, dokud nebude ověřeno jejich podporované upload rozhraní.

## Instalace

Vyžaduje Python 3.11 nebo novější.

```powershell
cd C:\Users\Administrator\Documents\GitHub\X360-CZ-Links-Tracker
python -m pip install -r requirements.txt
Copy-Item config.example.json config.json
Copy-Item .env.example .env
```

`config.json` a `.env` Git ignoruje. Hesla ani tokeny se nesmí commitovat.

## Přihlášení

Do `.env` vyplňte pro Webshare buď účet:

```dotenv
WEBSHARE_USERNAME=uzivatel
WEBSHARE_PASSWORD=unikatni-heslo
```

nebo existující session token:

```dotenv
WEBSHARE_WST=token
```

Pro eDisk nejdřív v účtu aktivujte FTP a potom vyplňte:

```dotenv
EDISK_USERNAME=uzivatel
EDISK_PASSWORD=jine-unikatni-heslo
```

Použijte pro služby rozdílná hesla. Stejný e-mail je v pořádku, stejné heslo by umožnilo napadení všech replik najednou.

## Import katalogu

Excel vedený v repozitáři je `source/X360_CZ_GamesList_web_databaze.xlsx`. Běžná aktualizace proto vypadá takto:

1. nahraďte tento soubor novou verzí Excelu,
2. změnu commitněte a pushněte na větev `main`,
3. GitHub Actions automaticky znovu vytvoří JSON, zkontroluje Webshare a publikuje web.

Ručně lze stejný kompletní krok spustit příkazem:

```powershell
python archive_tool.py refresh
```

Jednorázový import Excelu z jiné cesty zůstává k dispozici:

```powershell
python archive_tool.py import-xlsx "C:\cesta\X360_CZ_GamesList_web_databaze.xlsx"
```

Výsledkem je `catalog/games.json`. Stabilním identifikátorem položky je kombinace Xbox Title ID a názvu varianty. Dvě různé edice mohou mít stejné Title ID.

Odlišný fyzický název se zapisuje do `catalog/local-aliases.json`. Scanner díky tomu nemusí měnit lokální soubor.

Při lokálním scanu se také aktualizuje `catalog/archive-sizes.json`. Obsahuje pouze interní ID a velikost archivu, nikdy lokální cestu. Díky němu GitHub pozná i vzdálený soubor se správným názvem, který je neúplný nebo poškozený.

## Kontrola

```powershell
python archive_tool.py scan
```

Rychlý scan porovnává názvy a velikosti. Hash všech lokálních archivů lze dopočítat samostatně:

```powershell
python archive_tool.py scan --hash
```

U velké knihovny může kompletní SHA-256 kontrola trvat dlouho. Při uploadu se hash cílového souboru spočítá automaticky.

Stav se ukládá pouze lokálně do `.archive-state/` a neodesílá se do GitHubu.

## Plán a oprava

### Nejjednodušší interaktivní varianta

Po aktualizaci repozitáře přes GitHub Desktop dvakrát klikněte na `SPUSTIT-UPDATER.bat`. Zadejte:

1. cestu ke složce s `.7z` archivy,
2. Webshare jméno nebo e-mail,
3. Webshare heslo, které se při psaní nezobrazuje a nikam se neukládá.

Updater provede čerstvou lokální i vzdálenou kontrolu, vypíše názvy a celkovou velikost chybějících kopií a nic nenahraje, dokud nenapíšete přesně `UPLOAD`. Průběh uploadu se zobrazuje v procentech. Denní GitHub kontrola ukládá strojově čitelný seznam problémů také do `docs/data/missing.json`.

Pokud na novém počítači chybí knihovny, jednorázově spusťte `python -m pip install -r requirements.txt`.

Nejdřív pouze zobrazte plán:

```powershell
python archive_tool.py repair
```

Tento příkaz nic nenahrává. Skutečný upload vyžaduje přepínač a následné napsání slova `UPLOAD`:

```powershell
python archive_tool.py repair --apply
```

Webshare upload je navíc ve výchozí konfiguraci blokovaný pomocí `upload_enabled: false`. Zapněte ho až po kontrole dry-run plánu změnou hodnoty na `true` v lokálním `config.json`.

První živý test lze omezit na jednu hru podle Xbox Title ID:

```powershell
python archive_tool.py repair --id 415607D2
python archive_tool.py repair --id 415607D2 --apply
```

Lokální soubor například `Fallout 3 - Game of the Year Edition.7z` zůstane beze změny. Vzdálená kopie dostane technický název složený z interního ID a hashe, například:

```text
x360-425307d5-fallout-3-game-of-the-year-edition-a91f38c2e741.7z
```

Technické názvy slouží k jednoznačnému párování a verzování. Nesmí se používat k obcházení oprávněných odstranění nebo podmínek služby.

## Webový katalog

Po scanu vygenerujte veřejná data:

```powershell
python archive_tool.py build-site
```

Statický web je v `docs/`. Neobsahuje lokální cesty, hesla ani tokeny. Po pushnutí změn workflow `Denní kontrola a publikace katalogu` nasadí obsah přes GitHub Pages. V nastavení repozitáře zvolte **Settings → Pages → Source: GitHub Actions**.

## Automatický provoz na GitHubu

Workflow `Denní kontrola a publikace katalogu` běží:

- po změně zdrojového Excelu, scanneru, aliasů nebo CI konfigurace,
- každý den v 05:15 UTC,
- ručně přes **GitHub → Actions → Denní kontrola a publikace katalogu → Run workflow**.

GitHub se připojuje pouze k veřejné složce Webshare, takže v repozitáři nejsou potřeba žádná hesla ani tokeny. Workflow importuje Excel, zkontroluje dostupnost každé hry, vytvoří `docs/data/games.json`, případnou změnu stavu commitne a následně nasadí GitHub Pages.

GitHub Actions nevidí lokální disky s archivy a záměrně nic nenahrává. Když web ohlásí chybějící kopii, spusťte lokálně:

```powershell
python archive_tool.py scan
python archive_tool.py repair
python archive_tool.py repair --apply
```

Po uploadu lze buď počkat na další denní kontrolu, nebo workflow spustit ručně a web se aktualizuje hned. Přidání dalších her tedy vyžaduje jen doplnit Excel, uložit jej do `source/`, commitnout a pushnout; samotný web i kontrola Webshare se provedou automaticky.

## Testy

```powershell
python -m unittest -v
```

## Bezpečnost a distribuce

Automatickou obnovu používejte pouze pro soubory, které smíte na dané službě ukládat a distribuovat. Pokud služba odstraní soubor kvůli právnímu hlášení, projekt není určen k maskování a opakovanému obcházení takového odstranění.
