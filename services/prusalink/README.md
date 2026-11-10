# PrusaLink LAN service

Intrinsic service asset **`ai.omts.prusalink`**, instance **`prusalink`**.
Reads PrusaLink v1 telemetry over HTTP Digest and exposes HTTP for `curl` and
typed gRPC for the printer skills. No physical printer, cloud connection, or
perception models are needed for the telemetry/skill demo.

The implemented subset follows the supplied official PrusaLink OpenAPI
`1.0.0-draft`: status, current job, and pause/resume/stop/continue by job ID.
File upload, starting prints, arbitrary G-code, and automatic robot picking are **not**
implemented. Compatibility with physical Core One firmware is not yet verified;
the supplied contract uses Digest authentication.

Development branch: `feat/prusalink-skills`, created from
`origin/rebot-parameters`. The walkthrough below runs from that local branch.

## Run with the reBot: five terminals

`//:rebot_solution` includes both the PrusaLink service asset and its configured
`prusalink` instance and both printer skills. **Deploy only rebot_solution**, not a second printer-only
solution. Intrinsic has one active solution per cluster: a solution declares the
complete set of assets/instances to deploy, rather than adding to the previous
solution. The reBot and PrusaLink now belong to that same deployment.

All printer traffic goes to a separate loopback mock HTTP listener inside the
service container. It verifies real Digest challenges and responses; the client
does not return hard-coded telemetry or silently switch to a mock on failure.
The mock starts automatically with the service; do not launch a local server
alongside the deployed solution.

This walkthrough runs real `read_printer_status` and `wait_for_printer_ready`
skills through the Executive, but **never moves the robot**. Do not run
`omts_app` alongside it: the existing app does **not** wait for PrusaLink and
must not be used to demonstrate that gating. Only one demo Executive operation
may run at a time; stop `watch` before starting `wait`.

### Terminal 1: deploy the reBot and service together

Run from the repository root:

```bash
cd /home/berti/gits/intrinsic-omts
inctl asset instance list --address localhost:17080
bazel run //:rebot_solution -c opt -- \
  --address=localhost:17080 --operation_mode=sim
inctl service state list --address localhost:17080
inctl skill list --address localhost:17080 | grep ai.omts
```

An empty cluster may report "no current application" on the first inspection.
If another solution is active, deploying replaces it; never replace an active
hardware cell without authorization. Wait for deployment to finish and for
`prusalink` to report `State: Enabled`. The deployment command exits; Kubernetes
keeps the service running, so this terminal can be reused.

If the reBot with PrusaLink is **already running**, as in the previous service
walkthrough, skip redeployment and install just the new skills:

```bash
bazel build //skills/printer:read_printer_status \
  //skills/printer:wait_for_printer_ready
inctl skill install bazel-bin/skills/printer/read_printer_status.bundle.tar \
  --address localhost:17080
inctl skill install bazel-bin/skills/printer/wait_for_printer_ready.bundle.tar \
  --address localhost:17080
inctl skill list --address localhost:17080 | grep ai.omts
```

These installs do not replace the reBot cell or reset mock values. They are
unnecessary after deploying the updated `rebot_solution`, which includes them.

