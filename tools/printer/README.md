# From the printer's G-code to a model, and the skills that report it (`tools/printer/`)

Goal: while a print runs, know what it deposits (shape, supports, bed
position), to train a pose model for the finished part. The printer is the only
part guaranteed to be in the system, so everything starts from what the printer
receives. Plan and status: `research/HANDOFF.md`, section 5f.

| Tool | Target | What it does |
| :--- | :--- | :--- |
| `mock_printer` | `python3 tools/mock_printer/mock_printer.py` | A disposable fake PrusaLink printer with a live screen. [README](../mock_printer/README.md). |
| `gcode_to_stl.py` | `//tools/printer:gcode_to_stl` | G-code or bgcode to a compound STL. The PrusaLink service runs it on every new job; also usable by hand. |
| `printer_skills` | `//tools/printer:printer_skills` | Runs the four printer skills through the Executive (no robot motion); `--mode=monitor` is a live screen of both read skills. |

## The flow

```
 you (curl or a slicer)
   │ PUT file, Print-After-Upload                                      A: separate
   ▼                                                                      machine
 PRINTER  (tools/mock_printer, or a real PrusaLink printer)
   ▲   GET /api/v1/status, /api/v1/job, then the file at refs.download
   │
 PRUSALINK SERVICE   in the reBot solution, polls every 2 s               B: Intrinsic
   new job? ─► download ─► check it is G-code ─► gcode_to_stl ─► compound.stl
   ▲          (job_id, name, size, file time seen before? skip)
   │ gRPC
 SKILLS  read_job_model / wait_for_job_model        "the model exists, start the next process"
         read_printer_status / wait_for_printer_ready  "finished and cool, unload"
```

Details of the service (routes, storage, resends, failures):
[`services/prusalink/README.md`](../../services/prusalink/README.md).

## Step by step

Everything starts in `/home/berti/gits/intrinsic-omts` (one terminal each;
five if you want every view). A cluster must be running at `localhost:17080`.

**Terminal 1: the mock printer** (the disposable one; any machine; leave it open).
It shows a live screen and needs nothing else:

```bash
python3 tools/mock_printer/mock_printer.py
```

**Terminal 2: deploy the reBot solution with the printer service** (once;
replaces the active solution; the command exits and the cluster keeps running):

```bash
bazel run //:rebot_solution -c opt -- --address=localhost:17080 --operation_mode=sim
```

With no printer arguments the service looks for the mock and says so. For a
real printer add `--//:printer_url=http://<ip> --//:printer_username=<user>
--//:printer_password=<password>` before the `--`. Check the route taken:

```bash
curl -sS http://localhost:17080/ext/services/prusalink/healthz
# {"route": "mock", "printer_url": "http://10.42.0.1:18081", "storage_dir": ..., ...}
# route "configured": the printer you passed. printer_url null: not found yet.
inctl service state list --address localhost:17080     # prusalink: Enabled
```

(From inside the cluster the host is the default gateway, `10.42.0.1` on k3s;
the mock listens on all interfaces.)

**Terminal 3: the skills, live** (both read skills, one real Executive call
each per refresh; the first run builds the tool):

```bash
bazel run //tools/printer:printer_skills -- --address=localhost:17080 --mode=monitor
```

**Terminal 4: send the job.** This is the file the slicer would send; the
original G-code stays where it is and is only read:

```bash
F=$HOME/omts-slicer-lab/out/warrior_mod_0.4n_0.2mm_PLA_COREONEL_18m.bgcode
curl --digest -u maker:mock-only -sS -w "HTTP %{http_code}\n" -X PUT \
  -H 'Print-After-Upload: ?1' -H 'Overwrite: ?1' -T "$F" \
  http://localhost:18081/api/v1/files/local/warrior.bgcode
```

Expect `HTTP 201`. What you see, within a few seconds:

1. Terminal 1: `PRINTING`, job 1, the progress bar moving for 60 s, then
   `FINISHED`, the bed cooling from 60 to 24 °C over 60 s.
2. Terminal 3, `read_job_model`: `DOWNLOADING`, `CONVERTING` (about 5 s), then
   `MODEL_READY` with the STL path (`MODEL_READY` is the signal for the next
   process to start). `read_printer_status`: `WAITING_FOR_PRINT` while it
   prints, `WAITING_FOR_COOLING` after `FINISHED` above 30 °C, and
   `READY_TO_UNLOAD` once it is below 30 °C (the signal to unload).

**Where the model is.** In the service's container,
`/tmp/prusalink/jobs/1_warrior.bgcode/compound.stl`, and served to you:

```bash
curl -sS -o /tmp/warrior.stl http://localhost:17080/ext/services/prusalink/v1/jobs/1/model.stl
curl -sS http://localhost:17080/ext/services/prusalink/v1/jobs | python3 -m json.tool
```

