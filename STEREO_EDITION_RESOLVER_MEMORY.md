# Stereo Edition Resolver — Continuation Memory

Last updated: 2026-08-19

## Objective

Allow a user who supplies a TIDAL Atmos-only album URL to find and optionally
use a separately published TIDAL stereo edition at High (Lossless) or MAX
(HiRes Lossless), without MusicBrainz, ISRC dependence, or any non-TIDAL data.

## Confirmed catalog case

- Atmos: album `549984784`, 13 tracks, `audioModes=[DOLBY_ATMOS]`.
- Stereo/MAX: album `549980023`, 14 tracks,
  `audioModes=[STEREO]`, tags `LOSSLESS, HIRES_LOSSLESS`.
- Same artist/title/date; stereo adds `Still`.
- Resolver score: 97.4%; track overlap: 92.9%; confirmation required.
- Corresponding Atmos/stereo tracks have different IDs and ISRCs. ISRC is not
  a reliable bridge for this feature.

## Implemented

1. `tiddl/core/edition_resolver.py`
   - TIDAL-only catalog matching.
   - Normalized title matching, artist/date/explicit/duration/track overlap.
   - High accepts `LOSSLESS` or `HIRES_LOSSLESS` stereo.
   - MAX requires advertised `HIRES_LOSSLESS` stereo.
   - Compatible source albums are retained without catalog search.
2. `tiddl info editions -q high|max ALBUM_URL`
   - Read-only diagnostic; tested against both confirmed album IDs.
3. `tiddl download --audio-mode stereo --edition-match ask|best --dry-run ...`
   - Direct album URLs only in this phase.
   - `auto` remains the default and preserves all legacy behavior.
   - Missing stereo candidate is skipped, never silently downloaded as Atmos.
   - Changed track lists require confirmation under `ask`.
   - `--dry-run` never prompts, downloads, or changes settings.

## Tests and evidence

- `tests/test_edition_resolver.py`: 7 focused tests currently pass.
- Ruff and `git diff --check` pass for resolver-related files.
- Real TIDAL diagnostic succeeds in about 3.6 seconds after title-prefiltering.
- Full suite observation before download integration: 298 passed, 3 skipped,
  6 failures in existing recover/publish tests under the local destination
  identity configuration. These failures are unrelated to resolver files.

## Safety boundaries

- Do not add MusicBrainz or another metadata source.
- Do not treat catalog Atmos tags as proof of the delivered stream mode.
- Do not alter playlist, artist, mix, or individual-track IDs yet.
- Do not enable automatic replacement by default.
- Before accepting a downloaded file as stereo/MAX, later phases must validate
  the playback response (`audioMode`, `audioQuality`, bit depth/sample rate)
  and ideally the parsed codec/channel layout.

## Next steps

1. Add focused CLI tests for dry-run, accept, decline, no-candidate, and
   already-compatible source using mocked TIDAL APIs.
2. Add post-playback stream validation before enabling this in the GUI.
3. Decide non-interactive behavior and non-zero exit status for skipped albums.
4. Test one accepted replacement against a controlled temporary destination.
5. Only then persist `audio_mode` in config and expose it in tiddl-gui.

## Latest live integration checks

- Real MAX dry-run for Atmos album `549984784` selected stereo album
  `549980023`, reported `Still`, stated that confirmation would be required,
  and performed no download.
- Real `ask` run was answered `No`; it skipped the Atmos album and printed
  `No resources remain to download.` No download began.
- An accepted real download has intentionally not been run during development;
  test acceptance with a controlled destination before release.

### Controlled accepted-run attempt

Attempted on 2026-08-19 with:

- Atmos input `443072650` (Tropicoqueta).
- Expected stereo replacement `442927546`.
- MAX, `edition-match=best`, one-track session limit, one thread, zero delays.
- Isolated temporary destination outside the music library.

Observed:

- Resolver correctly replaced `443072650 -> 442927546` at 100% score/overlap.
- Playback request targeted stereo track `442927549` with
  `audioquality=HI_RES_LOSSLESS`.
- TIDAL returned 401 token-expired and rejected automatic refresh because the
  account/token is flagged; manual `tiddl auth login` is required.
- Total downloads: 0. Temporary destination contained no files.
- Therefore codec/channel/bit-depth verification with ffprobe remains pending.

Unrelated defects exposed by this attempt:

- A playback 401 was eventually displayed as `(Rate Limit)`.
- With `max_tracks_per_session=1`, remaining album items each printed the
  session-limit message.

Both defects were corrected offline on 2026-08-19:

- HTTP failures are now classified using the actual response status (with a
  conservative exact-number fallback). A 401 reports `Authentication expired`;
  only a real 429 reports `Rate Limit`. Generic words such as `Limit` or `Rate`
  no longer cause false classification.
- A 401 now also raises the shared cooperative stop signal. Queued tracks,
  remaining resources, quality fallbacks, and responses from concurrent stream
  requests already in flight stop before any further processing or writes.
- `SessionTrackLimit` admits tracks synchronously and marks its warning as
  announced, so already-scheduled remaining items are skipped quietly.
- `tests/test_download_policy.py` covers 401/429 separation, false-positive
  prevention, unlimited mode, and one-time session-limit notification.
- Focused offline result after run-wide 401 stopping: 15 passed
  (download-policy + edition-resolver tests). The broader downloader-policy
  group also passes: 35 tests.
- Full offline result: 307 passed, 3 skipped, and the same 6 pre-existing
  recover/publish failures caused by local destination-identity configuration.
- No TIDAL endpoint, login, token refresh, playback, or download was contacted
  while the account was temporarily blocked.

## Real artist-catalog audit: KAROL G (artist 5237820)

Read-only TIDAL audit on 2026-08-19:

- 17 album entries returned.
- 4 Atmos-only editions.
- 6 stereo editions advertising MAX (`HIRES_LOSSLESS`).
- 7 stereo editions advertising High (`LOSSLESS` only).

Resolver results for every Atmos album:

| Atmos ID | Title | Stereo ID | High | MAX | Score | Difference |
|---|---|---:|---|---|---:|---|
| 549984784 | NO ME ARREPIENTO DE SENTIR TANTO | 549980023 | found | found | 97.4% | stereo adds `Still` |
| 443072650 | Tropicoqueta | 442927546 | found | found | 100% | identical listing |
| 310041848 | MAÑANA SERÁ BONITO (BICHOTA SEASON) | 309985062 | found | found | 100% | identical listing |
| 278210628 | MAÑANA SERÁ BONITO | 277248246 | found | found | 100% | identical listing |

Both High and MAX can select a stereo edition advertising
`LOSSLESS, HIRES_LOSSLESS`: High later requests `LOSSLESS`; MAX later requests
`HI_RES_LOSSLESS`. Catalog selection and playback quality remain separate.

## Offline playback-policy phase (2026-08-19)

- Added `tiddl/core/stream_policy.py` to inspect playback metadata before any
  media URL is transferred.
- `--audio-mode stereo` is passed into `Downloader`; a returned mode other than
  `STEREO` (including `DOLBY_ATMOS`) triggers the run-wide cooperative stop.
- The inspection records actual `audioQuality`, bit depth and sample rate, and
  reports whether the delivered quality meets High (`LOSSLESS`) or MAX
  (`HI_RES_LOSSLESS`). A lower-quality track is not discarded solely for being
  below MAX because mixed-quality albums may legitimately contain tracks whose
  highest available stereo asset is standard lossless; existing fallback and
  degradation reporting remain responsible for that case.
- Focused stream-policy, resolver, failure-policy and downloader regression
  group: 47 tests passed. No TIDAL calls were made.
- Latest full offline suite after this phase: 314 passed, 3 skipped, with the
  same 6 pre-existing `recover/publish` failures under the machine's local
  destination-identity state. No new resolver/downloader failures appeared.

### Complete preference matrix

- Audio edition: `auto` or `stereo`.
- Requested quality: `low`, `normal`, `high`, or `max`.
- Quality policy: `flexible` (legacy fallback) or `strict` (exact delivery).
- These controls are independent, so every combination is available.
- `stereo` always rejects a non-`STEREO` playback manifest.
- `strict high` requires exactly `LOSSLESS`; `strict max` requires exactly
  `HI_RES_LOSSLESS`. Neither silently falls back.
- Low/Normal stereo catalog discovery is supported: any catalog edition that
  advertises `STEREO` can be requested at those delivery tiers.
- Focused regression after completing the matrix: 50 tests passed offline.
- Flexible catalog selection now treats the user's quality as a ceiling:
  MAX searches MAX -> High -> Normal -> Low; High searches High -> Normal ->
  Low. The playback request uses the original ceiling and follows the same
  downward order.
