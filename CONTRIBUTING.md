# Contribuir a JobFilter

¡Gracias por querer ayudar! Esta guía explica cómo preparar el entorno, cómo está organizado
el código y qué se espera de un pull request. Issues y PRs en español o en inglés.

## Formas de contribuir

- **Integrar una plataforma**: es lo que más valor aporta. Ver
  [docs/plataformas.md](docs/plataformas.md) y abre primero un issue con la plantilla **Nueva
  plataforma** para coordinar.
- **Reportar un bug**: con la plantilla **Reporte de bug**.
- **Proponer una mejora**: con la plantilla **Propuesta**. JobFilter es intencionalmente
  simple (un botón, una lista y la lista negra), así que conviene discutir la idea antes de
  programarla.
- **Mejorar la documentación o el perfil de ejemplo.**

## Preparar el entorno

Necesitas [Bun](https://bun.sh) 1.4+ y Git.

```sh
git clone https://github.com/SebastianAsprino/jobfilter.git
cd jobfilter
bun install
cp -r profile.example profile
bun run dev
```

Si también quieres probar con Node: `bun run dev:node` (Node 22+).

## Cómo está organizado

El código del servidor sigue **slices verticales con CQRS**: una carpeta por funcionalidad
en `src/lib/server/features/`, con `commands/` (cambian datos) y `queries/` (solo leen), un
archivo por caso de uso. Las rutas de SvelteKit solo llaman a un comando o una consulta. El
detalle está en [docs/arquitectura.md](docs/arquitectura.md).

## Convenciones

- **TypeScript estricto.** `bun run check` tiene que pasar sin errores ni warnings.
- **Tests de los parsers.** Cada adapter tiene su `<plataforma>.test.ts` que prueba el parseo
  contra los `fixtures/`, sin peticiones reales. `bun run test` tiene que pasar.
- **Identificadores en inglés; textos de la interfaz, comentarios y docs en español.**
- **Base de datos solo con Drizzle.** Si cambias `src/lib/server/db/schema.ts`, corre
  `bun run db:generate` e incluye la migración en el PR. No edites migraciones ya publicadas.
- **Los adapters solo traducen y filtran.** Nada de guardar en la base ni iniciar sesión
  desde un adapter. Usa siempre el cliente HTTP compartido (`ctx.client`).
- **Respeta a las plataformas.** Pausas generosas entre peticiones, sin login, sin cookies de
  cuentas. Un PR que haga muchas peticiones o use credenciales no se va a aceptar.
- **Nada personal en el repo.** `profile/` y `data/` están en `.gitignore`. Para pruebas usa
  `profile.example/` y los `fixtures/`.
- **Comentarios solo donde aportan:** el porqué, no el qué.

## Commits

Usamos [Conventional Commits](https://www.conventionalcommits.org/es/):

```
feat: integrar Computrabajo
fix: no descartar vacantes híbridas en la ciudad del perfil
docs: explicar el filtro de idioma
refactor: mover el cálculo de encaje a su propio slice
```

## Pull requests

1. Crea una rama desde `main` (`feat/computrabajo`, `fix/filtro-idioma`…).
2. Haz cambios pequeños y enfocados: un PR, un tema.
3. Verifica:
   - `bun run check` y `bun run test` pasan.
   - Probaste el cambio en la app (`bun run dev`) o con `bun run buscar` si toca la búsqueda.
   - Si agregaste una plataforma: una segunda búsqueda no trae duplicados y los filtros de
     ubicación e idioma funcionan.
4. Actualiza la documentación si cambia el comportamiento, y el [CHANGELOG](CHANGELOG.md)
   bajo "Sin publicar".
5. Abre el PR completando la plantilla.

## Código de conducta

Al participar aceptas el [Código de Conducta](CODE_OF_CONDUCT.md).
