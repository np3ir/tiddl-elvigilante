# tiddl-elvigilante v1.5.3

## 🇬🇧 What's new

**A cooperative safety stop no longer terminates the host process.**

- Cancelling a download — or the engine's own safety stop when TIDAL
  rate-limits the run (**429**) or flags/blocks the account (**401**) — now ends
  the run by **returning a non-zero exit code** instead of calling `sys.exit()`
  during teardown.
- **The CLI is unchanged:** `tiddl download …` and `python -m tiddl …` still exit
  non-zero on Cancel / 429 / 401, so scripts and CI keep the same exit codes.
- **Why it matters:** under an embedded interpreter (a bundled GUI), the old
  `sys.exit()` hard-killed the whole host process during teardown. The exit is
  now a normal `click.exceptions.Exit` that can be caught in-process.
- **The matching GUI adaptation is a later, separate step:** catching that exit
  in-process, re-pinning the bundled engine, and rebuilding/publishing the GUI
  are not part of this engine release.

## 🇪🇸 Novedades

**Una parada de seguridad cooperativa ya no termina el proceso anfitrión.**

- Cancelar una descarga —o la parada de seguridad del propio motor cuando TIDAL
  limita la tasa de la corrida (**429**) o marca/bloquea la cuenta (**401**)—
  ahora finaliza la corrida **devolviendo un código de salida no cero** en lugar
  de llamar a `sys.exit()` durante el cierre.
- **El CLI no cambia:** `tiddl download …` y `python -m tiddl …` siguen saliendo
  con código no cero ante Cancel / 429 / 401, así que los scripts y la CI
  conservan los mismos códigos de salida.
- **Por qué importa:** bajo un intérprete embebido (una GUI empaquetada), el
  `sys.exit()` anterior mataba de golpe todo el proceso anfitrión durante el
  cierre. Ahora la salida es un `click.exceptions.Exit` normal que puede
  capturarse dentro del proceso.
- **La adaptación correspondiente de la GUI es un paso posterior e
  independiente:** capturar esa salida en el proceso, re-fijar el pin del motor
  empaquetado y reconstruir/publicar la GUI no forman parte de esta versión del
  motor.
