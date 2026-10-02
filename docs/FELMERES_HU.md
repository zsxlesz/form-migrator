# Felmérés – mi tiltja a generált végpontokat

A felmérés sok formot generál egyszerre, majd egy megosztható riportban összesíti, miért maradnak
tiltva (HTTP 501, kommentben hagyott SQL) a DPS-végpontok. A riport alapján látszik, melyik hiányzó
fordítási szabály szabadítaná fel a legtöbb végpontot.

## Futtatás a webes felületen

1. A „Forrás” részben kapcsold be a **Felmérés** kapcsolót.
2. Húzd be a formokat (.fmb vagy Forms2XML .xml), akár egyet, akár százat.
3. Ha a formok OLB-re hivatkoznak, add hozzá az OLB-exportokat (`…_olb.xml`). Ha van, a `schema.json`-t
   is megadhatod, de nem kötelező.
4. Indítsd el a „Felmérés indítása” gombbal.

Felmérés módban:

- nem kell AWU_AZON;
- a több ablakos formok nem állnak meg kérdéssel, az összes ablak elkészül;
- több lehetséges főablak esetén az első lesz a fő képernyő.

A futás a Feladatok fülön, a tömeges futtatások között követhető. A végén a „Mi tiltja a végpontokat”
táblázat mutatja a legfontosabb okokat. A „Felmérés” sor gombjai letöltik a riportot:

- **Markdown:** `FELMERES_HU.md`, ez olvasható és megosztható.
- **JSON:** `felmeres.json`, a teljes adat.
- **Nevekkel:** a valódi nevekkel készült változat. Ez csak helyi használatra való, ne oszd meg.

Az „Összesítő ZIP” is tartalmazza a felmérés két fájlját.

## Futtatás parancssorból

```
python -m niva_forms survey forms/ --out felmeres
python -m niva_forms survey forms/ --out felmeres --olb kozos_olb.xml --schema schema.json
python -m niva_forms survey --out felmeres --report-only --names   # meglévő kimenetből, nevekkel
```

A kimenet ugyanaz, mint a weben: `FELMERES_HU.md` és `felmeres.json`, mellettük a szokásos
`PORTFOLIO_HU.md`, a formonkénti almappákban pedig a generált modulok.

A felmérés a `backend_live` beállítással fut, ahogy a web is. Így a riport azt mutatja, mit nem tud
lefordítani a generátor, nem az ellenőrzési szabályokat: nincs MODULE_REVIEWED-kapu, és az írás csak
akkor tiltott, ha a `schema.json` kifejezetten tiltja.

## Mi van a riportban

- **Végpontok:** műveletenként az összes, az engedélyezett, a kapcsolóra váró és a tiltott végpontok
  száma.
- **Okok:** a tiltott végpontok okai hibakóddal és üzenetsablonnal. Az **egyedüli ok** oszlop
  megmutatja, hány végpontot csak az adott ok tilt, vagyis hány nyílik meg, ha ezt az egy okot
  megszüntetjük. Az első okokhoz kódpéldák tartoznak.
- **Átültetendő triggerek:** eseményenként és okonként, a bennük lévő Forms-hívásokkal és
  SQL-szerkezetekkel.
- **Szerkezetek:** hány végpontot tiltó trigger tartalmazza az egyes elemeket (pl. `SET_BLOCK_PROPERTY`,
  `GO_BLOCK`, `:SYSTEM.*`, `SELECT … INTO`, csomaghívás).
- **Lekérdezések és LOV-ok:** a tiltott olvasások WHERE feltételei és a hibás rekordcsoport-lekérdezések.
- **Adatforrások, hibakódok, sikertelen formok.**

## Mit takar el a megosztható változat

A kódpéldák szerkezete megmarad. Ami helyettesítőre cserélődik:

- **Nevek:** táblák, oszlopok, rutinok, blokkok, mezők, például `N1`, `:B1.I2`, `:GLOBAL.G1`,
  `:PARAMETER.P1`.
- **Szöveges literálok:** `'…'`. Ha a szövegben SQL van, például egy `DEFAULT_WHERE` értéke, annak
  csak a szerkezete marad.
- **Négy- vagy többjegyű számok:** `N`.
- **Kommentek:** kimaradnak.

Ami megmarad:

- **Nyelvi elemek:** a kulcsszavak, az Oracle-függvények, a Forms beépített hívásai és
  tulajdonságnevei.
- **A `:SYSTEM.*` változók.**

A formokat `F1`, `F2` stb. jelöli.

A hibák feltárásához a `FELMERES_HU.md` elküldése általában elég. Ha a JSON-t is csatolod, minden sor
és példa látszik.
