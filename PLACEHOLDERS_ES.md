# Placeholders de plantillas de tiddl-elvigilante

> [English version](PLACEHOLDERS.md)

Referencia extraída del código actual de `tiddl-elvigilante`, principalmente de `tiddl/core/utils/format.py` y de las variables adicionales proporcionadas por los comandos de descarga.

Los placeholders se escriben entre llaves dentro de una plantilla:

```toml
[templates]
default = "{album.artist}/{album.title}/{item.number:02}. {item.title}"
```

Usa `/` para separar carpetas, incluso en Windows. tiddl convierte y sanea la ruta para el sistema de archivos.

## Track o video — `{item.*}`

| Placeholder | Descripción |
|---|---|
| `{item.id}` | ID del track o video en TIDAL. |
| `{item.title}` | Título limpio, sin la versión añadida. |
| `{item.safe_title}` | Título saneado para utilizarse en nombres de archivos. |
| `{item.title_version}` | Título más la versión entre paréntesis, por ejemplo `Song (Remastered 2011)`. |
| `{item.number}` | Número de pista. Admite relleno con ceros, por ejemplo `{item.number:02}`. |
| `{item.volume}` | Número de disco o volumen. |
| `{item.version}` | Texto crudo de la versión, por ejemplo `Remastered 2011`; no incluye automáticamente paréntesis. |
| `{item.copyright}` | Texto de copyright. |
| `{item.bpm}` | Pulsaciones por minuto. |
| `{item.isrc}` | Código ISRC. |
| `{item.quality}` | Calidad suministrada al formateador para este item. |
| `{item.artist}` | Artista principal. |
| `{item.safe_artist}` | Artista principal saneado para el sistema de archivos. |
| `{item.artists}` | Artistas principales unidos con `artist_separator`. |
| `{item.safe_artists}` | Artistas principales unidos y saneados para el sistema de archivos. |
| `{item.features}` | Artistas invitados o featured unidos con `artist_separator`. |
| `{item.artists_with_features}` | Artistas principales e invitados unidos con `artist_separator`. |
| `{item.explicit}` | Indicador de contenido explícito. Admite los modificadores descritos más abajo. |
| `{item.genre}` | Género obtenido del álbum del item. |
| `{item.dolby}` | Valor condicional para Dolby Atmos. Solo imprime el texto indicado como formato si el item es Atmos. |
| `{item.releaseDate}` | Fecha de publicación. Admite formatos `strftime`. |
| `{item.streamStartDate}` | Fecha de inicio de disponibilidad. Admite formatos `strftime`. |

Los nombres de artistas visibles en rutas están limitados a los tres primeros; si existen más, tiddl añade `& others`. Los tags internos conservan la información completa.

## Álbum — `{album.*}`

| Placeholder | Descripción |
|---|---|
| `{album.id}` | ID del álbum en TIDAL. |
| `{album.title}` | Título del álbum. |
| `{album.safe_title}` | Título del álbum saneado para el sistema de archivos. |
| `{album.artist}` | Artista principal del álbum. |
| `{album.safe_artist}` | Artista principal saneado para el sistema de archivos. |
| `{album.artists}` | Artistas principales del álbum unidos con `artist_separator`. |
| `{album.safe_artists}` | Artistas principales unidos y saneados. |
| `{album.date}` | Fecha de publicación del álbum. Admite formatos `strftime`. |
| `{album.explicit}` | Indicador de contenido explícito. Admite los mismos modificadores que `{item.explicit}`. |
| `{album.master}` | Valor condicional de calidad Master/HiRes. Imprime el texto indicado solo cuando aplica. |
| `{album.release}` | Tipo de lanzamiento, normalmente `ALBUM`, `SINGLE` o `EP`. |

Cuando un video u otro item no trae álbum, tiddl construye un álbum de respaldo: usa el título y artista del item, establece `{album.id}` en `0`, `{album.release}` en `SINGLE` y deja `{album.master}` desactivado.

## Playlist — `{playlist.*}`

| Placeholder | Descripción |
|---|---|
| `{playlist.uuid}` | UUID de la playlist. |
| `{playlist.title}` | Título de la playlist. |
| `{playlist.index}` | Posición del item dentro de la playlist. |
| `{playlist.created}` | Fecha de creación. Admite formatos `strftime`. |
| `{playlist.updated}` | Fecha de última actualización. Admite formatos `strftime`. |

