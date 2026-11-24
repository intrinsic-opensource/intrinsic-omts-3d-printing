# From the printer's G-code to a model, and the skills that report it (`tools/printer/`)

Goal: while a print runs, know what it deposits (shape, supports, bed
position), to train a pose model for the finished part. The printer is the only
part guaranteed to be in the system, so everything starts from what the printer
receives. Plan and status: `research/PRINTER_SERVICE_HANDOFF.md`.

| Tool | Target | What it does |
| :--- | :--- | :--- |
| `mock_printer` | `python3 tools/mock_printer/mock_printer.py` | A disposable fake PrusaLink printer with a live screen. [README](../mock_printer/README.md). |
| `gcode_to_stl.py` | `//tools/printer:gcode_to_stl` | G-code or bgcode to a compound STL. The PrusaLink service runs it on every new job; also usable by hand. |
| `printer_skills` | `//tools/printer:printer_skills` | Runs the four printer skills through the Executive (no robot motion); `--mode=monitor` is a live screen of both read skills. |

## Door (simulation only)

Real-printer behavior is unverified. `tools/printer/demo_open_door.sh
[target_deg]` runs the whole sequence below (default target 115 deg; the
arm's reach ends near 120). Tools: `open_door` (`--mode
look|detect|discover|approach|pull|entities|joints`; `--path blended|stepwise`; `--chunk_deg`, `--wp_deg`; `--az_mode
radial|fixed`; `--belief_door_at end|start`; `--no_belief_door`), `sync_door`
(Gazebo's door and crank angles into the belief world; `--rate_hz`,
`--min_change_deg`, `--duration`) and `control_door` (`--action
open|close|set|status`, `--theta_deg`, `--reset_sim`). Design and results:
`research/HANDOFF.md` 5e.

### Step by step

The hinge is passive, so right after a deploy Gazebo shows the door **open**
(the SDF's joint position 0); step 3 resets Gazebo to the belief world and
closes it. Run everything from the repository root in one shell, except the GUI
(step 4), which needs its own terminal. Steps 7 and 9 run in the background of
that shell.

```bash
# 0. Once per shell
export GZ_PARTITION=intrinsic_sim GZ_IP=10.42.0.1
export GZ_RELAY=$(kubectl get pod -n app-resources rs-gazebo-simulator-0 -o jsonpath='{.status.podIP}')
A=--address=localhost:17080

# 1. Deploy: door closed in the belief world, passive hinge, printer at d 0.80, 0.2 m left
bazel run //:rebot_solution -c opt --//models/printer:door=closed \
  --//models/printer:hinge=passive --//models/printer:layout=door_test -- $A

# 2. Build the tools
bazel build //tools/printer:open_door //tools/printer:sync_door \
  //tools/printer:control_door //research/tools:door_angle \
  //tools/world:apply_scene_updates

# 3. Reset Gazebo to the deployed layout (a deploy alone does not move it)
bazel-bin/tools/world/apply_scene_updates $A --reset_sim \
  --files configs/rebot/printer_door_test.updates.pbtxt \
          configs/rebot/printer_door_closed.updates.pbtxt

# 4. Gazebo GUI, in its own terminal (with the GZ_* exports of step 0), after
#    the reset: a GUI open during the reset mis-draws the scene
pkill -f 'gz-sim-main -g'; pkill -f gz-sim-gui-client; sleep 1; gz sim -g

# 5. Look pose
bazel-bin/tools/printer/open_door $A --mode=look \
  --joints 0.3055 -1.2202 -1.4196 0.1996 -0.0436 -1.5708

# 6. Find the printer from the marker: PRINTER DETECTED, or a NOT DETECTED
#    banner and exit code 3
bazel-bin/tools/printer/open_door $A --mode=discover

# 7. Keep the belief door in step with Gazebo (background; stop it in step 10)
bazel-bin/tools/printer/sync_door $A > /tmp/sync.log 2>&1 &
SYNC=$!

# 8. Record Gazebo's poses (background)
gz topic -e -t /world/default/pose/info --json-output > /tmp/poses.jsonl &
REC=$!

# 9. Grab the crank, open the door, release and retreat (--hold keeps the grip;
#    --chunk_deg=12 swings stepwise instead of in one call)
bazel-bin/tools/printer/open_door $A --mode=pull --target_deg=115 \
  --no_belief_door --path=blended --chunk_deg=115 --wp_deg=3

# 10. Stop the background jobs and read the result
sleep 3; kill $SYNC $REC
bazel-bin/research/tools/door_angle /tmp/poses.jsonl --every 100000
bazel-bin/tools/printer/control_door $A --action=status   # belief door_hinge
```

If a pull fails, it prints the planner's reason. `--mode=entities` and
`--mode=joints` dump the world and the joint positions.

## The flow

```
 you (curl, or any sender of G-code)
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

**Terminal 4: send the job.** Any G-code or bgcode works; the
original file stays where it is and is only read. This one is a test fixture:

```bash
F=tests/unit/testdata/prusaslicer_2_9_7_part.bgcode   # from the repo root
curl --digest -u maker:mock-only -sS -w "HTTP %{http_code}\n" -X PUT \
  -H 'Print-After-Upload: ?1' -H 'Overwrite: ?1' -T "$F" \
  http://localhost:18081/api/v1/files/local/part.bgcode
```

Expect `HTTP 201`. What you see, within a few seconds:

1. Terminal 1: `PRINTING`, job 1, the progress bar moving for 7 s, then
   `FINISHED`, the bed cooling from 60 to 24 °C over 7 s.
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

## After a reboot

The cluster (k3s) and Docker start by themselves and the deployed solution
comes back (about 5 minutes; wait until `kubectl get pods -A` shows no
`0/1`). Jobs the service had converted are lost (its storage is in the pod).
The mock and the monitor are not services: start them again.

| Terminal | Folder | Command |
| --- | --- | --- |
| 1 | `~/gits/intrinsic-omts` | `python3 tools/mock_printer/mock_printer.py` (leave open, live screen) |
| 2 | `~/gits/intrinsic-omts` | `bazel run //tools/printer:printer_skills -- --address=localhost:17080 --mode=monitor` |

Checks, in order: `kubectl get pods -A | grep -v Running` shows nothing
(except the header); `curl -s localhost:17080/ext/services/prusalink/healthz`
answers `"route": "mock"` and a `printer_url` once terminal 1 is up (a few
seconds); the monitor shows `IDLE`, `NO_JOB`. Then send a job (the curl
step above); terminal 1 shows the upload and `PRINTING`, the monitor goes `WAITING_FOR_PRINT` -> `READY_TO_UNLOAD` and `MODEL_READY`.

Redeploy only if the cluster was reset or the code changed:
`bazel run //:rebot_solution -c opt -- --address=localhost:17080`.
If a skill call hangs with no output, the Executive is stuck (it spins at
~1 CPU and logs nothing): `kubectl rollout restart deploy/executive -n
app-intrinsic-app-chart`.