- The resolver scans the artist catalog only once, groups matching stereo
  editions by their highest usable tier, then selects from the first available
  tier. It does not repeat the complete catalog query for each fallback level.
- Focused regression after catalog fallback optimization: 53 tests passed.
- The GUI now exposes the existing engine `--dry-run` through a `Verify
  versions` action for direct album links. This exercises catalog resolution
  and reports the selected tier/differences without constructing `Downloader`
  or transferring media.

## Clean offline regression baseline

- The six historical `recover/publish` failures were test-environment leakage,
  not product failures: `tests/test_recover_cli.py` inherited the developer's
  real `destination_identity = strict` setting while its default-path tests
  assumed `off`.
- Its autouse fixture now explicitly isolates that setting to `off`; tests that
  exercise strict mode still opt into it themselves.
- Recovery group: 34 passed.
- Complete engine suite after all resolver/stream-policy changes: **326 passed,
  3 skipped, 0 failed** in the offline environment.
- No TIDAL catalog, playback, authentication, or download request was made.
- Packaging check succeeded: generated
  `.codex-build/tiddl_elvigilante-1.2.1-py3-none-any.whl`, containing the new
  resolver, stream policy and download policy modules.

## Working tree caution

This repository contains many user-owned untracked audit/proposal files.
Preserve them. Resolver work is limited to the files listed above plus focused
tests and documentation.

## Successful controlled live downloads (2026-08-19)

The TIDAL account became available again and the accepted replacement was
validated using isolated roots outside the music library.

- Source: Atmos album `549984784`.
- Selected replacement: stereo album `549980023` at 97.4% score and 92.9%
  track overlap; the additional track `Still` was reported before transfer.
- Each run used `--edition-match best`, `--quality-policy strict`, one thread,
  zero delays and `--max-tracks 1`.
- MAX delivered `Te llevas To` as FLAC, 24-bit, 48 kHz, 2-channel stereo.
- High delivered the same track as FLAC, 16-bit, 44.1 kHz, 2-channel stereo.
- Both runs exited successfully with exactly one download. `ffprobe` confirmed
  the codec, bit depth, sample rate and stereo channel layout.
- Strict destination-identity protection correctly rejected the first
  untrusted test root. Each root was then explicitly trusted for its run and
  removed from local trust state afterward; global security was not weakened.
- Test files remain under `C:\tiddl-live-test` and
  `C:\tiddl-live-test-high` for manual inspection or later cleanup.

### Flexible degradation validated with Kinito Mendez

- Artist `3941799` returned 23 album entries: no album advertised
  `HIRES_LOSSLESS`, 13 advertised `LOSSLESS`, and 10 advertised only `STEREO`.
- Album `14824487` (`El Decreto`) with MAX + flexible resolved to catalog tier
  High and downloaded one track successfully as FLAC, 16-bit, 44.1 kHz,
  2-channel stereo. SHA-256:
  `68216CD006791C957E810244501855B99F39CAC77BA9CCAA4C4D52487C3B148F`.
- MAX + strict correctly rejected the same album without downloading because
  no exact MAX stereo edition exists.
- That strict dry run exposed misleading wording claiming an Atmos avoidance
  even though the source was already stereo. The message was corrected to say
  that the requested stereo/quality policy cannot be satisfied.

Album `8455110` (`El Hombre Merengue`) validated the complete lossy fallback:

- MAX + flexible selected catalog tier Normal; live playback ultimately
  returned LOW and the engine downloaded one HE-AAC `.m4a`, 96 kbps class,
  44.1 kHz, 2-channel stereo. It emitted the quality-degradation warning.
- SHA-256: `096E02D1715F8CF0A6DEBAC0D7D63CC35A1FD8EDF900A86FF4F4F746BFDC68A7`.
- Normal + strict received LOW, stopped before media transfer, downloaded zero
  files and now exits with status 1.
- This test exposed two defects that were fixed: cooperative safety stops now
  produce a non-zero CLI exit status, and Downloader preserves the original
  user quality slug so Normal maps to TIDAL `HIGH` rather than being
  reinterpreted as user High/`LOSSLESS` during strict validation.
- Focused regression: 65 passed. Complete offline suite after the fixes:
  **328 passed, 3 skipped, 0 failed**.

Still not intentionally tested live: forcing an authentication failure to
exercise the 401 stop. That path remains covered by offline tests.
