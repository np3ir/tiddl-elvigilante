# 🎵 tiddl — Tutorial de instalación y configuración

Guía paso a paso para instalar y configurar **tiddl**, un descargador de música de TIDAL (FLAC, letras, portadas, metadata completa). Pensada para compartir en grupos de Telegram — seguila de arriba hacia abajo.

> ⚠️ **Aviso**: esta herramienta es para uso personal/educativo. No está afiliada a TIDAL. El uso debe cumplir los Términos de Servicio de TIDAL y las leyes de derechos de autor de tu país. Lo que bajes es para uso personal, no para redistribuir.

---

## 1. Requisitos

- **Python 3.10 o superior** (funciona con 3.11, 3.12, 3.13, 3.14)
- **ffmpeg** (para procesar audio/video)
- **Cuenta de TIDAL** — importante: según la calidad que quieras, necesitás un plan distinto:
  - `low` / `normal` (AAC) → cualquier cuenta, incluso gratuita
  - `high` (**FLAC 16-bit/44.1kHz, lossless**) → requiere plan **HiFi** (de pago)
  - `max` (**FLAC hi-res hasta 24-bit**) → requiere plan **HiFi Plus**

Si tu cuenta no tiene el plan necesario, tiddl baja automáticamente a la mejor calidad disponible.

---

## 2. Instalar Python

