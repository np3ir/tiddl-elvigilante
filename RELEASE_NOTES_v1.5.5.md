# tiddl-elvigilante v1.5.5

## 🇬🇧 What's new

**Cross-folder false `Exists (Alt)` no longer skips Dolby Atmos tracks.**

- The skip-existing check that looks for an already-downloaded alternative
  extension (for example, a `.flac` when a `.m4a` was requested) used a
  **run-global** index keyed by the bare filename stem. Two albums that share
  track titles — such as a Deluxe edition (`.flac`) and a "(Dolby Atmos Version)"
  (`.m4a`) — collided: the first album scanned poisoned the index, so a
  same-titled track in the **other** album matched a file living in a **different**
  folder. The engine reported `Exists (Alt)` and pointed the metadata writer at a
  path that did not exist there, **skipping the Atmos track and emitting a metadata
  warning** (`[WinError 2]`).
- **Same-folder only.** The alternative-extension lookup is now scoped to the
  track's **own directory**. Only a real file in that folder can satisfy the
  request; a same-stem file in another album is ignored, so Atmos tracks are no
  longer skipped because of a FLAC located in a different album.
- **Real name and casing preserved.** Matching is case-insensitive, but the
  **existing on-disk filename** is returned — never a reconstructed lowercase name —
  so the reported path is one that actually exists (no spurious re-download).
- **Atmos and stereo are distinct modalities.** When Atmos is the **requested**
  modality (`-q atmos` on a track that offers Atmos), a same-stem **stereo FLAC is
  not accepted** as an alternative. For a stereo request (`-q normal`/`low`) or a
  FLAC request (`-q high`/`max`), an eligible equal-or-better same-folder
  alternative continues to satisfy the request.
- **Stale-listing guard.** If the cached folder listing is out of date (the file
  vanished, or the name is a directory), the folder is re-scanned **once** and
  revalidated with a real `is_file()` check before reporting `Exists (Alt)`;
  otherwise the track is downloaded normally.

**📚 Documentation.** This release also folds in engine-reference documentation
improvements. These are **documentation only** — they describe existing behaviour
and are **not** new functional changes in 1.5.5: the `tiddl destination` group
(`trust` / `status` / `forget`); the safety model of `--confirm-mounted` and
`--adopt-existing`; `hires_client`, `quality_policy`, and the `--rpm` override; the
shared per-run TV/HiRes request budget; and the `max_tracks_per_session` semantics.

**No behavioural change elsewhere.** This release does **not** modify TV/HiRes
client routing, the quality cascade, or the per-run RPM budget — only the
skip-existing / alternative-extension logic. **Engine-only release:** re-pinning the
bundled engine and rebuilding/publishing the GUI are a later, separate step and are
not part of this engine release.

## 🇪🇸 Novedades

**Los falsos `Exists (Alt)` entre carpetas ya no omiten pistas Dolby Atmos.**

- La comprobación de "ya existe" que busca una extensión alternativa ya descargada
  (por ejemplo, un `.flac` cuando se pidió un `.m4a`) usaba un índice **global de la
  corrida** indexado por el nombre base del archivo. Dos álbumes que comparten
  títulos de pista —como una edición Deluxe (`.flac`) y una "(Dolby Atmos Version)"
  (`.m4a`)— colisionaban: el primer álbum escaneado contaminaba el índice, así que
  una pista con el mismo título en el **otro** álbum coincidía con un archivo
  ubicado en una carpeta **distinta**. El motor reportaba `Exists (Alt)` y apuntaba
  el escritor de metadata a una ruta que allí no existía, **omitiendo
  incorrectamente la pista Atmos y mostrando una advertencia de metadata**
  (`[WinError 2]`).
- **Solo la misma carpeta.** La búsqueda de extensión alternativa ahora se limita al
  **directorio propio** de la pista. Solo un archivo real en esa carpeta puede
  satisfacer la solicitud; un archivo con el mismo nombre base en otro álbum se
  ignora, de modo que las pistas Atmos ya no se omiten por un FLAC ubicado en otro
  álbum.
- **Se preserva el nombre y el casing real.** La coincidencia es insensible a
  mayúsculas/minúsculas, pero se devuelve el **nombre de archivo real en disco** —
  nunca un nombre reconstruido en minúsculas—, así que la ruta reportada existe de
  verdad (sin re-descargas espurias).
- **Atmos y estéreo son modalidades distintas.** Cuando Atmos es la modalidad
  **solicitada** (`-q atmos` en una pista que ofrece Atmos), un **FLAC estéreo** con
  el mismo nombre base **no se acepta** como alternativa. Para una solicitud estéreo
  (`-q normal`/`low`) o una solicitud FLAC (`-q high`/`max`), una alternativa
  elegible, de calidad igual o superior y ubicada en la misma carpeta continúa
  satisfaciendo la solicitud.
- **Defensa ante listados obsoletos.** Si el listado en caché de la carpeta está
  desactualizado (el archivo desapareció, o el nombre es un directorio), la carpeta
  se vuelve a escanear **una sola vez** y se revalida con una comprobación real
  `is_file()` antes de reportar `Exists (Alt)`; de lo contrario, la pista se descarga
  normalmente.

**📚 Documentación.** Esta versión también incorpora mejoras en la documentación de
referencia del motor. Son **solo de documentación** — describen comportamiento ya
existente y **no** son nuevos cambios funcionales en 1.5.5: el grupo
`tiddl destination` (`trust` / `status` / `forget`); el modelo de seguridad de
`--confirm-mounted` y `--adopt-existing`; `hires_client`, `quality_policy` y el
override `--rpm`; el presupuesto de solicitudes compartido TV/HiRes por corrida; y la
semántica de `max_tracks_per_session`.

**Sin cambios de comportamiento en el resto.** Esta versión **no** modifica el
enrutamiento de clientes TV/HiRes, la cascada de calidad ni el presupuesto de
solicitudes por corrida (RPM) — solo la lógica de "ya existe" / extensión
alternativa. **Versión solo del motor:** re-fijar el pin del motor empaquetado y
reconstruir/publicar la GUI son un paso posterior e independiente, y no forman parte
de esta versión del motor.
