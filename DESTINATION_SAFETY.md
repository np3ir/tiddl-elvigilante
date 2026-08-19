# Destination Safety / Seguridad del destino

Destination-volume identity is an opt-in safety feature for NAS shares, USB
drives, mapped network drives and other removable or remote destinations. It
prevents tiddl from publishing files when the mounted destination is not the
same volume the user explicitly trusted.

La identidad del volumen de destino es una protección opcional para NAS,
unidades USB, discos de red y otros destinos remotos o extraíbles. Evita que
tiddl publique archivos cuando el destino montado no sea el mismo volumen que
el usuario autorizó expresamente.

---

## English

### Why enable it?

An unavailable NAS or USB drive can leave behind a valid-looking path. Without
an identity check, an application may write to that local fallback path instead
of the intended volume. Strict mode requires two matching pieces of evidence:

1. A local trust record on the current machine.
2. A `.tiddl-anchor` marker stored at the real destination root.

If either is missing, unreadable or different, tiddl refuses the destination
write. Verified staging data is retained for recovery instead of being lost.

### One-time setup

First confirm that the real destination is mounted. Always trust the **exact
same root** configured as `download_path`.

Windows drive-letter example:

```powershell
Get-PSDrive Z
tiddl destination trust "Z:\"
tiddl destination status "Z:\"
```

UNC path example:

```powershell
tiddl destination trust "\\server\Music"
tiddl destination status "\\server\Music"
```

Linux/macOS example:

```bash
mountpoint /mnt/music
tiddl destination trust /mnt/music
tiddl destination status /mnt/music
```

The status command should report `trusted`. Then edit
`~/.tiddl/config.toml` (`C:\Users\YourName\.tiddl\config.toml` on Windows):

```toml
[download]
download_path = "Z:\\"
scan_path = "Z:\\"
destination_identity = "strict"
```

Normal download commands do not change. Strict mode checks the destination
immediately before protected writes.

### A second computer or fresh installation

The destination marker may already exist while the second machine has no local
record. With the real volume mounted, adopt the existing marker:

```powershell
tiddl destination trust "Z:\" --adopt-existing
```

Do not use `--adopt-existing` if you cannot independently confirm that the path
is the intended physical or network destination.

For unattended automation only, `--confirm-mounted` skips the interactive
question. Use it only after the script has independently verified the mount.

### Status and troubleshooting

```powershell
tiddl destination status "Z:\"
```

| Result | Meaning | Action |
|---|---|---|
| `trusted` | Local record and destination marker agree. | Downloads may publish normally. |
| `local_state_unreadable` | The local trust database cannot be read safely. | Check its permissions or corruption before retrying; do not recreate trust blindly. |
| `unknown_root` | This machine has no trust record for the root. | Trust it, or adopt an independently verified existing marker. |
| `marker_absent` | The trusted root is present without its marker. | Confirm the correct volume is mounted; do not blindly retrust it. |
| `marker_invalid` / `marker_unreadable` | The marker cannot be validated. | Check permissions and storage health. |
| `id_mismatch` | Local record and mounted marker identify different destinations. | Stop and verify the mount; never overwrite the marker to bypass the warning. |

`destination status` is read-only. A non-`trusted` result is status information
and may still return process exit code 0; scripts should inspect the reported
reason instead of relying only on the exit code.

### Retained-file recovery

List retained files without contacting TIDAL or modifying them:

```bash
tiddl recover
```

After restoring and trusting the correct destination, publish one retained
entry or all eligible entries:

```bash
tiddl recover --publish ENTRY_ID
tiddl recover --all --yes
```

For a legacy retained entry that has no destination identity, first bind it to
an already-trusted root:

```powershell
tiddl recover --bind-root ENTRY_ID --root "Z:\" --confirm
```

### Disable or forget

To disable enforcement while keeping trust records, set:

```toml
[download]
destination_identity = "off"
```

To remove only this machine's local trust record:

```powershell
tiddl destination forget "Z:\"
```

`forget` intentionally does **not** delete `.tiddl-anchor` from the shared
destination because another installation may still depend on it.

---

## Español

### ¿Por qué activarlo?