## Alias globales sin prefijo

| Placeholder | Descripción y disponibilidad |
|---|---|
| `{title}` | Alias de `{item.title}`. Solo existe cuando hay un item. |
| `{artist}` | Alias de `{item.artist}`. Solo existe cuando hay un item. |
| `{albumartist}` | Alias de `{album.artist}`. Solo existe cuando hay un álbum. |
| `{artist_initials}` | Letra o categoría inicial del artista. Con álbum, tiddl prefiere el artista del álbum; de lo contrario usa el artista del item. |
| `{release_date}` | Alias de `{album.date}`. Solo existe cuando hay un álbum. |
| `{quality}` | Calidad pasada al formateador, por ejemplo `MAX`, `HIGH` u otro valor del flujo de descarga. |
| `{now}` | Fecha y hora actuales. Admite formatos `strftime`. |

## Variables contextuales

Estas variables no están disponibles en todas las plantillas; el comando de descarga las proporciona únicamente en contextos específicos.

| Placeholder | Dónde está disponible | Descripción |
|---|---|---|
| `{mix_id}` | Plantillas de mix y M3U de mix | ID del mix. |
| `{type}` | Plantillas M3U de álbum, playlist o mix | Tipo del recurso: `album`, `playlist` o `mix`. |

## Formatos de fecha y hora

Los campos de fecha son objetos `datetime`, por lo que aceptan los códigos estándar de `strftime`:

| Ejemplo | Resultado aproximado |
|---|---|
| `{item.releaseDate}` | `2024-03-15 00:00:00` |
| `{item.releaseDate:%Y}` | `2024` |
| `{item.releaseDate:%Y-%m}` | `2024-03` |
| `{item.releaseDate:%Y-%m-%d}` | `2024-03-15` |
| `{album.date:%B}` | `March` |
| `{playlist.created:%d-%m-%Y}` | `15-03-2024` |
| `{now:%Y-%m-%d}` | Fecha actual. |
| `{now:%H-%M}` | Hora y minuto actuales. |

También pueden utilizarse, entre otros, `%d` (día), `%m` (mes), `%b` (mes abreviado), `%B` (nombre del mes), `%A` (día de la semana), `%H` (hora), `%M` (minuto) y `%S` (segundo).

Una fecha ausente o inválida se convierte internamente en `datetime.min`; por eso conviene comprobar el resultado antes de usar fechas de fuentes incompletas en nombres definitivos.

## Formato de números

Los números utilizan el minilenguaje estándar de formato de Python:

```toml
track = "{album.artist}/{album.title}/{item.number:02}. {item.title}"
```

Ejemplos:

| Placeholder | Valor 5 | Resultado |
|---|---:|---:|
| `{item.number}` | 5 | `5` |
| `{item.number:02}` | 5 | `05` |
| `{item.number:03}` | 5 | `005` |
| `{playlist.index:02}` | 5 | `05` |

## Modificadores de contenido explícito

Si el item o álbum no es explícito, todos estos formatos producen una cadena vacía.

| Placeholder | Resultado cuando es explícito |
|---|---|
| `{item.explicit}` | `E` |
| `{item.explicit:upper}` | `E` |
| `{item.explicit:long}` | `explicit` |
| `{item.explicit:upperlong}` | `EXPLICIT` |
| `{item.explicit:parens}` | ` (Explicit)` |
| `{item.explicit:shortparens}` | ` (explicit)` |

Los mismos modificadores funcionan con `{album.explicit}`.

Ejemplo:

```toml
track = "{item.number:02}. {item.title}{item.explicit:parens}"
```

Resultado: `01. Song Name (Explicit)` o `01. Song Name`.

## Texto condicional para Master y Dolby Atmos

`{album.master}` y `{item.dolby}` son valores condicionales. El texto escrito después de `:` aparece únicamente cuando la condición es verdadera:

```toml
track = "{item.title} {album.master:MQA}{item.dolby:Dolby Atmos}"
```

| Placeholder | Condición verdadera | Condición falsa |
|---|---|---|
| `{album.master:HiRes}` | `HiRes` | cadena vacía |
| `{album.master:[MASTER]}` | `[MASTER]` | cadena vacía |
| `{item.dolby:Atmos}` | `Atmos` | cadena vacía |
| `{item.dolby:[DOLBY ATMOS]}` | `[DOLBY ATMOS]` | cadena vacía |

