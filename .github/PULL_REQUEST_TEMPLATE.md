## Qué cambia

<!-- Qué hace este PR y por qué. Si cierra un issue: "Cierra #123". -->

## Cómo lo probé

<!-- Pasos para verificarlo: búsqueda, página, capturas si es visual. -->

## Checklist

- [ ] `bun run check` pasa sin errores ni warnings
- [ ] `bun run test` pasa (y si toqué un parser, agregué o actualicé sus tests y fixtures)
- [ ] Lo probé en la app (`bun run dev`) o con `bun run buscar`
- [ ] Si cambié el esquema: incluí la migración de `bun run db:generate`
- [ ] Si agregué una plataforma: sin login, con pausas entre peticiones, una segunda búsqueda no duplica y respeta ubicación e idioma
- [ ] Actualicé la documentación y el `CHANGELOG.md` (sección "Sin publicar")
- [ ] No incluí nada de `profile/` ni `data/`
