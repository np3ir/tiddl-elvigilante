# tiddl-elvigilante v1.5.4

## 🇬🇧 What's new

**Large `--artists` / high-quality runs no longer trip TIDAL's HTTP 429 rate limit.**

- A regression had promoted the **whole run** to the strict, low-limit **HiRes**
  client whenever `-q high` (the default) ran with `hires_client=auto` — including
  **all enumeration** of playlists, artists, albums and credits. On a big
  `--artists` expansion (every credited artist's full discography) TIDAL answered
  with real **HTTP 429 (`Retry-After: 60`)**. `--albums` stayed quiet only because
  it enumerates far less; the amplifier is the artist fan-out, not `--resume`.
- The stable client matrix is restored — `high + auto → TV`, `max + auto → HiRes`,
  `* + never → TV`, `* + always → HiRes`. In **`high + auto` all enumeration now
  stays on the lenient TV client**; the 24-bit `HI_RES_LOSSLESS` tier is requested
  **per track only** — for a track whose only FLAC is 24-bit (e.g. Atmos) — via a
  separate secondary HiRes client, never for enumeration. `hires_client=never`
  never builds or calls the HiRes client.
- **One shared per-run request budget** now paces the TV and HiRes clients
  *together*, so activating both cannot exceed `requests_per_minute` (before, each
  client had its own limiter — up to ~2× the rate). It honours the `--rpm`
  override. The 429 circuit breaker stays as a last-resort host-safe stop.

**The `max_tracks_per_session` cap now actually stops the run.**

- Reaching the cap used to print "Reinicia para continuar" while the engine kept
  dispatching and enumerating the remaining resources (real API calls, more
  `[n/total]` lines). Reaching the cap now **stops the run**: no further resource
  is dequeued, enumerated (credits, covers, edition resolution) or requested;
  already-in-flight downloads finish cleanly.
- The cap **counts only NEW downloads** — an already-present file
  (`skip_existing`) no longer consumes the quota. Under concurrency it is enforced
  with an **atomic per-track reservation**, so parallel tracks can never overshoot
  the limit, and the warning is shown the moment the cap is reached.
- On `--resume`, a resource cut short by the cap is **not** marked complete, so a
  later run re-fetches its remaining tracks. Reaching the cap is a **normal stop**
  (distinct from a user cancel / 429 / 401): `tiddl download …` still exits **0**.

- **Engine-only release.** Re-pinning the bundled engine and rebuilding/publishing
  the GUI are a later, separate step and are not part of this engine release.

## 🇪🇸 Novedades

**Las corridas grandes `--artists` / de alta calidad ya no disparan el límite HTTP 429 de TIDAL.**

- Una regresión promovía **toda la corrida** al cliente **HiRes** estricto (de
  límite bajo) siempre que `-q high` (el valor por defecto) corría con
  `hires_client=auto` — incluida **toda la enumeración** de playlists, artistas,
  álbumes y créditos. En una expansión grande `--artists` (la discografía completa
  de cada artista acreditado) TIDAL respondía con **HTTP 429 real
  (`Retry-After: 60`)**. `--albums` quedaba tranquilo solo porque enumera mucho
  menos; el amplificador es el fan-out de artistas, no `--resume`.
- Se restaura la matriz estable de clientes — `high + auto → TV`,
  `max + auto → HiRes`, `* + never → TV`, `* + always → HiRes`. En
  **`high + auto` toda la enumeración se queda ahora en el cliente TV lenient**; el
  nivel 24-bit `HI_RES_LOSSLESS` se pide **solo por pista** —para una pista cuyo
  único FLAC es 24-bit (p. ej. Atmos)— mediante un cliente HiRes secundario, nunca
  para enumerar. `hires_client=never` nunca construye ni llama al cliente HiRes.
- **Un único presupuesto de solicitudes compartido por corrida** regula ahora a
  los clientes TV y HiRes *en conjunto*, de modo que activar ambos no puede superar
  `requests_per_minute` (antes cada cliente tenía su propio limitador — hasta ~2×
  la tasa). Respeta el override `--rpm`. El circuit breaker de 429 permanece como
  parada host-safe de último recurso.

**El límite `max_tracks_per_session` ahora detiene de verdad la corrida.**

- Al alcanzar el límite se imprimía "Reinicia para continuar" mientras el motor
  seguía despachando y enumerando los recursos restantes (llamadas API reales, más
  líneas `[n/total]`). Alcanzar el límite ahora **detiene la corrida**: no se
  toma, enumera (créditos, portadas, resolución de ediciones) ni solicita ningún
  recurso más; las descargas ya en curso terminan limpiamente.
- El límite **cuenta solo descargas nuevas** — un archivo ya presente
  (`skip_existing`) ya no consume el cupo. Con concurrencia se aplica mediante una
  **reserva atómica por pista**, de modo que las pistas en paralelo nunca superan
  el límite, y el aviso se muestra en el momento en que se alcanza.
- Con `--resume`, un recurso truncado por el límite **no** se marca completo, así
  que una corrida posterior vuelve a bajar sus pistas restantes. Alcanzar el límite
  es una **parada normal** (distinta de una cancelación del usuario / 429 / 401):
  `tiddl download …` sigue saliendo con código **0**.

- **Versión solo del motor.** Re-fijar el pin del motor empaquetado y
  reconstruir/publicar la GUI son un paso posterior e independiente, y no forman
  parte de esta versión del motor.
