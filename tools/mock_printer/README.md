# Mock printer

A disposable fake PrusaLink printer for testing the printer service. One file,
standard library only, nothing imported from the rest of the repository.
Delete this folder and nothing else is affected (`BUILD` only lets the unit
tests import it).

```bash
python3 tools/mock_printer/mock_printer.py          # from the repo root
```

It listens on `0.0.0.0:18081`, so a cluster on the same machine, or another
machine, can reach it, and shows a live screen that refreshes in place: state,
progress bar, bed temperature, the current job and file, stored files, and the
last requests it served.

```
 MOCK PRUSALINK PRINTER   (test double, not a printer)
────────────────────────────────────────────────────────
 listening   http://localhost:18081   http://192.168.1.20:18081
 login       maker / mock-only   (HTTP Digest)

 state       PRINTING
 progress    ████████████░░░░░░░░░░░░░░░░░░  41.0%
 bed         ██████████████████████████████  60.0 °C
 job         id 3   warrior.bgcode   594 KiB
 ...
 keys:  f finish   c cool bed   i idle   p pause/resume   s stop   e error   q quit
```

## Send it a job

Like a slicer does (`Print-After-Upload: ?1` starts it, `Overwrite: ?1` allows
the same name again):

```bash
curl --digest -u maker:mock-only -X PUT \
  -H 'Print-After-Upload: ?1' -H 'Overwrite: ?1' \
  -T ~/omts-slicer-lab/out/warrior_mod_0.4n_0.2mm_PLA_COREONEL_18m.bgcode \
  http://localhost:18081/api/v1/files/local/warrior.bgcode
```

The job id starts at 1 and goes up by one per job. The job "prints" for
`--print-seconds` (default 60; progress climbs), then reports `FINISHED` with
the bed still at 60 °C, which cools to 24 °C over `--cool-seconds` (default 60).
`--print-seconds=0` turns the automatic behavior off: the state then changes
only with the keys, or with
`curl --digest -u maker:mock-only -X POST localhost:18081/mock/state -d '{"state":"FINISHED","temp_bed":29}'`.

## What it imitates, and what it does not

Follows Prusa's OpenAPI (`Prusa-Link-Web/spec/openapi.yaml`): Digest login;
`GET /api/version`, `/api/v1/info`, `/api/v1/storage`, `/api/v1/status`,
`/api/v1/job`; upload, `POST` (start), `HEAD` and `GET` on
`/api/v1/files/{storage}/{path}` with folders, `Overwrite`, and 409 when the
file exists or a job is running; pause, resume, continue and stop; the file
download from `file.refs.download`; errors as `{code, title, text}`.

Unverified against a real printer: the download path form, the Digest realm
(the mock uses `PrusaLink mock`, which is how the service recognizes it), a new
upload while `FINISHED`, and the short 8.3 `file.name` (the mock reuses the
long name).

Options: `--port`, `--host`, `--username`, `--password`, `--print-seconds`,
`--cool-seconds`, `--gcode FILE` (a file the starting job offers for download).
Without a terminal (a pipe or a log file) it prints one line per change
instead of the live screen.
