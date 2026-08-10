# Bot de novetats CE Sabadell per a X

Publica automàticament novetats i resultats del CE Sabadell a X (Twitter),
diverses vegades al dia, basant-se en:

- **Google News** filtrat per "CE Sabadell" (agrega premsa esportiva: Mundo
  Deportivo, Sport, Diari de Sabadell, etc.)
- **Web oficial del club** (cesabadellfc.com)

La publicació a X es fa a través de **Postproxy** (pla gratuït, sense
targeta), que gestiona la connexió amb X per tu — no cal donar-se d'alta al
costós API oficial de X per a desenvolupadors.

## Configuració (uns 10 minuts)

### 1. Crea un compte a Postproxy i connecta X

1. Vés a https://postproxy.dev i registra't (pla gratuït).
2. Al dashboard, connecta el teu compte de X seguint el flux d'autorització.
3. Ves a **Settings → API Keys** i crea una clau nova. Copia-la — la
   necessitaràs al pas 3.

### 2. Puja aquest projecte a GitHub

1. Crea un repositori nou (pot ser privat) a GitHub.
2. Puja tots aquests fitxers (`bot.py`, `requirements.txt`, `posted.json`,
   `.github/workflows/bot.yml`, aquest `README.md`).

### 3. Configura el secret de l'API key

Al repositori de GitHub:

1. **Settings → Secrets and variables → Actions → New repository secret**
2. Nom: `POSTPROXY_API_KEY`
3. Valor: la clau que vas copiar al pas 1.

Si tens més d'un perfil de X connectat a Postproxy i vols triar-ne un de
concret, ves també a la pestanya **Variables** (al mateix lloc) i crea
`POSTPROXY_PROFILE` amb l'id del perfil (si no el crees, el bot farà servir
automàticament el primer perfil de X connectat).

### 4. Activa i prova el workflow

1. Ves a la pestanya **Actions** del repositori.
2. Selecciona **CE Sabadell X Bot** i prem **Run workflow** per fer una
   prova manual.
3. Revisa els logs: t'hi diran quantes notícies ha trobat i quantes ha
   publicat.
4. Si tot va bé, el workflow ja s'executarà sol als horaris programats
   (4 cops al dia, definits a `.github/workflows/bot.yml`).

## Personalització

Tot el que voldràs tocar més sovint és al principi de `bot.py`, dins el
diccionari `CONFIG`:

- `sources`: afegeix o treu fonts RSS (per exemple, el feed d'algun mitjà
  local que segueixi molt el club).
- `max_posts_per_run`: quants tuits nous es publiquen com a màxim cada
  vegada que s'executa el bot (per defecte 3, per no saturar el compte).
- Horaris: es canvien a `.github/workflows/bot.yml`, a la secció `cron`
  (format UTC).

## Com evita duplicats

Cada article publicat es desa (amb el seu enllaç) a `posted.json`, que el
mateix workflow torna a pujar al repositori després de cada execució. Així,
la propera vegada que el bot corri, sap què ja ha publicat i no ho repeteix.
Els registres de més de 30 dies es netegen automàticament.

## Límits a tenir en compte

- El pla gratuït de Postproxy té un límit de publicacions mensuals — si el
  bot es queda sense marge, els logs del workflow t'ho indicaran amb un
  error de Postproxy.
- El filtre de rellevància és bàsic (busca "Sabadell", "arlequinat", "Nova
  Creu Alta"...). Si detectes falsos positius o notícies que se t'escapen,
  ajusta la funció `looks_relevant()` a `bot.py`.