Sin texto de formato, `{album.master}` y `{item.dolby}` producen una cadena vacía incluso cuando la condición es verdadera. Por eso deben usarse normalmente con `:texto`.

## Separador de artistas

El valor se configura en `config.toml`:

```toml
[templates]
artist_separator = " / "
```

Afecta a:

- `{item.artists}`
- `{item.safe_artists}`
- `{item.features}`
- `{item.artists_with_features}`
- `{album.artists}`
- `{album.safe_artists}`
- tags de artistas escritos en los archivos multimedia

Valores comunes: `" / "`, `", "`, `" & "` y `"; "`.

## Dónde se configuran las plantillas

```toml
[templates]
default = "{album.artist}/{album.title}/{item.title}"
track = ""
video = ""
album = ""
playlist = ""
mix = ""
artist_separator = " / "
```

Los campos vacíos `track`, `video`, `album`, `playlist` y `mix` heredan de `default`.

Las plantillas también se reutilizan para portadas y M3U:

```toml
[cover.templates]
track = ""
album = ""
playlist = ""

[m3u.templates]
album = ""
playlist = ""
mix = ""
```

La disponibilidad de cada placeholder depende de los objetos entregados al formateador. Por ejemplo, una plantilla M3U de mix recibe `{mix_id}` y `{type}`, pero no necesariamente `{item.*}` o `{album.*}`.

## Ejemplos completos

### Biblioteca por inicial, artista y año

```toml
[templates]
default = "{artist_initials}/{album.artist}/({album.date:%Y}) {album.title}/{item.number:02}. {item.title}"
```

```text
B/The Beatles/(1969) Abbey Road/01. Come Together.flac
```

### Artistas invitados y contenido explícito

```toml
[templates]
track = "{album.artist}/{album.title}/{item.number:02}. {item.artists_with_features} - {item.title}{item.explicit:parens}"
```

### Playlist ordenada

```toml
[templates]
playlist = "Playlists/{playlist.title}/{playlist.index:03}. {item.artist} - {item.title}"
```

### Mix

```toml
[templates]
mix = "Mixes/{mix_id}/{item.artist} - {item.title}"

[m3u.templates]
mix = "Mixes/{mix_id}/{type}-{mix_id}"
```

### Indicadores condicionales de calidad

```toml
[templates]
album = "{album.artist}/{album.title} {album.master:[HIRES]}/{item.number:02}. {item.title}{item.dolby: [ATMOS]}"
```

## Resumen: todos los placeholders

```text
{item.id}
{item.title}
{item.safe_title}
{item.title_version}
{item.number}
{item.volume}
{item.version}
{item.copyright}
{item.bpm}
{item.isrc}
{item.quality}
{item.artist}
{item.safe_artist}
{item.artists}
{item.safe_artists}
{item.features}
{item.artists_with_features}
{item.explicit}
{item.genre}
{item.dolby}
{item.releaseDate}
{item.streamStartDate}

{album.id}
{album.title}
{album.safe_title}
{album.artist}
{album.safe_artist}
{album.artists}
{album.safe_artists}
{album.date}
{album.explicit}
{album.master}
{album.release}

{playlist.uuid}
{playlist.title}
{playlist.index}
{playlist.created}
{playlist.updated}

{title}
{artist}
{albumartist}
{artist_initials}
{release_date}
{quality}
{now}

{mix_id}
{type}
```

## Observaciones técnicas

- Si una plantilla contiene un placeholder inexistente o incompatible con el contexto, tiddl no siempre genera un error: el segmento puede convertirse en texto saneado. Es preferible probar una plantilla nueva con una descarga pequeña.
- Si un álbum tiene varios discos y la plantilla no contiene `{item.volume}`, tiddl inserta automáticamente una carpeta `Disc N` antes del nombre del archivo.
- Los nombres se normalizan en Unicode NFC y se sanean para eliminar caracteres incompatibles con el sistema de archivos.
- Cada componente de ruta se limita a 255 bytes. El último componente reserva espacio para la extensión.
- `{item.safe_title}`, `{item.safe_artist}`, `{item.safe_artists}`, `{album.safe_title}`, `{album.safe_artist}` y `{album.safe_artists}` son útiles cuando se desea controlar explícitamente qué partes quedan saneadas, aunque la ruta final completa también pasa por saneamiento.
