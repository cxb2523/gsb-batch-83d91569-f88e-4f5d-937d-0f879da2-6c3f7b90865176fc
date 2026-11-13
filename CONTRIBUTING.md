# Contribuir

Gracias por el interés en contribuir a RetroAchievements Downloader. Esta
guía resume cómo está organizado el flujo de trabajo del repo.

## Flujo de ramas

- La rama de integración es **`dev`**, no `main`. Todas las ramas de trabajo
  salen de `dev` y hacen Pull Request hacia `dev`.
- `main` se actualiza solo cuando se corta un release con cambios ya
  probados en `dev` — no abras PRs directamente contra `main`.

```bash
git checkout dev
git pull
git checkout -b tipo/nombre-descriptivo
# ... tus cambios ...
git push origin tipo/nombre-descriptivo
# abrí el PR con base dev
```

## Mensajes de commit

Formato [Conventional Commits](https://www.conventionalcommits.org/):
`tipo(scope): descripción`.

Tipos usados en este repo: `feat`, `fix`, `refactor`, `docs`, `chore`,
`test`, `ci`. Ejemplos reales:

```
feat(metadata): actualizar la metada wii-gamecube
fix(mobile): corregir overflow del buscador
ci: agregar workflow de lint + typecheck + build
```

## Antes de abrir el PR

```bash
pip install -r requirements-dev.txt   # Python
npm install && npm install --prefix web  # Node

pytest                                 # tests de Python
npm run lint --prefix web              # ESLint
npm run test --prefix web              # Vitest
npm run build --prefix web             # build de producción
```

El CI corre estos mismos chequeos en cada PR — si algo de esto falla
localmente, también va a fallar ahí.

## Ideas para contribuir

- 🆕 Agregar soporte para nuevas consolas (ver `src/factories/url_factory.py`
  y `src/core/rom_info.py`).
- 🔧 Mejorar la interfaz de usuario (`web/`).
- 🐛 Reportar y corregir bugs.
- 📚 Mejorar documentación.

Para reportar una vulnerabilidad de seguridad (no un bug común), seguí
[SECURITY.md](SECURITY.md) en vez de abrir un issue público.
