# AGENTS.md

El contexto completo del proyecto está en **[CLAUDE.md](CLAUDE.md)**:
arquitectura, reglas de negocio, cambios hechos, pendientes y errores conocidos.

Lee ese archivo antes de tocar código.

## Lo mínimo antes de empezar

1. La fuente de verdad es GitHub (`HugoCamara7/catalogo-control-center`), no
   ninguna carpeta local. Descarga `app_matrixify.py` de `main` y compara el hash.
2. Los tickets viven en otro repositorio privado: `catalogo-control-center-data`.
3. `inject_custom_css` es un f-string: las llaves del CSS van dobladas.
4. `run_app()` captura las excepciones; una prueba debe mirar `at.error`.
5. El usuario sube los archivos a mano: entrega en ZIP con la estructura del repo.
