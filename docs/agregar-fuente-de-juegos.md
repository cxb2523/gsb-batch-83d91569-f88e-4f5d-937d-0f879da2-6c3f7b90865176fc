# ¿Querés agregar una fuente de juegos nueva?

Guía práctica para agregar juegos nuevos al dataset (`Data/TamperMonkeyRetroachievements.json`), ya sea una consola que no existía todavía o un repositorio/item de archive.org con títulos que nos faltan de una consola que ya tenemos. Basada en el proceso real usado para agregar Nintendo DSi (5 juegos) y Wii/WiiWare (25 juegos) en 2026-11.

## Regla de oro

**Nunca agregues una entrada por nombre solo.** El dataset mapea `hash exacto -> URL de descarga`. RA suele tener varias revisiones/hashes válidos por juego (regiones, versiones, parches), así que "el archivo se llama igual que el juego en RA" no prueba que *este* dump específico tenga el hash que RA espera. Si el hash no coincide, el usuario baja el archivo pero no le suma logros -- peor que no tenerlo. Siempre hasheá y confirmá contra la API antes de agregar.

## Paso 0: conseguí RAHasher

Es el hasher oficial de rcheevos -- no reimplementes el algoritmo a mano, varía por consola y es fácil de errar (ver nota de `PC Engine` en `src/core/source_resync.py::_ra_hash`, que solo cubre la regla de cartucho simple).

```bash
curl -L -o RAHasher.zip https://github.com/RetroAchievements/RALibretro/releases/latest/download/RAHasher-x64-Windows-1.8.4.zip
```
(ajustá la versión/plataforma; Linux/macOS también están en esos releases). Verificá que ande:
```bash
RAHasher.exe
# Usage: RAHasher [-v] [-s systempath] systemid filepath
```

## Paso 1: identificar candidatos

Necesitás:
- El **nombre de la consola** y su **console ID** en RA: `RetroAchievementsClient(api_key).get_console_ids()` (ver `src/core/retroachievements_api.py`). Ej: Nintendo DSi = 78, Wii = 19.
- El **repositorio/item de archive.org** con los archivos. Puede ser:
  - Un item con archivos sueltos (ej. `archive.org/download/RetroAchievementsWii`).
  - Un item con un único `.zip` que contiene un `.zip`/ROM por juego (ej. el item de DSi de octubre 2025) -- archive.org expone cada archivo interno vía `/download/<item>/<outer>.zip/<outer sin extension>%2F<interno>` (confirmalo con un `curl -I` antes de asumir que existe).

Si ya tenés juegos de esa consola en el dataset, compará nombres contra lo que ya existe (normalizando mayúsculas/paréntesis/orden de palabras) para no re-procesar lo que ya está.

## Paso 2: hashear y verificar contra RA

Por cada candidato:
1. Descargalo.
2. `RAHasher.exe <console_id> "archivo.ext"` -> te da el MD5 estilo RA.
3. Traé los hashes reales de esa consola: `client.get_game_list(console_id, with_hashes=True)` -- cada juego trae su `Hashes: [...]`.
4. Comparar (mayúsculas, con `.upper()`). Si matchea con un GameID real: **confirmado, se puede agregar**. Si no matchea pero el título sí existe en RA: es una revisión/dump distinta, **no lo agregues** -- quedaría roto en silencio.

```python
from dotenv import load_dotenv

load_dotenv(".env")
from src.core.retroachievements_api import RetroAchievementsClient
import os

c = RetroAchievementsClient(os.getenv("API_KEY"))
games = c.get_game_list(CONSOLE_ID, with_hashes=True)
ra_hashes = {h.upper(): g for g in games for h in (g.get("Hashes") or [])}
# ra_hashes.get(mi_hash.upper()) -> {"ID": ..., "Title": ...} o None
```

Descartá sin culpa los que no matcheen: DLC sueltos (no son juegos con logros propios en RA), parches/traducciones no oficiales, revisiones que archive.org tiene pero RA no reconoce.

## Paso 3: agregar al dataset

Formato de `Data/TamperMonkeyRetroachievements.json`: `{ "<GameID>": [ { "<HASH_MAYUSCULA>": "<rom_path>" } ] }`. El `rom_path` es libre en forma (no es una URL todavía), pero seguí la convención: `"<Consola>/<Carpeta del juego>/<nombre de archivo original>"`. La carpeta raíz (`<Consola>`) es lo que `get_console_from_rom_path` (`src/core/rom_info.py`) usa para agrupar/mostrar la consola -- si es un nombre nuevo, fijate que caiga bien (el fallback capitaliza palabras separadas por espacio; una palabra pegada tipo `wiiware` necesita un alias explícito en el diccionario `aliases` de `rom_info.py`, igual que agregamos `'wiiware': 'WiiWare'`).

