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