**Sending the same model again** (once the first job is `FINISHED`; the mock
answers 409 while a job runs, as PrusaLink does): repeat the Terminal 4 `curl`.
It is job 2, a new folder, and `reused: true`: the conversion is copied, not
redone. **A file that is not G-code:** `printf 'hello\n' > /tmp/notes.gcode`
and upload it as `notes.gcode`: `MODEL_FAILED` with the reason.

**Waiting skills** (what a process chain uses; Terminal 5, before sending a
job, for a model, then for the unload signal):

```bash
bazel run //tools/printer:printer_skills -- --address=localhost:17080 \
  --mode=wait-model --after-job-id=0 --timeout=120   # returns READY when the STL exists
bazel run //tools/printer:printer_skills -- --address=localhost:17080 \
  --mode=wait --job-id=1 --timeout=180               # returns READY when finished and cool
```

Other modes: `--mode=read`, `--mode=model` (one snapshot), `--mode=watch`
(repeats). `--job-id` limits a skill to one job; without it any job is accepted.
`--after-job-id` ignores jobs up to that id.

**Without the mock's automatic timing:** `--print-seconds=0` on the mock; then
`f` finishes, `c` cools the bed, `i` sets idle (keys on its screen).

**Solution state**, if you want it (the skills already show what matters):

```bash
inctl service state list --address localhost:17080
curl -sS http://localhost:17080/ext/services/prusalink/healthz
curl -sS http://localhost:17080/ext/services/prusalink/v1/status
```

**Stop:** `q` in the mock, `Ctrl-C` in the monitor. The cluster and service keep
running; the stored models stay until the container restarts.

**Without the cluster** (the service as a plain process):
`bazel run //services/prusalink:prusalink_server` (it finds the mock on
`127.0.0.1`), then `curl http://127.0.0.1:18080/v1/model`.

## `gcode_to_stl`

```bash
python3 tools/printer/gcode_to_stl.py job.bgcode --out job_toolpaths
```

Every extruded move becomes a box (length x `;WIDTH:` x `;HEIGHT:`), grouped
by `;TYPE:`. Coordinates are the printer's bed frame (mm).

### What it writes: the model and its supports

| File | Contents | Use |
| --- | --- | --- |
| `compound.stl` | every type except `--exclude` (default `Custom`, the purge line): part **and** supports **and** brim | what is physically on the bed |
| `part.stl` | the designed object only: no supports, brim/skirt, wipe tower or purge | the shape to train a pose model on |
| `supports.stl` | `Support material` + `Support material interface` only | where supports are, e.g. to know what to break away |
| `by_type/<type>.stl` | one file per `;TYPE:` (`perimeter`, `external_perimeter`, `solid_infill`, `support_material`, ...) | inspect or combine types yourself |
| `summary.json` | per type: segments, triangles, volume, bounds, `included`; plus `part`, `supports` and `compound` totals, layers, warnings | check what a job contained |

`part.stl` and `supports.stl` exist only when the job has such extrusions
(a print without supports has no `supports.stl`). Supports come from the
slicer's own `;TYPE:` label, so nothing is guessed: a support is whatever the
slicer printed as support. The two files add up with the brim/skirt to
`compound.stl`.

Through the service the same files are served per job:
`/v1/jobs/<id>/model.stl` (= `compound.stl`), `part.stl`, `supports.stl` and
`by_type/<type>.stl`; on disk they are in
`<storage>/jobs/<id>_<name>/`.

* Reads ASCII and binary G-code (libbgcode v1; heatshrink and MeatPack are
  decoded in pure Python). Standard library only.
* Follows G2/G3 arcs (the Core One profile emits thousands), absolute and
  relative extrusion, and MeatPack lines with the spaces removed. Skips the
  `;MOVING_UNRETRACT_START/END` moves PrusaSlicer 3.x adds around wipe-tower
  de-retraction.
* It is an envelope of the plastic at toolpath resolution, not the designer's
  mesh: layer-stepped, detail below the nozzle width is lost, boxes of
  neighbouring paths overlap (no boolean union), and the file is large (33 MB
  for a 25k-triangle model). It has no model frame, so the pose against the
  source STL cannot come from G-code alone.
* **One compound for the whole job.** Objects are not separated; see
  "Limits" below.

Checked on a real Core One L job: binary and ASCII exports give identical
toolpaths, and the model's solid types add up to within 1% of the STL's
volume.

## Limits

* **Several objects on the bed:** all are in one `compound.stl` / `part.stl`,
  with their supports in `supports.stl`. Nothing separates them yet. If the slicer labelled objects
  (`; printing object <name> id:N copy M` for OctoPrint style, `M486` for
  firmware style) the G-code says which extrusion belongs to which; the
  tools do not use it yet.
* **One exported model that is really several bodies:** the slicer treats it
  as one object, so there is no label to split on. Separating the pieces
  would need clustering of the toolpaths by connectivity; not built.
* Brim, skirt and purge lines are in the G-code (and in `by_type/`), but the
  purge line is excluded from the compound by default.
