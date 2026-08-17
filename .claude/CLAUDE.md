# tiddl (ElVigilante Edition)

Fork de tiddl — descargador de música TIDAL production-ready.

## Stack
- Python 3.10+, Pydantic v1
- Config path: controlado por `TIDDL_PATH` (env var)

## Deploy en NAS
- Contenedor: `tiddl` en 192.168.68.55
- Ruta: `/volume1/docker/tiddl/`
- Config: `/volume1/docker/tiddl/config/`
- Descarga a: `/volume1/SERVER/Music`
- Scripts: `run_artists.sh` con `artist.txt` y `artist2.txt`
- Logs: `artist_run.log`, `artist2_run.log`

## Dockerfile en NAS
```
FROM python:3.12-slim + ffmpeg
TIDDL_PATH=/config
CMD tail -f /dev/null  (se controla con run_artists.sh externamente)
```

## Notas de desarrollo
- Fork de tiddl con optimizaciones de Pydantic v1
- CLI de autenticación y descarga de álbumes/tracks

## Convenciones
- **Código, comentarios, identificadores y mensajes de commit en inglés.** Las
  notas de release van **bilingües** (What's new / Novedades).
- Tests con `pytest`. CI en `.github/workflows/ci.yml` (matriz ubuntu+windows ×
  Python 3.10–3.13; ruff/mypy informativos, pytest+coverage, install desde el
  lock, `lock-drift`). Antes de proponer push: `pytest -q`, `ruff check`, y
  `compileall` en 3.10 (`uv run --python 3.10 --no-project -- python -m
  compileall -q tiddl`) y 3.13.
- Lockfile: `requirements.lock` (universal: `uv pip compile pyproject.toml
  --universal --python-version 3.10 -o requirements.lock`). Para comprobar drift,
  compila **IN-PLACE** sobre el archivo existente + `git diff` (uv preserva los
  pins; compilar a un archivo nuevo resuelve la última versión y marca falso drift).
- Instalar el fix en el CLI local tras merge (no es editable):
  `pip install --force-reinstall --no-deps "git+https://github.com/np3ir/tiddl-elvigilante.git@<commit>"`.

## Memoria del proyecto (auto-memory)

Este repo es su **propio proyecto de Claude Code** (ábrelo con `claude` desde su
carpeta). Su auto-memoria vive en:
`C:\Users\DJ Elvigilante\.claude\projects\G--My-Drive-Backups-zhome-2026-07-25-tiddl-elvigilante\memory\`

Actualiza la memoria **con frecuencia** (no solo al terminar): después de cada
cambio significativo o commit, de forma proactiva. Escribe en **dos** sitios:
1. `PROJECT_CONTEXT.md` en la raíz del repo — handoff portable detallado (está en
   `.gitignore`, no se sube).
2. La auto-memoria del proyecto — el archivo `.md` correspondiente **+ su línea en
   `MEMORY.md`** (una línea por memoria; nunca el contenido en `MEMORY.md`).

Ambos deben reflejar: estado (versión, rama/commit, PRs, CI), últimos cambios con
fecha (`YYYY-MM-DD`), problemas/tareas pendientes, y configuraciones clave.
