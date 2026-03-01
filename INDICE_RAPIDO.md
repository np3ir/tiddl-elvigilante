# 📚 ÍNDICE RÁPIDO - Qué contiene la Referencia Completa

## 📄 Archivo: `REFERENCIA_COMPLETA_COMANDOS_PLACEHOLDERS.md`

**Tamaño**: 17 KB | **Líneas**: 734 | **Formato**: 100% Markdown

---

## 🎯 Contenido del Documento

### 1️⃣ COMANDOS PRINCIPALES (Explicados para cualquier persona)

```
✅ tiddl auth          - Autenticación
   ├── login           - Inicia sesión
   └── logout          - Cierra sesión

✅ tiddl download      - Descargar
   ├── url             - Descargar por enlace
   └── fav             - Descargar favoritos

✅ tiddl info          - Obtener información

✅ tiddl export        - Exportar a M3U8
```

**Cada comando incluye:**
- Sintaxis exacta
- Qué hace explicado en palabras simples
- Ejemplos de uso real
- Requisitos

---

### 2️⃣ URLS SOPORTADAS

```bash
tiddl download url https://tidal.com/track/123456789      ✓
tiddl download url https://tidal.com/album/497662013      ✓
tiddl download url https://tidal.com/playlist/abc123xyz   ✓
tiddl download url https://tidal.com/artist/789123456     ✓
tiddl download url https://tidal.com/mix/mixed123xyz      ✓
```

---

### 3️⃣ TODAS LAS OPCIONES (16 opciones documentadas)

| Opción | Corto | Ejemplo | Explicación |
|--------|-------|---------|-------------|
| `--track-quality` | `-q` | `max`, `high`, `normal`, `low` | Calidad de audio |
| `--video-quality` | `-vq` | `fhd`, `hd`, `sd` | Calidad de video |
| `--no-skip` | `-ns` | - | Redescargar archivos |
| `--rewrite-metadata` | `-r` | - | Actualizar metadatos |
| `--threads-count` | `-t` | `8` | Hilos de descarga |
| `--path` | `-p` | `D:/Music` | Carpeta destino |
| `--template` | - | `{artist}/{album}/{title}` | Naming personalizado |
| Y muchas más... | | | |

---

### 4️⃣ PLACEHOLDERS - TODOS EXPLICADOS

#### **Para Canciones (item)**
```
{item.id}                      → 123456789
{item.title}                   → "Come Together"
{item.number}                  → 1, 2, 3...
{item.artist}                  → "The Beatles"
{item.artists_with_features}   → "Artist feat. Guest"
{item.releaseDate:%Y}          → 1969
{item.explicit}                → [E] si es explícito
```

#### **Para Álbumes (album)**
```
{album.id}                     → 497662013
{album.title}                  → "Abbey Road"
{album.artist}                 → "The Beatles"
{album.date:%Y}                → 1969
{album.release}                → "ALBUM", "SINGLE", "EP"
{album.master}                 → "Master" si es calidad master
```

#### **Para Playlists (playlist)**
```
{playlist.title}               → "Mi Playlist"
{playlist.uuid}                → abc123xyz
{playlist.index}               → 1, 2, 3...
{playlist.created}             → Fecha creación
{playlist.updated}             → Última actualización
```

#### **Especiales**
```
{artist_initials}              → "T" (agrupa por letra)
{now:%Y}                       → 2026 (año actual)
{quality}                      → "max", "high"...
```

---

### 5️⃣ FORMATO DE FECHAS (13 variantes)

```bash
{album.date}                   # 2023-01-15 (ISO)
{album.date:%Y}                # 2023 (año)
{album.date:%Y-%m-%d}          # 2023-01-15 (completa)
{album.date:%B}                # January (mes completo)
{album.date:%b}                # Jan (mes corto)
{album.date:%d}                # 15 (día)
{album.date:%m/%d/%Y}          # 01/15/2023 (americano)
{album.date:%d/%m/%Y}          # 15/01/2023 (europeo)
{album.date:%Y-%m-%d %H:%M}    # 2023-01-15 14:30 (con hora)
{album.date:%A, %B %d, %Y}     # Sunday, January 15, 2023 (descriptivo)
```

---

### 6️⃣ EJEMPLOS PRÁCTICOS (8 Ejemplos Reales)

```bash
# Ejemplo 1: Simple
{album.artist}/{album.title}/{item.title}
→ The Beatles/Abbey Road/Come Together.flac

# Ejemplo 2: Con número
{album.artist}/{album.title}/{item.number}. {item.title}
→ The Beatles/Abbey Road/01. Come Together.flac

# Ejemplo 3: Con año
{album.artist}/({album.date:%Y}) {album.title}/{item.number}. {item.title}
→ The Beatles/(1969) Abbey Road/01. Come Together.flac

# Ejemplo 4: Agrupa por letra
{artist_initials}/{album.artist}/{album.title}/{item.title}
→ T/The Beatles/Abbey Road/Come Together.flac

# Ejemplo 5: Con featuring artists
{album.artist}/{album.title}/{item.number}. {item.artists_with_features}
→ Drake/Certified Lover Boy/01. Drake feat. 21 Savage.flac

# Ejemplo 6: Con versión
{album.artist}/{album.title}/{item.number}. {item.title} {item.version}
→ The Weeknd/Dawn FM/01. Gasoline (Remix).flac

# Ejemplo 7: Solo artista
{album.artist}/{item.title}
→ The Beatles/Come Together.flac

# Ejemplo 8: Todos los artistas
{album.artists}/{album.title}/{item.number}. {item.title}
→ The Beatles, Yoko Ono/Abbey Road/01. Come Together.flac
```