No escribas a mano arriba de 2-3 entradas -- un script chico que arme el dict y haga `json.dump(..., ensure_ascii=False, indent=2)` preservando el resto del archivo evita reformatear todo el JSON (revisá `git diff --stat` después: si dice "miles de líneas cambiadas" en vez de unas pocas decenas, algo reformateó de más).

## Paso 4: URLGenerator (`src/factories/url_factory.py`)

Si el root folder nuevo no matchea ningún `can_handle()` existente, cae en `DefaultURLGenerator` (la colección vieja `retroachievements_collection_v5`) y el link va a estar roto. Agregá un generador nuevo **antes** de `DefaultURLGenerator` en `URLGeneratorFactory._generators`. Dos patrones según la fuente:

- **Item con archivos sueltos, mismo nombre que el `rom_path`** (ej. `WiiURLGenerator`): `can_handle` chequea el root folder, `generate_url` arma `BASE_URL + filename`.
- **Pocos juegos puntuales / item con estructura rara (zip anidado, etc.)** (ej. `DSiOctober2025URLGenerator`): un diccionario `rom_path -> nombre real` con match exacto. No contamina los generadores existentes ni necesita lógica de parsing nueva.

Agregá un `assert` al smoke check (`if __name__ == "__main__":` al final del archivo) con al menos un caso de la fuente nueva, y corré:
```bash
python -m src.factories.url_factory
python -m src.core.rom_info
```

`api/index.py` importa `URLGeneratorFactory` directo (`from src.factories.url_factory import URLGeneratorFactory`) -- **no hace falta duplicar nada ahí** (si alguna vez ves que sí, es porque alguien rompió esa consolidación, no una regla nueva a seguir).

## Paso 5: imágenes y logros (metadata)

Las carátulas/logros que se ven en `/` vienen de `Data/retroachievements_metadata.json`, generado por `scripts/sync_games_metadata.py` -- **no se actualiza solo**, hay que correrlo después de tocar el dataset:

```bash
python scripts/sync_games_metadata.py
```

Matchea por nombre de consola normalizado contra el `Name` real de RA. Si tu consola nueva no matchea sola (ej. `WiiWare` vs `Wii` en RA -- no son el mismo string ni normalizado), agregala a `MANUAL_CONSOLE_ALIASES` en `src/core/games_metadata_sync.py`:
```python
MANUAL_CONSOLE_ALIASES = {
    ...
    "WiiWare": "Wii",  # RA no tiene consola separada para WiiWare
}
```
Sin esto, los juegos entran al dataset pero salen sin carátula y sin contador de logros (exactamente el bug que motivó esta guía).

## Paso 6: verificación end-to-end

No des nada por andando sin probarlo de punta a punta:
```python
from src.core.data_manager import RetroAchievementsDataManager
from src.factories.url_factory import URLGeneratorFactory
import requests

dm = RetroAchievementsDataManager()
dm.reload_data()
rom_path = dm.find_hash("EL_HASH_EN_MAYUSCULA")
url = URLGeneratorFactory.generate_url(rom_path)
assert requests.head(url, allow_redirects=True, timeout=20).status_code == 200
```
Y corré los smoke checks existentes para confirmar que no rompiste nada: `python -m src.core.rom_info`, `python -m src.core.source_resync`, `python -m src.core.link_checker`, `python -m src.factories.url_factory`.

## Una consola, varias fuentes (ej. Nintendo DSi)

Es normal terminar con más de un repositorio para la misma consola a lo largo del tiempo (la colección vieja `v5`, un item nuevo que cubre huecos, etc.). No hace falta unificarlos:

- Si los juegos nuevos **no se superponen** con los que ya tenés (otro GameID), simplemente agregá sus hashes al dataset con su propio `rom_path` y, si la URL no sigue el patrón de un generador existente, sumá uno nuevo (Paso 4). Los juegos viejos siguen resolviendo con su generador de siempre -- no se tocan.
- Si hay **overlap** (mismo juego, misma fuente mejor/viva), ahí sí conviene un resync tipo `scripts/sync_source.py` (ver ese script) que reemplaza la URL de origen sin tocar el hash.
- Si dos fuentes de la *misma consola nominal* terminan siendo cosas conceptualmente distintas (ej. Wii discos vs WiiWare descargable), separalos en roots distintos (`Wii` vs `WiiWare`) en vez de forzarlos a convivir bajo el mismo nombre -- así cada uno puede tener su propio `URLGenerator` y no hay ambigüedad en `get_console_from_rom_path`.
