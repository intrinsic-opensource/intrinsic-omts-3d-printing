# PrusaLink LAN service

Intrinsic service asset **`ai.omts.prusalink`**, instance **`prusalink`**. It is
part of `//:rebot_solution` (on by default) and does two things with the
printer's PrusaLink API:

1. **Telemetry**: status and current job, for the skills
   `ai.omts.read_printer_status` / `wait_for_printer_ready`. It computes
   `print_finished` and `ready_for_unload` itself (PrusaLink has neither):
   `ready_for_unload` is true only for `state == FINISHED` with a bed
   temperature below 30 °C. The 30 °C is a placeholder, not a Prusa value.
2. **Job model**: every new job the printer reports is downloaded (G-code or
   bgcode), checked, and converted to an STL, for the skills
   `ai.omts.read_job_model` / `wait_for_job_model`.

```
 slicer / curl ──► PRINTER (real, or tools/mock_printer)          machine A
                         ▲  poll GET /api/v1/job every 2 s
                         │  GET <file.refs.download>             (HTTP, Digest)
 ───────────────────────┼────────────────────────────────────────────────────
                         │                                        machine B
   PRUSALINK SERVICE (container in the cluster)
     JobWatcher: new job id? ─► download ─► gcode_to_stl ─► <storage>/jobs/<id>_<name>/
     HTTP + gRPC:  status, job, model status, model.stl
                         ▲
   SKILLS (Executive) ───┘  read_printer_status  wait_for_printer_ready
                            read_job_model      wait_for_job_model
```

The printer never calls the service: PrusaLink has no push. The service polls.

## Which printer it reads

| Given | Route | Log line |
| --- | --- | --- |
| a printer URL | that printer, with the given username and password | `ROUTE: printer http://… as user '…' (explicitly configured)` |
| nothing | the mock printer (`tools/mock_printer`), searched on this machine | `ROUTE: mock printer found at http://…` / `ROUTE: no printer configured and no mock printer found at …; still looking` |

The mock is searched at `127.0.0.1`, the container's default gateway (the host,
from inside a k3s pod: `10.42.0.1`), `host.docker.internal` and
`host.containers.internal`, port `18081`. Only a server that answers with a
Digest challenge for the realm `PrusaLink mock` counts, so a real printer or
any other web server is never mistaken for it. If it is not up yet, or stops
answering, the service keeps looking and recovers when it comes back. The route
taken is in the log and in `GET /healthz` (`route`, `printer_url`).

**In the cluster** the printer is set when the solution is built:

```bash
bazel run //:rebot_solution -c opt \
  --//:printer_url=http://192.168.1.50 --//:printer_username=maker \
  --//:printer_password=<digest password> -- --address=localhost:17080
```

With none of these the service looks for the mock. `--no//:printer_service`
leaves the service and its skills out of the solution. The password flag
writes the password into the solution's config (the asset bundle); use it for
test credentials only. A secret-managed delivery (`password_env`) exists but
has no delivery path into the cluster yet.

**Running the binary directly** (no cluster), same choices as arguments:

```bash
bazel run //services/prusalink:prusalink_server -- \
  [--printer-url=http://192.168.1.50 --username=maker --password=… \
   | --password-env=PRUSALINK_PASSWORD] \
  [--storage-dir=/tmp/prusalink] [--poll-interval=2] [--max-download-mb=256] \
  [--no-job-pull] [--enable-job-commands] \
  [--mock-port=18081] [--mock-host=HOST ...] \
  [--http-port=18080] [--grpc-port=18082] [--host=127.0.0.1]
```

## Where the model goes, and what happens on a resend

Each job gets a folder in the service's storage
(`<storage-dir>/jobs/<job id>_<file name>/`, default `/tmp/prusalink`, inside
the container in a cluster, so it is lost when the container restarts; jobs
converted before a restart are recognized on startup and not read again):

```
compound.stl      everything printed except Custom (start lines): part + supports + brim
part.stl          the designed object only (no supports, brim, wipe tower)
supports.stl      the support structures only (when the job has any)
by_type/*.stl     one STL per extrusion type (perimeters, infill, supports, ...)
job.bgcode|gcode  the downloaded file
job.json          job id, name, size, sha256, layers, reused, warnings
summary.json      volumes and bounds per type
```

It is served at `GET /v1/jobs/<id>/model.stl` (on the cluster ingress:
`http://localhost:17080/ext/services/prusalink/v1/jobs/<id>/model.stl`), and the
skills and gRPC clients get its path and state (`ModelStatus`).

- **A new job** is recognized by its job id, file name and size. A job is read
  once; polling the same job again does nothing.
- **The same model sent again** gets a new job id on the printer, so it is a
  new job here: read again, with its own folder. When the file's content
  (SHA-256) equals an earlier one, the earlier conversion is copied and the
  record says `reused: true`, so the conversion runs once.