This command does not export/load the optional perception models: printer
telemetry needs none. The pose estimator may be unavailable without its models;
that does not prevent this PrusaLink-only exercise. If you already use the full
reBot perception deployment, use its existing `--//:perception_models` and
`--repo_env=NVIDIA_POSE_ESTIMATOR_MODELS_DIR=...` flags instead, as documented in
the [reBot guide](../../research/REBOT_OMTS_APP.md#3-deploy); it also includes
PrusaLink. Do not start the app for this exercise.

### Terminal 2: watch the service, not the printer

```bash
watch -n 2 'inctl service state list --address localhost:17080; curl -sS --max-time 3 -w "\nHTTP %{http_code}\n" http://localhost:17080/ext/services/prusalink/healthz'
```

`State: Enabled` is the Intrinsic service lifecycle state. `/healthz` reports
listener liveness, `mode: sim`, and whether commands are enabled. It is
deliberately **not** a printer connectivity check: an upstream printer fault
does not mean the service process itself has stopped.

Leave this running. `Ctrl-C` stops watching, not the service.

### Terminal 3: watch printer telemetry (the skills' input)

```bash
watch -n 1 'curl -sS --max-time 3 -w "\nHTTP %{http_code}\n" http://localhost:17080/ext/services/prusalink/v1/status'
```

Watch `state`, `bed_temperature_c`, `print_finished`, and `ready_for_unload`.
This is the service's **fresh reading of the mock printer**, not the service's
own health. Each request queries the upstream mock through the same Digest
client used for a LAN printer. Leave this running while using terminal 4.

### Terminal 4: control the mock and send commands through the service

Define `BASE` in **this terminal** (shell variables are not shared):

```bash
BASE=http://localhost:17080/ext/services/prusalink

# Optional: inspect the current job.
curl -fsS "$BASE/v1/job"
```

The initial mock job is `42`, `PRINTING`, bed `60 °C`. There is no automatic
time progression: use the simulation controls to reproduce each condition.

```bash
# HTTP 204, followed by PAUSED telemetry.
curl -i -X POST "$BASE/v1/jobs/42/pause"
curl -fsS "$BASE/v1/status"
curl -i -X POST "$BASE/v1/jobs/42/resume"

# Finished, but still too hot: ready_for_unload is false at EXACTLY 30 °C.
curl -fsS -X POST "$BASE/simulation/state" \
  -H 'Content-Type: application/json' \
  -d '{"state":"FINISHED","temp_bed":30}'
curl -fsS "$BASE/v1/status"

# Finished and cool: ready_for_unload is true.
curl -fsS -X POST "$BASE/simulation/state" \
  -H 'Content-Type: application/json' -d '{"temp_bed":29}'
curl -fsS "$BASE/v1/status"

# Missing temperature must never imply that unloading is available.
curl -fsS -X POST "$BASE/simulation/state" \
  -H 'Content-Type: application/json' -d '{"temp_bed":null}'
curl -fsS "$BASE/v1/status"

# Simulate an upstream fault: service returns HTTP 502, not stale telemetry.
curl -fsS -X POST "$BASE/simulation/state" \
  -H 'Content-Type: application/json' -d '{"failure":500}'
curl -i "$BASE/v1/status"

# Reset the demo (also clears injected failures).
curl -fsS -X POST "$BASE/simulation/state" \
  -H 'Content-Type: application/json' \
  -d '{"state":"PRINTING","temp_bed":60,"job_id":42,"failure":null}'
```

Terminal 3 shows these expected decisions:

| Mock condition | `print_finished` | `ready_for_unload` | Read skill `decision` |
| --- | --- | --- | --- |
| `PRINTING`, 60 degrees | false | false | `WAITING_FOR_PRINT` |
| `PAUSED`, any temperature | false | false | `WAITING_FOR_PRINT` |
| `FINISHED`, 30 degrees | true | false | `WAITING_FOR_COOLING` |
| `FINISHED`, 29 degrees | true | true | `READY_TO_UNLOAD` |
| `FINISHED`, missing temperature | true | false | `TEMPERATURE_UNAVAILABLE` |
| Injected upstream 500 | HTTP 502 error, no status | No valid readiness result | Execution fails; never reuse an old `true` |

During the injected failure, terminal 2 should still show the service healthy
while terminal 3 shows HTTP 502 and an explicit error. Clearing `failure`
restores fresh telemetry. All mock state is in memory and resets when the
service restarts/redeploys; it is not the Gazebo printer model's state.

### Terminal 5: see actual skill execution and changing results

Run from the repository root in this terminal too:

```bash
cd /home/berti/gits/intrinsic-omts
bazel run //tools/printer:printer_skills -- \
  --address=localhost:17080 --mode=watch --job-id=42 --interval=1
```

Leave it running and repeat the commands from terminal 4. Every sample is a
**new Executive invocation** of `ai.omts.read_printer_status`, not a local
calculation pretending to be a skill. It prints execution state and the typed
result, for example:

```json
{"skill": "watch", "execution_state": "SUCCEEDED"}
{
  "printer_status": {"state": "FINISHED", "bed_temperature_c": 30.0},
  "decision": "WAITING_FOR_COOLING",
  "outcome": "SNAPSHOT",
  "ready_for_unload": false
}
```

The result above is abbreviated. Execution `SUCCEEDED` means the read worked,
**not** that the printer is ready. `decision` and `ready_for_unload` express
readiness. Fast reads may finish before a `RUNNING` state is observed.
For a single sample use `--mode=read`; for a bounded watch add `--samples=5`.
On a service fault the command exits nonzero with the Executive error; fix the
mock and rerun it. The skill does not mask faults or reuse previous results.

#### Demonstrate one waiting skill: RUNNING -> READY

1. Stop terminal 5's watch with `Ctrl-C`.
2. In **terminal 4**, reset a known job:

   ```bash
   curl -fsS -X POST "$BASE/simulation/state" \
     -H 'Content-Type: application/json' \
     -d '{"state":"PRINTING","temp_bed":60,"job_id":42,"failure":null}'
   ```

3. In **terminal 5**, start the real waiting skill:

   ```bash
   bazel run //tools/printer:printer_skills -- \
     --address=localhost:17080 --mode=wait --job-id=42 \
     --timeout=120 --interval=1
   ```

   It prints `RUNNING` and stays there while the print is incomplete/hot.
   Terminal 3 continues showing fresh printer telemetry. Terminal 2 continues
   showing service health. These are three different kinds of status.

4. In **terminal 4**, finish the print at the exact boundary:

   ```bash
   curl -fsS -X POST "$BASE/simulation/state" \
     -H 'Content-Type: application/json' \
     -d '{"state":"FINISHED","temp_bed":30}'
   ```

   The wait remains `RUNNING`: 30 is not below 30.

5. In **terminal 4**, cool the bed:

   ```bash
   curl -fsS -X POST "$BASE/simulation/state" \
     -H 'Content-Type: application/json' -d '{"temp_bed":29}'
   ```

   Terminal 5 finishes with `execution_state: SUCCEEDED`, `outcome: READY`,
   `decision: READY_TO_UNLOAD`, and `ready_for_unload: true`.
   **No pick is executed.** Readiness is an advisory result.

#### Other wait outcomes

Reset in terminal 4 before each case, then start `--mode=wait` in terminal 5:

| Change in terminal 4 | Waiting skill behavior |
| --- | --- |
| Keep `PRINTING`, use `--timeout=5` | `SUCCEEDED`, `outcome: TIMED_OUT`, readiness false |
| `{"state":"FINISHED","temp_bed":null}` | Remains `RUNNING` until valid cooling or timeout |
| `{"state":"PAUSED"}` | Remains `RUNNING`; resuming alone does not mean finished |
| `{"state":"ERROR"}`, `STOPPED`, or `ATTENTION` | `FAILED`, printer-blocked skill error |
| `{"job_id":43}` or `{"job_id":null}` | `FAILED`, mismatched/missing job error |
| `{"failure":500}` | `FAILED`, PrusaLink service error |
| `Ctrl-C` in terminal 5 | Cancels this operation; leaves service and reBot deployed |

Use the same `curl -X POST "$BASE/simulation/state"` wrapper from above for
each JSON change. With the injected failure still set, clear it through this
simulation route (`{"failure":null}`), which remains available.

`TIMED_OUT` is a normal, explicit result with readiness false, not a printer
fault. A future behavior tree must test **`outcome == READY` and
`ready_for_unload`**, not merely whether the skill node succeeded. A wait is
bound to `--job-id`; it will never silently switch to a different job.

For service logs, optionally open **terminal 6**:

```bash
kubectl logs -n app-resources rs-prusalink-0 --tail=30 --follow
```

For skill process/container health use `kubectl get pods -n skills`.
Waiting-skill logs record decision changes. Find its container with
`kubectl get pods -n skills -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.spec.containers[*].name}{"\n"}{end}'`,
then `kubectl logs -n skills <pod> -c <container> --follow`.
Skill pods being `Running` means the skill server is available, not that an
invocation is executing; terminal 5 reports that invocation's state.

To finish, stop each watcher/log tail with `Ctrl-C`. This leaves the reBot
solution and service running. Only if you want to stop the **whole solution,
including the reBot**, run in terminal 1:

```bash
inctl solution stop --address localhost:17080
```

### Optional service-only deployment

`//services/prusalink:prusalink_solution` is retained for isolated service
development on an otherwise unused cluster. It does **not** extend the active
reBot solution; deploying it replaces the reBot deployment. Do not launch it
for the five-terminal workflow above. It does not include the printer skills.
`//:omts_solution` and `lab_bb_01` are
unchanged and do not include PrusaLink.

## Local demo without a cluster

```bash
bazel run //services/prusalink:prusalink_server -- \
  --mode=sim --enable-job-commands
```

In another terminal, use the same `curl` commands with
`BASE=http://127.0.0.1:18080`. HTTP is `18080`, mock PrusaLink is `18081`,
and gRPC is `18082`; override `--http-port`, `--mock-port`, and `--grpc-port`
if occupied. `Ctrl-C` or `SIGTERM` closes all listeners cleanly.

You can also test the simulated upstream directly:

```bash
curl --digest -u maker:mock-only http://127.0.0.1:18081/api/v1/status
```

These credentials are **mock-only constants**, not printer credentials.
The mock listener is always loopback-only. It is not exposed by Intrinsic
ingress; use `/simulation/state` there.

## HTTP and gRPC contract

| HTTP | gRPC | Behavior |
| --- | --- | --- |
| `GET /healthz` | — | Listener liveness, mode, command flag; does not assert printer connectivity |
| `GET /v1/status` | `GetStatus(Empty)` | Fresh status, temperatures, optional job ID/progress, observation timestamp |
| `GET /v1/job` | `GetJob(Empty)` | Current job; upstream HTTP 204 becomes `has_job: false` |
| `POST /v1/jobs/{id}/pause` | `CommandJob(JobCommand)` | Upstream `PUT /api/v1/job/{id}/pause` |
| `POST /v1/jobs/{id}/resume` | `CommandJob(JobCommand)` | Upstream `PUT /api/v1/job/{id}/resume` |
| `POST /v1/jobs/{id}/stop` | `CommandJob(JobCommand)` | Upstream `DELETE /api/v1/job/{id}` |
| `POST /v1/jobs/{id}/continue` | `CommandJob(JobCommand)` | Upstream `PUT /api/v1/job/{id}/continue` (timelapse continuation in the real API) |
| `POST /simulation/state` | — | Sim-only test controls; HTTP 404 in real mode |

The simulator's pause/resume/stop state transitions are deterministic; its
`continue` transition approximates timelapse continuation without simulating a
camera. Simulation controls accept `state`, `temp_bed` (number or null),
`job_id` (nonnegative integer or null), and `failure`
(`401`, `404`, `409`, `500`, or null). Unknown fields are errors.

HTTP results use protobuf JSON with snake_case field names. Optional absent
temperatures/IDs are omitted, **not defaulted to zero**. `int64` IDs and times
are encoded as strings by protobuf JSON. Booleans are always present.

`ready_for_unload` means precisely:

```text
printer.state == FINISHED AND bed temperature is present AND temperature < 30
```

`IDLE`, `READY`, `STOPPED`, `ERROR`, missing temperature, or upstream failures
cannot substitute for print completion. There is no cache or completion latch.
The observation timestamp is the service's receipt time, not a printer sensor
timestamp. This boolean is **advisory telemetry, not robot motion authorization**.

Errors have the shape
`{"error":{"code":"upstream_error","message":"PrusaLink HTTP 500"}}`.
Upstream 404/409 are preserved; authentication failures, unreachable upstream,
redirects, malformed/oversized responses and invalid telemetry become HTTP 502;
timeouts become 504. Disabled commands return 403 and invalid commands 400.
Failures are logged without credentials or printer response bodies.

The gRPC service is `omts.prusalink.PrusaLinkService`, defined in
[`prusalink.proto`](prusalink.proto). In Intrinsic, connect to
`localhost:17080` and attach `x-resource-instance-name: prusalink` metadata.
Generated Python stubs are available via
`//services/prusalink:prusalink_py_pb2_grpc`. Example for a gateway client:

```python
import grpc
from google.protobuf import empty_pb2
from services.prusalink import prusalink_pb2_grpc

with grpc.insecure_channel("localhost:17080") as channel:
  stub = prusalink_pb2_grpc.PrusaLinkServiceStub(channel)
  status = stub.GetStatus(
    empty_pb2.Empty(),
    metadata=(("x-resource-instance-name", "prusalink"),),
    timeout=5,
  )
  print(status.ready_for_unload)
```

## Configuration and future LAN connection

[`PrusaLinkConfig`](prusalink.proto) contains `printer_url` (HTTP(S) origin,
no embedded credentials), Digest `username`, `password_env`, socket
`timeout_seconds` (0 < timeout <= 60), and `enable_job_commands`.
No credentials are bundled. Real mode requires an explicit URL, username,
and populated password environment variable; it never falls back to simulation.
Printer requests bypass host proxy settings and reject redirects.

Job commands are **disabled by default**. The demo's
[`simulation_config.textproto`](simulation_config.textproto) explicitly enables
them for the mock. Do not enable them for physical equipment without authorization.
Both front-end APIs are unauthenticated: local mode binds loopback by default.
Restrict gateway access to a trusted network; do not expose either interface to
the Internet. `--host` can change the local front-end bind address.

For a future LAN connection, provision the printer's Digest password as
`PRUSALINK_PASSWORD` in the service runtime environment, then configure its LAN
origin and username. Inject the credential through deployment secret management,
not a tracked textproto, command-line password, or service bundle.
Physical printer access/commands have not been exercised in this stage.

## Bundle and sideloading

The manifest allocates gRPC on `RuntimeContext.port`, HTTP on
`RuntimeContext.http_port`, and honors `http_path_prefix`. A missing/malformed
runtime context, wrong configuration envelope, wrong simulation level, or
unallocated ports cause an explicit startup failure.

```bash
bazel build //services/prusalink:prusalink_service

# Generate a binary google.protobuf.Any, not a textproto.
bazel run //services/prusalink:prusalink_server -- \
  --enable-job-commands --write-config=/tmp/prusalink.binpb

# Only with an existing SIMULATION solution; service add inherits its mode.
inctl asset install \
  bazel-bin/services/prusalink/prusalink_service.bundle.tar \
  --address localhost:17080
inctl service add ai.omts.prusalink --name=prusalink \
  --config=/tmp/prusalink.binpb --address localhost:17080
inctl service state list --address localhost:17080
```

Use a different instance name if `prusalink` already exists; its HTTP prefix
and gRPC resource metadata must match that name. The stand-alone demo target
handles packaging and instantiation without these manual steps.

## Skill contracts, verification, and next step

The shared protobuf contract is
[`read_printer_status.proto`](../../skills/printer/read_printer_status.proto).
Both skills bind `printer` with capability
`omts.prusalink.PrusaLinkService` using the leased handle's gRPC address and
routing metadata, not a hard-coded host. The manifest declares a READ lease;
neither skill locks or edits the world. Preview explicitly refuses to invent
live printer readiness.

* `ai.omts.read_printer_status`: optional `expected_job_id`, optional
  `rpc_timeout_seconds` (default 5, max 10); returns `SNAPSHOT`.
* `ai.omts.wait_for_printer_ready`: requires `expected_job_id`;
  `timeout_seconds` default 120 (max 3600), `poll_interval_seconds` default 1
  (max 60), `rpc_timeout_seconds` default 5 (max 10). Cancellation interrupts
  polling; an in-flight RPC is bounded by its timeout. Returns `READY` or
  `TIMED_OUT`, or raises an explicit skill error.

Skills reject invalid/nonfinite parameters, missing/invalid resource handles,
invalid or over-10-second-old service observations, and inconsistent readiness.
The timestamp checks service receipt freshness, not the age of a physical
sensor measurement. Each invocation creates its own connection and local poll
state; readiness is never latched across invocations.

At the pinned SDK, declaring equipment in a new skill manifest is disabled
although its public Python runtime still consumes that model. The narrowly
scoped [`printer_skill_dependencies.patch`](../../bazel/patches/printer_skill_dependencies.patch)
allowlists only these two manifests. Remove it when migrating these bindings
to a supported replacement SDK dependency model.

```bash
bazel test --test_output=errors \
  //tests/unit:test_prusalink //tests/unit:test_printer_skills
bazel build //services/prusalink:prusalink_service \
  //skills/printer:read_printer_status //skills/printer:wait_for_printer_ready \
  //tools/printer:printer_skills
bazel build --nobuild //...
./tools/lint.sh
```

Tests exercise real loopback HTTP and gRPC, Digest credential rejection,
commands and conflicts, absent jobs/temperatures, malformed telemetry,
upstream failures/timeouts, prefix routing, configuration validation and the
strict 30 °C threshold. The isolated solution was also deployed and exercised
through Intrinsic ingress with `curl`.

Skill tests cover real loopback mock HTTP -> service gRPC -> skill calls,
the exact boundary, identity, faults, timeout, cancellation, and fresh results.
The two bundles are also exercised through the running simulation Executive.

Next demo: explicitly compose a guarded pick behavior. This is intentionally
not wired into `omts_app` yet: add per-job consumption/repeated-pick prevention,
revalidate telemetry before motion, and retain the cell's independent motion
safety checks. Re-running a wait on the same completed/cool job returns READY
again; it does not persist a "part already removed" latch.
