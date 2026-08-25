# tiddl-elvigilante v1.5.3

## 🇬🇧 What's new

**A cooperative safety stop no longer terminates the host process.**

- A **cooperative cancellation requested through the engine's hook**
  (`request_cancel()`, as used by the GUI) — or the engine's own safety stop when
  TIDAL rate-limits the run (**429**) or flags/blocks the account (**401**) — now
  ends the run by **returning a non-zero exit code** instead of calling
  `sys.exit()` during teardown.
- **CLI exit codes are preserved** for these cooperative stops: `tiddl download …`
  and `python -m tiddl …` still exit non-zero on a cooperative cancellation / 429
  / 401. This concerns the cooperative-stop path only; it does not change the
  CLI's `Ctrl+C` / `KeyboardInterrupt` handling.
- **Why it matters:** under an embedded interpreter (a bundled GUI), the old
  `sys.exit()` hard-killed the whole host process during teardown. The exit is
  now a normal `click.exceptions.Exit` that can be caught in-process.
- **The matching GUI adaptation is a later, separate step:** the in-process host
  must still catch that `click.exceptions.Exit` around
  `tiddl_app(standalone_mode=False)`; re-pinning the bundled engine and
  rebuilding/publishing the GUI are not part of this engine release.

## 🇪🇸 Novedades

**Una parada de seguridad cooperativa ya no termina el proceso anfitrión.**

- Una **cancelación cooperativa solicitada mediante el hook del motor**
  (`request_cancel()`, como la usa la GUI) —o la parada de seguridad del propio
  motor cuando TIDAL limita la tasa de la corrida (**429**) o marca/bloquea la
  cuenta (**401**)— ahora finaliza la corrida **devolviendo un código de salida
  no cero** en lugar de llamar a `sys.exit()` durante el cierre.
- **Se conservan los códigos de salida del CLI** ante estas paradas cooperativas:
  `tiddl download …` y `python -m tiddl …` siguen saliendo con código no cero ante
  una cancelación cooperativa / 429 / 401. Esto atañe solo al camino de parada
  cooperativa; no cambia el manejo de `Ctrl+C` / `KeyboardInterrupt` del CLI.
- **Por qué importa:** bajo un intérprete embebido (una GUI empaquetada), el
  `sys.exit()` anterior mataba de golpe todo el proceso anfitrión durante el
  cierre. Ahora la salida es un `click.exceptions.Exit` normal que puede
  capturarse dentro del proceso.
- **La adaptación correspondiente de la GUI es un paso posterior e
  independiente:** el host en proceso todavía debe capturar ese
  `click.exceptions.Exit` alrededor de `tiddl_app(standalone_mode=False)`;
  re-fijar el pin del motor empaquetado y reconstruir/publicar la GUI no forman
  parte de esta versión del motor.