Cuando un NAS o USB no está disponible, puede quedar una ruta aparentemente
válida en el equipo. Sin comprobar su identidad, una aplicación podría escribir
en esa carpeta local en vez del volumen esperado. El modo estricto exige dos
evidencias coincidentes:

1. Un registro de confianza local en la computadora actual.
2. Un marcador `.tiddl-anchor` guardado en la raíz del destino real.

Si falta alguno, no se puede leer o no coincide, tiddl rechaza la escritura. Los
archivos verificados de staging se conservan para recuperación.

### Configuración inicial — una sola vez

Primero confirmá que el destino real esté conectado. Autorizá siempre la
**misma raíz exacta** configurada como `download_path`.

Ejemplo con unidad de Windows:

```powershell
Get-PSDrive Z
tiddl destination trust "Z:\"
tiddl destination status "Z:\"
```

Ejemplo con ruta UNC:

```powershell
tiddl destination trust "\\servidor\Musica"
tiddl destination status "\\servidor\Musica"
```

Ejemplo Linux/macOS:

```bash
mountpoint /mnt/musica
tiddl destination trust /mnt/musica
tiddl destination status /mnt/musica
```

El estado debe mostrar `trusted`. Después editá `~/.tiddl/config.toml`
(`C:\Users\TuNombre\.tiddl\config.toml` en Windows):

```toml
[download]
download_path = "Z:\\"
scan_path = "Z:\\"
destination_identity = "strict"
```

Los comandos de descarga no cambian. El modo estricto verifica el destino justo
antes de cada escritura protegida.

### Segunda computadora o instalación nueva

El marcador puede existir en el NAS aunque la computadora nueva todavía no
tenga un registro local. Con el volumen real conectado, adoptalo así:

```powershell
tiddl destination trust "Z:\" --adopt-existing
```

No uses `--adopt-existing` si no podés confirmar por otro medio que la ruta
pertenece al destino físico o de red correcto.

Solo para automatización sin supervisión, `--confirm-mounted` omite la pregunta
interactiva. Usalo únicamente si el script ya verificó el montaje por otro medio.

### Estado y diagnóstico

```powershell
tiddl destination status "Z:\"
```

| Resultado | Significado | Acción |
|---|---|---|
| `trusted` | El registro local y el marcador coinciden. | Las descargas pueden publicar normalmente. |
| `local_state_unreadable` | No se puede leer con seguridad la base local de confianza. | Revisar sus permisos o corrupción antes de reintentar; no recrear la confianza a ciegas. |
| `unknown_root` | Esta computadora no confía todavía en esa raíz. | Autorizarla o adoptar un marcador existente verificado. |
| `marker_absent` | La raíz confiable aparece sin marcador. | Confirmar que está montado el volumen correcto; no autorizarlo a ciegas. |
| `marker_invalid` / `marker_unreadable` | No se puede validar el marcador. | Revisar permisos y salud del almacenamiento. |
| `id_mismatch` | El registro y el marcador identifican destinos diferentes. | Detenerse y revisar el montaje; no sobrescribir el marcador para evitar el aviso. |

`destination status` es de solo lectura. Un resultado distinto de `trusted` es
información de estado y puede devolver código de proceso 0; los scripts deben
leer la razón mostrada y no depender solamente del código de salida.

### Recuperar archivos retenidos

Listá los archivos sin contactar TIDAL ni modificarlos:

```bash
tiddl recover
```

Después de restaurar y confiar en el destino correcto:

```bash
tiddl recover --publish ID_DE_ENTRADA
tiddl recover --all --yes
```

Para una entrada antigua sin identidad de destino, vinculala primero a una raíz
que ya esté autorizada:

```powershell
tiddl recover --bind-root ID_DE_ENTRADA --root "Z:\" --confirm
```

### Desactivar u olvidar

Para desactivar la protección conservando los registros:

```toml
[download]
destination_identity = "off"
```

Para retirar solo la confianza local de esta computadora:

```powershell
tiddl destination forget "Z:\"
```

`forget` no borra `.tiddl-anchor` del destino compartido porque otra
instalación puede seguir utilizándolo.
