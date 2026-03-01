# 🎯 REFERENCIA COMPLETA - Comandos y Placeholders

**Guía exhaustiva para usar tiddl** | Explicado de forma sencilla

---

## 📋 Tabla de Contenidos

1. [Comandos Principales](#comandos-principales)
2. [Subcomandos de Download](#subcomandos-de-download)
3. [Opciones Globales](#opciones-globales)
4. [Opciones por Comando](#opciones-por-comando)
5. [Placeholders de Rutas](#placeholders-de-rutas)
6. [Ejemplos Prácticos](#ejemplos-prácticos)
7. [Casos de Uso Comunes](#casos-de-uso-comunes)

---

# 🎵 Comandos Principales

## 1. `tiddl auth` - Autenticación

Gestiona tu acceso a TIDAL.

### Subcomandos

#### **`tiddl auth login`**
Inicia sesión con tu cuenta de TIDAL.

```bash
tiddl auth login
```

**¿Qué hace?**
1. Abre navegador
2. Muestra código para ingreso
3. Espera a que ingreses el código en tidal.com
4. Guarda credenciales localmente

**Requisitos**: Ninguno, primera vez

---

#### **`tiddl auth logout`**
Cierra sesión.

```bash
tiddl auth logout
```

**¿Qué hace?**
- Elimina credenciales locales
- Invalida token en TIDAL

---

## 2. `tiddl download` - Descargar Contenido

Descarga música, videos, playlists, etc.

### 2.1 Descargar por URL: `tiddl download url`

Descarga contenido usando un enlace.

#### Sintaxis Básica
```bash
tiddl download url <URL>
```

#### URLs Soportadas

```bash
# Track (canción)
tiddl download url https://tidal.com/track/123456789

# Album
tiddl download url https://tidal.com/album/497662013

# Playlist
tiddl download url https://tidal.com/playlist/abc123xyz

# Artist (todos los álbumes)
tiddl download url https://tidal.com/artist/789123456

# Mix
tiddl download url https://tidal.com/mix/mixed123xyz
```

#### Opciones

```bash
# Calidad de audio
tiddl download url --track-quality max https://...     # 24-bit, 192kHz FLAC
tiddl download url --track-quality high https://...    # 16-bit, 44.1kHz FLAC
tiddl download url --track-quality normal https://...  # 320kbps AAC
tiddl download url --track-quality low https://...     # 96kbps AAC

# Calidad de video
tiddl download url --video-quality fhd https://...     # 1080p
tiddl download url --video-quality hd https://...      # 720p
tiddl download url --video-quality sd https://...      # 360p

# Ubicación de descarga
tiddl download url --path "D:/Music" https://...
tiddl download url -p "~/Music/Tidal" https://...

# No saltar archivos existentes (redescargar)
tiddl download url --no-skip https://...
tiddl download url -ns https://...

# Número de hilos de descarga
tiddl download url --threads-count 8 https://...
tiddl download url -t 4 https://...

# Reescribir metadatos
tiddl download url --rewrite-metadata https://...
tiddl download url -r https://...

# Naming template
tiddl download url --template "{album.artist}/{album.title}/{item.title}" https://...

# Debug
tiddl download url --debug https://...
```

---

### 2.2 Descargar Favoritos: `tiddl download fav`

Descarga todos tus favoritos de TIDAL.

```bash
tiddl download fav
```

**¿Qué hace?**
- Descarga todas las canciones marcadas como favorito
- Soporta todas las opciones de `download url`

**Ejemplo con opciones:**
```bash
tiddl download fav --track-quality max --threads-count 8
```

---

## 3. `tiddl info` - Información

Obtiene detalles sobre contenido sin descargar.

```bash
tiddl info url https://tidal.com/album/497662013
```

**Muestra:**
- Título
- Artista/Artistas
- Duración
- Bitrate disponible
- Fecha de lanzamiento
- Disponibilidad

---

## 4. `tiddl export` - Exportar Playlist

Guarda una playlist como archivo M3U8 (compatible con reproductores).

```bash
tiddl export url https://tidal.com/playlist/xyz -o my_playlist.m3u8
```

**Opciones:**
```bash
# Guardar en carpeta específica
tiddl export url https://... -o "D:/Playlists/playlist.m3u8"
tiddl export url https://... --output "~/Music/mi_playlist.m3u8"
```

---

# 🔄 Subcomandos de Download

## Estructura Completa

```
tiddl download
├── url          # Descargar por enlace
│   ├── https://tidal.com/track/...
│   ├── https://tidal.com/album/...
│   ├── https://tidal.com/playlist/...
│   └── https://tidal.com/artist/...
└── fav          # Descargar favoritos
```

---

# ⚙️ Opciones Globales

Estas opciones funcionan con **TODOS** los comandos:

```bash
# Mostrar versión
tiddl --version
tiddl -v

# Mostrar ayuda
tiddl --help
tiddl -h

# Debug (guarda logs detallados)
tiddl --debug <comando>

# Omitir cache
tiddl --omit-cache <comando>
```

---

# 📋 Opciones por Comando

## Download Command Options

| Opción | Corto | Tipo | Defecto | Descripción |
|--------|-------|------|---------|-------------|
| `--track-quality` | `-q` | low/normal/high/max | high | Calidad de audio |
| `--video-quality` | `-vq` | sd/hd/fhd | fhd | Calidad de video |
| `--no-skip` | `-ns` | bool | false | NO saltar archivos existentes |
| `--rewrite-metadata` | `-r` | bool | false | Reescribir metadatos existentes |
| `--threads-count` | `-t` | 1-20 | 4 | Número de descargas simultáneas |
| `--path` | `-p` | ruta | ~/Music/tiddl | Carpeta de descarga |
| `--template` | - | string | config | Naming template |
| `--scan-path` | `--sp` | ruta | igual a path | Carpeta para escanear existentes |
| `--debug` | - | bool | false | Guardar logs de API |

---

# 🎨 Placeholders de Rutas

Los "placeholders" son variables que se reemplazan automáticamente con información real.

## Placeholders de Item (Canción/Video)

```bash
{item.id}                      # ID de la canción
                               # Ejemplo: 123456789

{item.title}                   # Título de la canción
                               # Ejemplo: "Song Name"

{item.title_version}           # Título con versión
                               # Ejemplo: "Song Name (Remix)"

{item.number}                  # Número de pista
                               # Ejemplo: 1, 2, 3

{item.volume}                  # Número de volumen/disco
                               # Ejemplo: 1, 2

{item.version}                 # Versión extendida
                               # Ejemplo: "(Remix)", "(Acoustic)"

{item.artist}                  # Artista principal
                               # Ejemplo: "The Beatles"

{item.safe_artist}             # Artista con caracteres seguros
                               # (sin caracteres especiales)

{item.artists}                 # Todos los artistas
                               # Ejemplo: "Artist1, Artist2"

{item.safe_artists}            # Artistas con caracteres seguros

{item.features}                # Solo artistas featuring
                               # Ejemplo: "Artist3, Artist4"

{item.artists_with_features}   # Artistas + featuring
                               # Ejemplo: "Artist1 feat. Artist2"

{item.explicit}                # Indicador de explícito
                               # Ejemplo: "[E]" si es explícito

{item.genre}                   # Género
                               # Ejemplo: "Pop", "Hip-Hop"

{item.copyright}               # Información de copyright

{item.bpm}                     # BPM (beats per minute)
                               # Ejemplo: 120

{item.isrc}                    # ISRC code

{item.quality}                 # Calidad descargada
                               # Ejemplo: "FLAC", "AAC"

{item.releaseDate}             # Fecha de lanzamiento
                               # Ver formato de fechas abajo

{item.streamStartDate}         # Fecha de disponibilidad
                               # Ver formato de fechas abajo

{item.dolby}                   # Atmos Dolby (si está disponible)
```

---

## Placeholders de Album

```bash
{album.id}                     # ID del álbum
                               # Ejemplo: 497662013

{album.title}                  # Nombre del álbum
                               # Ejemplo: "Album Name"

{album.safe_title}             # Título con caracteres seguros

{album.artist}                 # Artista del álbum
                               # Ejemplo: "The Beatles"

{album.safe_artist}            # Artista con caracteres seguros

{album.artists}                # Todos los artistas del álbum

{album.safe_artists}           # Artistas con caracteres seguros

{album.date}                   # Fecha de lanzamiento
                               # Ejemplo: 2023-01-15
                               # Ver formato de fechas abajo

{album.explicit}               # Indicador de explícito

{album.master}                 # Si es Master Quality
                               # (muestra nada si no, "Master" si sí)

{album.release}                # Tipo de lanzamiento
                               # Ejemplo: "ALBUM", "SINGLE", "EP"
```

---

## Placeholders de Playlist

```bash
{playlist.uuid}                # ID único de la playlist
                               # Ejemplo: "abc123xyz"

{playlist.title}               # Nombre de la playlist
                               # Ejemplo: "Mi Playlist"

{playlist.index}               # Número de pista en playlist
                               # Ejemplo: 1, 2, 3

{playlist.created}             # Fecha de creación
                               # Ver formato de fechas abajo

{playlist.updated}             # Última actualización
                               # Ver formato de fechas abajo
```

---

## Placeholders de Carpeta/Artista

```bash
{artist_initials}              # Letra inicial del artista
                               # Ejemplo: "T" para "The Beatles"
                               # Agrupa por letra

{album.artist}                 # Igual que album.artist
```

---

## Formato de Fechas

Las fechas se pueden formatear de muchas formas:

```bash
# Formato básico (ISO)
{item.releaseDate}             # 2023-01-15

# Año solo
{item.releaseDate:%Y}          # 2023

# Año-mes
{item.releaseDate:%Y-%m}       # 2023-01

# Año-mes-día
{item.releaseDate:%Y-%m-%d}    # 2023-01-15

# Nombre del mes
{item.releaseDate:%B}          # January

# Mes corto
{item.releaseDate:%b}          # Jan

# Día
{item.releaseDate:%d}          # 15

# Formato americano
{item.releaseDate:%m/%d/%Y}    # 01/15/2023

# Formato europeo
{item.releaseDate:%d/%m/%Y}    # 15/01/2023

# Hora y minutos
{item.releaseDate:%Y-%m-%d %H:%M}  # 2023-01-15 14:30

# Custom - Puedes combinar
{item.releaseDate:%A, %B %d, %Y}   # Sunday, January 15, 2023
```

---

## Otras Variables

```bash
{quality}                      # Calidad de descarga
                               # Ejemplo: "max", "high"

{now}                          # Fecha y hora actual
                               # Ejemplo: 2026-03-01
                               # Se puede formatear como fechas

{now:%Y}                       # Año actual
{now:%Y-%m-%d}                 # Fecha actual
{now:%H-%M}                    # Hora actual
```

---

# 💡 Ejemplos Prácticos

## Ejemplo 1: Estructura Simple

```bash
# Config: default = "{album.artist}/{album.title}/{item.title}"

# Resultado:
The Beatles/Abbey Road/Come Together.flac
The Beatles/Abbey Road/Maxwell's Silver Hammer.flac
The Beatles/Abbey Road/Oh! Darling.flac
```

---

## Ejemplo 2: Con Número de Pista

```bash
# Template: "{album.artist}/{album.title}/{item.number}. {item.title}"

# Resultado:
The Beatles/Abbey Road/01. Come Together.flac
The Beatles/Abbey Road/02. Maxwell's Silver Hammer.flac
The Beatles/Abbey Road/03. Oh! Darling.flac
```

---

## Ejemplo 3: Con Año del Álbum

```bash
# Template: "{album.artist}/({album.date:%Y}) {album.title}/{item.number}. {item.title}"

# Resultado:
The Beatles/(1969) Abbey Road/01. Come Together.flac
The Beatles/(1969) Abbey Road/02. Maxwell's Silver Hammer.flac
The Beatles/(1969) Abbey Road/03. Oh! Darling.flac
```

---

## Ejemplo 4: Con Artista Initial (Agrupa por Letra)

```bash
# Template: "{artist_initials}/{album.artist}/{album.title}/{item.title}"

# Resultado:
T/The Beatles/Abbey Road/Come Together.flac
T/The Beatles/Abbey Road/Maxwell's Silver Hammer.flac
D/Drake/Certified Lover Boy/Champagne Poetry.flac
D/Drake/Certified Lover Boy/In the Cut.flac
```

---

## Ejemplo 5: Con Feature Artists

```bash
# Template: "{album.artist}/{album.title}/{item.number}. {item.artists_with_features}"

# Resultado:
Drake/Certified Lover Boy/01. Drake feat. 21 Savage.flac
Drake/Certified Lover Boy/02. Drake feat. Giveon.flac
Drake/Certified Lover Boy/03. Drake.flac
```

---

## Ejemplo 6: Con Versión (Remix, Acoustic)

```bash
# Template: "{album.artist}/{album.title}/{item.number}. {item.title} {item.version}"

# Resultado:
The Weeknd/Dawn FM/01. Gasoline (Remix).flac
The Weeknd/Dawn FM/02. Take My Breath (Extended).flac
The Weeknd/Dawn FM/03. Sacrifice (Acoustic).flac
```

---

## Ejemplo 7: Sin Carpeta de Álbum

```bash
# Template: "{album.artist}/{item.title}"

# Resultado:
The Beatles/Come Together.flac
The Beatles/Maxwell's Silver Hammer.flac
Drake/Champagne Poetry.flac
Drake/In the Cut.flac
```

---

## Ejemplo 8: Todos los Artistas

```bash
# Template: "{album.artists}/{album.title}/{item.number}. {item.title}"

# Resultado (si hay varios artistas del álbum):
The Beatles, Yoko Ono/Abbey Road/01. Come Together.flac
```

---

# 🎯 Casos de Uso Comunes

## Caso 1: "Tengo espacio limitado"

```bash
tiddl download url https://... \
  --track-quality normal \
  --threads-count 2
```

**Explica:**
- `normal` = 320kbps (mucho menos que FLAC)
- Menos hilos = uso menor de ancho de banda y RAM

---

## Caso 2: "Quiero máxima calidad"

```bash
tiddl download url https://tidal.com/album/497662013 \
  --track-quality max \
  --path "D:/HighQuality"
```

**Explica:**
- `max` = 24-bit, 192kHz FLAC (mejor calidad)
- Carpeta separada para organizarlos

---

## Caso 3: "Quiero que se organice por año"

En `config.toml`:
```toml
[templates]
default = "{album.artist}/({album.date:%Y}) {album.title}/{item.number}. {item.title}"
```

```bash
tiddl download url https://...
```

**Resultado:**
```
Adele/(2008) 21/01. Rolling in the Deep.flac
Adele/(2015) 25/01. Hello.flac
Adele/(2019) 30/01. Easy On Me.flac
```

---

## Caso 4: "Cambiar rápidamente la carpeta"

```bash
tiddl download url https://... --path "E:/Backup"
```

No necesitas editar config.toml, el flag lo sobrescribe.

---

## Caso 5: "No quiero re-descargar"

```bash
# Mantén skip_existing = true en config.toml (por defecto)
tiddl download url https://...

# O usa el flag
tiddl download url https://... --no-skip   # REESCRIBE TODO
```

---

## Caso 6: "Descargar album completo rápido"

```bash
tiddl download url https://tidal.com/album/497662013 \
  --track-quality high \
  --threads-count 8
```

**Explica:**
- `high` = Buena calidad sin ser excesivo
- 8 hilos = máxima velocidad

---

## Caso 7: "Reescribir metadatos desactualizados"

```bash
tiddl download url https://... \
  --rewrite-metadata \
  --no-skip
```

---

## Caso 8: "Descargar todo con naming customizado"

En `config.toml`:
```toml
[templates]
default = "{album.artist} - ({album.date:%Y}) {album.title}/{item.number:02d} - {item.title}"
```

```bash
tiddl download fav
```

---

# 🔧 Troubleshooting

## "¿Qué es el --debug?"

```bash
tiddl download url https://... --debug
```

Crea logs detallados en `~/.tiddl/api_debug/`

**Úsalo si:**
- Descarga falla
- Quieres ver qué hace la app
- Tienes problemas de red

---

## "¿Por qué algunos placeholders no funcionan?"

```bash
# ❌ Esto falla:
{item.unknown_field}

# ✅ Usa placeholders válidos:
{item.title}
{album.artist}
{item.releaseDate:%Y}
```

---

## "¿Cómo hago paths de red?"

```bash
# Windows red UNC
--path "//servidor/compartido/Música"

# O así:
--path "\\\\servidor\\compartido\\Música"
```

---

# 📚 Referencia Rápida

```bash
# AUTENTICACIÓN
tiddl auth login
tiddl auth logout

# DESCARGAR
tiddl download url https://tidal.com/album/123      # Por URL
tiddl download fav                                    # Favoritos

# INFORMACIÓN
tiddl info url https://tidal.com/album/123

# EXPORTAR
tiddl export url https://tidal.com/playlist/xyz -o file.m3u8

# OPCIONES COMUNES
--track-quality max                                   # Máxima calidad
--path "D:/Música"                                    # Carpeta
--threads-count 8                                     # Velocidad
--no-skip                                             # Redescargar
--template "{artist}/{album}/{title}"                # Naming
--debug                                               # Logs

# VARIABLES PRINCIPALES
{item.title}                                          # Canción
{album.artist}                                        # Artista
{album.title}                                         # Álbum
{album.date:%Y}                                       # Año
{item.number}                                         # Pista #
{item.artists_with_features}                         # Feat artists
```

---

**Fin de la Referencia Completa** 🎉

Todos los comandos son simples de entender si sigues estos ejemplos.

¡Ahora estás listo para usar tiddl! 🚀