---

### 7️⃣ CASOS DE USO COMUNES (8 Casos)

```bash
1. "Tengo poco espacio"
   → --track-quality normal --threads-count 2

2. "Quiero máxima calidad"
   → --track-quality max --path "D:/HighQuality"

3. "Quiero organizar por año"
   → Config: {album.date:%Y}/{album.artist}/{album.title}/{item.title}

4. "Cambiar carpeta rápido"
   → --path "E:/Backup"

5. "No redescargar"
   → Usa skip_existing = true (por defecto)

6. "Descargar rápido"
   → --track-quality high --threads-count 8

7. "Actualizar metadatos"
   → --rewrite-metadata --no-skip

8. "Naming personalizado"
   → --template "{artist}/{title}"
```

---

### 8️⃣ TROUBLESHOOTING

- ¿Qué es --debug?
- ¿Por qué algunos placeholders no funcionan?
- ¿Cómo hago paths de red?

---

### 9️⃣ REFERENCIA RÁPIDA (Copia y Pega)

```bash
# AUTENTICACIÓN
tiddl auth login
tiddl auth logout

# DESCARGAR
tiddl download url https://tidal.com/album/123
tiddl download fav

# INFORMACIÓN
tiddl info url https://tidal.com/album/123

# EXPORTAR
tiddl export url https://tidal.com/playlist/xyz -o file.m3u8

# OPCIONES
--track-quality max
--path "D:/Música"
--threads-count 8
--template "{artist}/{album}/{title}"

# VARIABLES
{item.title}
{album.artist}
{album.date:%Y}
{item.number}
```

---

## 📊 Estadísticas del Documento

| Métrica | Valor |
|---------|-------|
| Líneas | 734 |
| Tamaño | 17 KB |
| Comandos explicados | 4 principales |
| Subcomandos | 2 |
| Opciones documentadas | 16 |
| Placeholders item | 15 |
| Placeholders album | 10 |
| Placeholders playlist | 5 |
| Formatos de fecha | 13 |
| Ejemplos prácticos | 8 |
| Casos de uso | 8 |
| URLs soportadas | 5 tipos |

---

## 🎯 Para Qué Sirve Cada Sección

| Sección | Úsala cuando... |
|---------|-----------------|
| Comandos | Quieres saber QUÉ comandos existen |
| Opciones | Necesitas ajustar comportamiento |
| Placeholders | Quieres customizar nombres de carpetas |
| Formato de fechas | Quieres fechas específicas en nombres |
| Ejemplos | Necesitas copiar un patrón |
| Casos de uso | Tienes una situación específica |
| Referencia rápida | Necesitas copiar y pegar |

---

## 💡 Consejos de Uso

1. **Empieza simple**: Usa los ejemplos básicos primero
2. **Lee los casos de uso**: Probablemente tu situación está ahí
3. **Copia y adapta**: No tienes que memorizar
4. **Prueba con --debug**: Si algo falla, activa debug
5. **Usa la referencia rápida**: Para comandos más frecuentes

---

## 📚 Otros Archivos Disponibles

```
/mnt/user-data/outputs/
├── REFERENCIA_COMPLETA_COMANDOS_PLACEHOLDERS.md ← ESTE (completo)
├── tiddl-v1.0.0-final.zip
├── 00_RESUMEN_FINAL_v1.0.0.md
├── README.md
├── USAGE.md
├── FORK.md
├── CONTRIBUTING.md
├── CHANGELOG.md
├── CONFIG.md
└── DESIGN_CONSTRAINTS.md
```

---

## 🚀 Cómo Usar Este Documento

### En Tu Computadora
```bash
# Descarga el archivo
# Ábrelo en tu editor de texto (VS Code, Notepad++, etc)
# Usa Ctrl+F para buscar palabras clave
```

### En GitHub
```bash
# Sube el archivo a tu repo
# GitHub mostrará el Markdown formateado automáticamente
# Los usuarios podrán leerlo fácilmente
```

### En Tu Wiki/Documentación
```bash
# Copia el contenido a tu plataforma
# Funciona en Notion, Confluence, etc
```

---

## ✅ Checklist de Lectura

- [ ] Leí los Comandos Principales
- [ ] Entiendo las 5 URLs soportadas
- [ ] Conozco las 16 opciones principales
- [ ] Sé cómo usar placeholders
- [ ] Entiendo formato de fechas
- [ ] Revisé los ejemplos prácticos
- [ ] Mi caso de uso está en "Casos de Uso"
- [ ] Tengo la referencia rápida guardada

---

**¡Listo para usar tiddl!** 🎵
