# Política de seguridad

## Versiones con soporte

JobFilter está en desarrollo activo. Solo la última versión de `main` recibe correcciones de
seguridad.

## Reportar una vulnerabilidad

**No abras un issue público.** Repórtala en privado por una de estas vías:

- La pestaña **Security → Report a vulnerability** de este repositorio (reporte privado de
  GitHub).
- Un correo a **contacto@asprino.dev** con el asunto `[JobFilter] Vulnerabilidad`.

Incluye qué encontraste, cómo reproducirlo y qué impacto puede tener. Vas a recibir una
respuesta en un plazo de 7 días; cuando esté corregida, se publicará el arreglo y, si quieres,
se te dará crédito.

## Alcance

JobFilter corre en tu máquina, sin cuentas ni servidor público. Interesan especialmente:

- Ejecución de código o lectura de archivos a partir de contenido de una vacante (HTML o
  JSON que devuelve una plataforma).
- Que la app quede expuesta en la red local sin que el usuario lo pida.
- Filtración de datos de `profile/` o `data/`.

Que una plataforma bloquee las peticiones no es una vulnerabilidad: abre un issue normal.