- **A job that is not G-code** (wrong extension, no extrusion moves, corrupt
  bgcode, larger than `--max-download-mb`) ends as `MODEL_FAILED` with the
  reason; it is not retried. A dropped connection is retried on the next poll.
- The model is a layer-stepped envelope rebuilt from the toolpaths, not the
  designer's mesh. See [`tools/printer/README.md`](../../tools/printer/README.md).

## HTTP and gRPC contract

| HTTP | gRPC | Behavior |
| --- | --- | --- |
| `GET /healthz` | — | Liveness, route, printer URL, storage, command and pull flags |
| `GET /v1/status` | `GetStatus(Empty)` | Fresh state, temperatures, job id/progress, `print_finished`, `ready_for_unload`, observation time |
| `GET /v1/job` | `GetJob(Empty)` | Current job; upstream 204 becomes `has_job: false` |
| `GET /v1/model` | `GetModelStatus(ModelRequest)` | The newest job's model: `NO_JOB`, `DOWNLOADING`, `CONVERTING`, `MODEL_READY`, `MODEL_FAILED` |
| `GET /v1/jobs` | `ListModels(Empty)` | Every job read since the service started |
| `GET /v1/jobs/{id}/model` | `GetModelStatus(job_id)` | That job's model (404 if never seen) |
| `GET /v1/jobs/{id}/model.stl`, `.../part.stl`, `.../supports.stl`, `.../by_type/{type}.stl` | — | The STL (`model/stl`) |
| `POST /v1/jobs/{id}/pause\|resume\|stop\|continue` | `CommandJob(JobCommand)` | Job commands; off unless enabled, HTTP 403 otherwise |

HTTP results are protobuf JSON with snake_case names; `int64` ids and times are
strings; absent optionals are omitted, not zero. Upstream 404/409 are kept;
authentication failures, an unreachable printer and bad telemetry are 502/504;
`printer_not_found` (502) means no printer is configured and no mock was found.
With `--no-job-pull` the model routes answer 409 `job_pull_disabled`.
Both interfaces are unauthenticated; do not expose them beyond a trusted
network. Printer requests bypass proxy settings and reject redirects.

## Skills

All four bind the service with capability `omts.prusalink.PrusaLinkService`
and a READ lease, and never move a robot or touch the world.

| Skill | Returns |
| --- | --- |
| `ai.omts.read_printer_status` | `decision`: `WAITING_FOR_PRINT`, `WAITING_FOR_COOLING`, `TEMPERATURE_UNAVAILABLE`, `PRINTER_BLOCKED`, `JOB_MISMATCH`, `JOB_UNKNOWN`, `READY_TO_UNLOAD`; `ready_for_unload`. Optional `expected_job_id`. |
| `ai.omts.wait_for_printer_ready` | Polls the above until `READY_TO_UNLOAD` (`READY`) or the timeout (`TIMED_OUT`). Requires `expected_job_id`. Fails on a blocked printer or a changed job. |
| `ai.omts.read_job_model` | `decision`: `NO_JOB`, `DOWNLOADING`, `CONVERTING`, `MODEL_READY`, `MODEL_FAILED`; `model_ready`; the `ModelStatus` with the STL path. Optional `expected_job_id` (that job's model even if a newer job started). |
| `ai.omts.wait_for_job_model` | Polls until `MODEL_READY` (`READY`) or the timeout. Optional `expected_job_id`, and `after_job_id` to wait for a job newer than one already handled. Fails on `MODEL_FAILED`. |

A process chain: `wait_for_job_model` (start the next process when the model of
a new job exists) ... `wait_for_printer_ready(expected_job_id = that job)`
(start unloading). Readiness is never latched: every call is a fresh reading,
and observations older than 10 s are rejected.

The SDK pinned here disallows new skill manifests that declare equipment unless
they are allowlisted; [`printer_skill_dependencies.patch`](../../bazel/patches/printer_skill_dependencies.patch)
lists these four. Remove it when moving to a supported dependency model.

## Test and run

```bash
bazel test --test_output=errors //tests/unit:test_prusalink \
  //tests/unit:test_jobwatch //tests/unit:test_discovery \
  //tests/unit:test_mock_printer //tests/unit:test_printer_skills \
  //tests/unit:test_job_model_skills //tests/unit:test_gcode_to_stl
```

The step-by-step run (mock printer, service, skills, what to watch) is in
[`tools/printer/README.md`](../../tools/printer/README.md); the mock itself in
[`tools/mock_printer/README.md`](../../tools/mock_printer/README.md).

Not verified on a real printer: that a Core One serves `file.refs.download`
(and in what form) while printing, its Digest realm, which state a new upload
is accepted in, and the status/job bodies in `FINISHED`. Not covered:
several objects or several bodies in one job (one merged model), and
PrusaSlicer 3.x output. See `research/HANDOFF.md` §7.
