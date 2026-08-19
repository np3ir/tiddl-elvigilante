# TIDAL-only Stereo Edition Audit — Artist 5237820

Date: 2026-08-19

This is a read-only integration-test record. No media was downloaded. Source:
TIDAL artist/album/item endpoints through the project's authenticated API.

## Catalog distribution

| Category | Count |
|---|---:|
| Atmos-only albums | 4 |
| Stereo MAX albums (`HIRES_LOSSLESS`) | 6 |
| Stereo High-only albums (`LOSSLESS`) | 7 |
| Total | 17 |

## Atmos resolution matrix

| Input Atmos album | Selected stereo album | Track overlap | Confirmation |
|---:|---:|---:|---|
| 549984784 | 549980023 | 13/14 (92.9%) | Yes: adds `Still` |
| 443072650 | 442927546 | 20/20 (100%) | No listing difference |
| 310041848 | 309985062 | 10/10 (100%) | No listing difference |
| 278210628 | 277248246 | 17/17 (100%) | No listing difference |

All four resolved for both `requested_quality=high` and
`requested_quality=max`. Selected candidates advertise both `LOSSLESS` and
`HIRES_LOSSLESS`; the later playback request determines whether High or MAX is
actually delivered.

## Reproduction

Use the source checkout (until packaged/installed):

```powershell
python -c "import sys; from tiddl.cli.app import main; sys.argv=['tiddl','download','--track-quality','max','--audio-mode','stereo','--dry-run','url','https://tidal.com/album/443072650']; main()"
```

Expected: stereo replacement `443072650 -> 442927546`, 100% score and overlap,
then a statement that no files or settings were changed.

## Controlled playback attempt

The replacement was accepted in a one-track isolated test and correctly
requested `HI_RES_LOSSLESS` from stereo track `442927549`. Playback could not
complete because the TIDAL token had expired and automatic refresh was refused.
No files were written. Manual reauthentication is required before ffprobe can
validate the delivered stream.
