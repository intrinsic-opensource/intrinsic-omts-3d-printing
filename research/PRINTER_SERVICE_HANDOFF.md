# Printer service handoff: PrusaLink service, job models and skills

Status and plan for the printer-side service work on `feat/prusalink-skills`
(service `ai.omts.prusalink`, the four `ai.omts.*` printer skills, the mock
printer, and the G-code to STL converter). It was split out of
`research/HANDOFF.md` (sections 5e, 5f and part of 7) so that this branch does
not edit that file. The reBot cell plan stays in `HANDOFF.md`.

How to run it: [`tools/printer/README.md`](../tools/printer/README.md) (step by
step, after a reboot). The service: [`services/prusalink/README.md`](../services/prusalink/README.md).
The mock: [`tools/mock_printer/README.md`](../tools/mock_printer/README.md).

## 1. What exists

Goal: while a print runs, know what is printed (shape, supports) and when the
part can be unloaded, using only what the printer itself reports. The printer
is the only part guaranteed to be in the system, so nothing depends on a
slicer or its project files.

```
G-code sent to the printer -> printer prints as usual
  -> service polls GET /api/v1/job, downloads each new job, checks it is
     G-code, converts it to an STL, serves it
  -> skills read printer state and model state
```

* **Service** (`services/prusalink`, part of `//:rebot_solution`, on by
  default; `--no//:printer_service` leaves it out). Reads the printer given by
  `--//:printer_url`, `--//:printer_username`, `--//:printer_password`, or,
  with none, the mock found on the cluster's host; the route is logged and in
  `/healthz`. `JobWatcher` polls every 2 s; a job not read before (job id,
  name, size, file time) is downloaded from `file.refs.download` into
  `<storage>/jobs/<id>_<name>/`. Same content (SHA-256) copies the earlier
  conversion (`reused: true`); a file that is not G-code ends as
  `MODEL_FAILED`; a restart does not re-read converted jobs.
* **Served files** per job: `model.stl` (= `compound.stl`, everything printed
  except the purge line), `part.stl` (the designed object: no supports, brim,
  skirt or wipe tower), `supports.stl`, and `by_type/<type>.stl`. Supports are
  whatever the slicer labelled `;TYPE:Support material*`.
* **Skills** (read-only, never move a robot): `read_printer_status`,
  `wait_for_printer_ready` (`FINISHED` and bed strictly below 30 C; the 30 C is
  a placeholder, not a Prusa value), `read_job_model`, `wait_for_job_model`.
  PrusaLink has no `print_finished` or `ready_for_unload`; the service computes
  them. Readiness is never latched; observations older than 10 s are rejected.
* **`tools/printer/gcode_to_stl.py`.** Rebuilds an STL from `.gcode` or
  `.bgcode` alone: each extrusion becomes a box (length x `;WIDTH:` x
  `;HEIGHT:`), grouped by `;TYPE:`. Decodes binary G-code (heatshrink and
  MeatPack) in pure Python; follows G2/G3 arcs. On a real Core One L job,
  binary and ASCII exports gave identical toolpaths (56,088 segments, 153
  layers) and the solid types summed to about 514 mm3 against the source STL's
  518.9 mm3.
* **Mock printer** (`tools/mock_printer`): one file, standard library, live
  screen, 7 s print and 7 s cooling by default, spec-conformant uploads (409
  while printing, `Overwrite`). Printing time stops when the job finishes.
  Checked against Prusa's OpenAPI text, not a real printer.
* **`tools/printer/printer_skills.py`.** Runs the skills through the
  Executive; `--mode=monitor` is a live screen.
* **Skill allowlist patch.** The pinned SDK refuses new skill manifests that
  declare equipment unless they are in `skill_manifest_deps`;
  `bazel/patches/printer_skill_dependencies.patch` adds the four manifests.
  See section 5.

## 2. Verified

On the local k3s cluster, after a redeploy, with the mock only:

* The service found the mock at the pod's gateway `10.42.0.1:18081`.
* `wait_for_job_model` returned READY with the STL (33.6 MB, 153 layers) after
  one `curl` upload; `wait_for_printer_ready` returned READY after the job
  finished and cooled; the STL was fetched through the ingress.
* A resend was `reused`; a non-G-code file gave `MODEL_FAILED` and the wait
  failed; a stopped mock gave `printer_not_found` (502) with the model still
  served, and the service recovered when the mock returned.
* After a reboot the cluster came back by itself with the service deployed;
  the mock and the monitor were started again by hand. A stuck Executive
  (about 1 CPU, no log lines, every skill call blocked) was fixed by
  `kubectl rollout restart deploy/executive -n app-intrinsic-app-chart`; the
  cause was not found.
* `bazel build --nobuild //...` and `bazel test //tests/...` pass (29 targets).
  `ruff` and `buildifier` were not run (not installed on the dev machine).

## 3. Error handling

Rules the service follows, checked in an audit of every `except` in the
service, converter and skills:

* The downloaded file is untrusted. Damaged `.bgcode` input raises only
  `ValueError` from the converter (library errors such as `zlib.error` and
  `struct.error` are converted); inflating a block is bounded by the size the
  block declares. Whatever else a bad file breaks, `JobWatcher` still ends the
  job as `MODEL_FAILED` with the error type, so it is never left in
  `DOWNLOADING` or `CONVERTING` and skills do not wait on it.
* A dropped connection (502, 504) is retried on the next poll; every other
  failure is permanent for that job (a resend is a new job).
* Our own disk (full, read-only, no permission) is `local_storage_error`
  (500), not "printer unreachable", and does not make the service look for the
  mock again.
* An unexpected error in an HTTP handler answers 500 `internal_error`, and in a
  gRPC handler `INTERNAL`; it never drops the call. A caller that leaves while
  a model is streamed is ignored.
* The watcher thread outlives any single bad poll; an unexpected poll error is
  shown in `poll_error`.
* Discovery treats a server that does not speak HTTP on the mock's port as
  "not the mock".

## 4. Unverified, and not built

Check before building on them.

* **Mock vs a real PrusaLink.** Unchecked on a real printer: the
  `refs.download` path form, the Digest realm, whether `FINISHED` accepts a new
  job before it is cleared, 8.3 short `file.name`, and the status/job bodies in
  `FINISHED` (does `job` stay present?).
* **Pulling a job's G-code from a real Core One**, once, with a job running:
  * that `GET /api/v1/job` lists `file.refs.download` and the path serves the
    file (Prusa's spec gives `/api/files/local/<name>/raw`; the file `GET`
    returns metadata only), and on which firmware;
  * that the downloaded bytes equal what was sent (compare SHA-256);
  * how soon after the job starts the file can be downloaded;
  * what happens when the job was started from USB or the printer's own
    storage, and whether the file is still there after the print;
  * that a real `.bgcode` from the printer decodes (only one encoder's output
    has been tried);
  * that the Digest login covers the download.
* **A real printer behind the cluster.** The `--//:printer_url` route (real
  Digest login, a printer on another machine) was built and unit-tested but
  never run against hardware. A password as a secret has no path into the
  cluster (`password_env`); the flag writes it into the solution config, so it
  is for test credentials only.
* **Large jobs through the cluster.** Only a 600 KB job was pulled; the limit is
  256 MiB and the STL is about 55 times the G-code size.
* **Newer slicer output.** G-code from slicer 3.x was read from source only: the
  `;TYPE:`, `;WIDTH:`, `;HEIGHT:` tags are unchanged, and
  `;MOVING_UNRETRACT_START/END` (skipped by the parser) is new. No such file
  was converted.
* **Several objects, or one model of several bodies.** Not separated: one
  compound per job. Object labels in the G-code (`; printing object <name>
  id:N copy M`, or `M486`) could split objects when the slicer emits them;
  bodies inside one object have no label. `; objects_info` exists only in
  ASCII G-code, not in the `.bgcode` a Core One receives.
* **Model fidelity.** A layer-stepped envelope at toolpath resolution, not the
  designer's mesh; boxes overlap; large files; no model frame, so the pose
  against a source STL cannot come from G-code alone.
* **Persistence.** The storage is the service pod's filesystem, so models are
  lost when the pod restarts. k3s has a local-path provisioner; a volume at
  `--storage-dir` would keep them, but whether the service manifest allows one
  was not checked. The pod image has no shell or `tar`, so files can only be
  fetched through the service's HTTP routes.
* **Not built:** feeding the STL to pose-model training or into the world as a
  scene object, and a guarded behavior `wait_for_job_model` -> consume ->
  `wait_for_printer_ready` -> unload, with a persistent per-job guard and a
  fresh recheck. `omts_app` is **not** printer-gated.

## 5. The allowlist patch

`printer_skill_dependencies.patch` edits `skill_manifest_deps` in
`@intrinsic-core//intrinsic/assets/build_defs/allowlists.bzl`. It is a
stopgap on Core internals:

* Core's comment says manifest `dependencies` (`required_equipment`) are to be
  replaced by dependencies declared in the skill's parameter. At the pinned
  commit (`50927e35`) no skill in Core uses that model, and the Python skill
  API only exposes `resource_handles` built from the manifest's
  `required_equipment`, so moving the four manifests is not possible yet, not
  small.
* The check matches `//<package>:<name>` with no repository name, so the
  entries are looser than they look.
* The patch has about three lines of context. A pin bump that edits the list
  near `preplan_motion_manifest` or the `keep-sorted end` marker breaks module
  resolution. `MODULE.bazel` says to re-check it on every bump. When a pin
  offers the parameter-based model: move `skills/printer/*.manifest.textproto`
  to it, set `incompatible_disallow_manifest_dependencies = True` in
  `skills/printer/BUILD`, and delete the patch, its `exports_files` entry and
  its `MODULE.bazel` line.
* `bazel build --nobuild //...` after any bump catches a stale label or a
  patch that no longer applies.

## 6. Next small demos

1. Persist the models (volume, or save to a host path through the HTTP route).
2. The guarded behavior in section 4.
3. The real printer, with the checks in section 4.