Si no lo tenés, bajalo de [python.org/downloads](https://www.python.org/downloads/). Durante la instalación en Windows, marcá la casilla **"Add python.exe to PATH"**.

Verificá que quedó instalado abriendo una terminal (CMD/PowerShell en Windows, Terminal en Mac/Linux):

```bash
python --version
```

Debería mostrar `Python 3.10` o más nuevo.

---

## 3. Instalar ffmpeg

**Windows** (con `winget`, ya viene en Windows 10/11 actualizados):
```bash
winget install ffmpeg
```

**macOS** (con [Homebrew](https://brew.sh)):
```bash
brew install ffmpeg
```

**Linux (Ubuntu/Debian)**:
```bash
sudo apt install ffmpeg
```

Verificá que quedó instalado:
```bash
ffmpeg -version
```

---

## 4. Instalar tiddl

```bash
pip install git+https://github.com/np3ir/tiddl-elvigilante
```

Verificá que se instaló:
```bash
tiddl --help
```

Si ves la lista de comandos, ya está listo.

---

## 5. Autenticarte con tu cuenta de TIDAL

```bash
tiddl auth login
```

> **⚠️ Ahora aparecen 2 autorizaciones (login híbrido).** Para lograr la máxima calidad sin tener que mantener ventanas abiertas, `tiddl auth login` configura **dos** tokens:
> - **Paso 1/2 — HiRes:** cliente con derecho a `HI_RES_LOSSLESS` (24-bit).
> - **Paso 2/2 — Fallback:** cliente TV que entrega `LOSSLESS` (16-bit) en los tracks donde el primario bajaría a 320 kbps.

Esto va a:
1. Abrir un link en el navegador para el **Paso 1/2 (HiRes)** — inicia sesión en TIDAL y confirma el código.
2. Abrir **otro** link para el **Paso 2/2 (Fallback)** — confirma el segundo código.
3. La terminal muestra **"Logged in!"** en cada paso y al final **"Hibrido listo"**.

Ambas sesiones quedan guardadas y **se auto-refrescan solas**: no hace falta repetir esto ni mantener ventanas abiertas. Resultado: **24-bit en HiRes + 16-bit LOSSLESS en el resto, nunca lossy (AAC).**

Para reconfigurar solo el segundo token: `tiddl auth login-fallback`. Para salir de ambos: `tiddl auth logout`.

---

## 6. Configuración inicial

tiddl guarda su configuración en:
- **Windows:** `C:\Users\TU_USUARIO\.tiddl\config.toml`
- **Mac/Linux:** `~/.tiddl/config.toml`

Abrilo con cualquier editor de texto (Notepad, VS Code, etc.) y ajustá al menos esto:

```toml
[download]
track_quality = "high"        # low / normal / high / max — ver tabla de arriba
video_quality = "fhd"
download_path = "D:/Musica"   # a dónde se guardan las descargas
skip_existing = true          # no vuelve a bajar lo que ya tenés

[metadata]
enable = true
embed_lyrics = true
save_lyrics = true
cover = true
```

### 6.1 Proteger un NAS, USB o unidad de red (recomendado)

Si `download_path` apunta a un NAS, USB o unidad mapeada como `Z:\`, podés
evitar que tiddl escriba en una carpeta local equivocada cuando el volumen no
esté conectado. Con el destino real montado, ejecutá una sola vez:

```powershell
tiddl destination trust "Z:\"
tiddl destination status "Z:\"
```

El segundo comando debe mostrar `Z:\: trusted`. Después añadí a la sección
`[download]` de `config.toml`:

```toml
destination_identity = "strict"
```

Desde ese momento, si el NAS o disco desaparece o cambia, tiddl rechaza la
escritura y conserva el archivo verificado para recuperación. No hace falta
repetir el proceso en cada descarga. Consultá la guía bilingüe completa:
**[DESTINATION_SAFETY.md](DESTINATION_SAFETY.md)**.

---

## 7. Comandos básicos para descargar

```bash
# Un track suelto
tiddl download url https://tidal.com/track/123456789

# Un álbum completo
tiddl download url https://tidal.com/album/497662013

# Una playlist
tiddl download url https://tidal.com/playlist/abc-123-xyz

# Toda la discografía de un artista
tiddl download url https://tidal.com/artist/12316

# Expandir una playlist (en vez de bajarla como playlist):
tiddl download --albums url https://tidal.com/playlist/abc-123-xyz   # el álbum completo de cada canción
tiddl download --artists url https://tidal.com/playlist/abc-123-xyz  # la discografía de cada artista (¡puede ser MUCHO!)
tiddl download --tracks url https://tidal.com/playlist/abc-123-xyz   # cada canción suelta, con estructura de track

# Tus favoritos (canciones que marcaste con ♥ en TIDAL)
tiddl download fav

# Buscar sin saber la URL
tiddl download search "nombre del artista o canción"
```

---

## 8. ⚡ Velocidad vs. seguridad de la cuenta — leé esto antes de bajar en masa

Si vas a bajar muchos artistas/álbumes de una, **no lo hagas con la configuración más agresiva posible** — TIDAL puede detectar patrones de descarga que no parecen humanos y suspender la cuenta temporalmente.

En `config.toml`, sección `[download]`, estos son los valores que controlan el ritmo:

| Opción | Qué hace | Valor recomendado (equilibrado) |
|---|---|---|
| `threads_count` | Cuántos tracks se descargan a la vez | `1` |
| `requests_per_minute` | Piso de peticiones por minuto a la API de TIDAL | `20` |
| `track_delay` | Pausa aleatoria (segundos) entre cada track | `3.0` |
| `artist_delay` | Pausa aleatoria (segundos) entre cada álbum al bajar un artista completo | `8.0` |
| `artist_concurrency` | Cuántos álbumes se procesan a la vez | `1` |

**Regla simple**: si estás bajando pocas cosas (un álbum, una playlist), no importa tanto. Si vas a bajar la discografía completa de muchos artistas seguidos, dejá estos valores conservadores (o más altos, nunca en `0`) y armate paciencia — es más lento, pero es la config que reduce el riesgo de que te bloqueen la cuenta.

⚠️ Si en algún momento ves que TIDAL empieza a rechazar pedidos o tu sesión se cae sola de forma rara, es señal de ir MÁS lento, no más rápido.

---

## 9. Problemas comunes

**"ffmpeg no encontrado" / error de conversión**
→ Verificá que `ffmpeg -version` funcione en tu terminal. Si instalaste ffmpeg después de instalar tiddl, puede que necesites reiniciar la terminal (o la PC en Windows) para que el PATH se actualice.

**El login no confirma / se queda esperando**
→ Revisá que hayas completado el login en la MISMA pestaña/link que se abrió, y que no haya expirado (tenés unos minutos). Si expira, corré `tiddl auth login` de nuevo.

**Quiero bajar en la mejor calidad pero me llega en AAC**
→ Tu cuenta de TIDAL no tiene el plan necesario para esa calidad (ver tabla del punto 1), o el track específico no está disponible en esa calidad en tu región.

**Ya bajé algo y no quiero que se repita**
→ `skip_existing = true` en la config ya hace esto automáticamente — no vuelve a bajar ni retagear lo que ya está completo.

---

## 10. Más ayuda

- Referencia completa de comandos: [COMPLETE_COMMAND_REFERENCE.md](COMPLETE_COMMAND_REFERENCE.md)
- Todas las opciones de configuración: [CONFIG.md](CONFIG.md)
- Ejemplos de uso: [USAGE.md](USAGE.md)
- Repo: https://github.com/np3ir/tiddl-elvigilante

---

*Este tutorial corresponde al fork `np3ir/tiddl-elvigilante`. Es software de uso personal — no lo uses para redistribuir contenido con derechos de autor.*
