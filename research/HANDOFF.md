# Handoff: 3D Printer Tending

Current state and plan for the printer-tending project, so work can continue on
any machine. The printer-side design is [`PRINTER_UNLOADING.md`](PRINTER_UNLOADING.md).
This file records what has been decided and what to do next.

---

## 1. Where Things Are

| Item | Location |
| --- | --- |
| Repo | `https://github.com/intrinsic-opensource/intrinsic-omts-3d-printing`, branch `added-rebot-solution` |
| Research commit | `fbb9606` "Printer unloading viability research", on top of upstream `main` at `48be90d` (#151). Upstream has since been merged in through #156. |
| Printer design notes | `research/PRINTER_UNLOADING.md` (trimmed 2026-10-22; the full feasibility study, including the SO-101 evaluation, is at commit `6b33ad7`) |
| Arm comparison (decided) | Summarized in section 6.3; the full comparison (`ARM_SELECTION_REQUEST.md`) is in git history at `b5b4eee` |
| SO-101 URDF | `research/so101_new_calib.urdf`, from the earlier SO-101 evaluation; superseded by the reBot decision |
| reBot URDFs | Base for the sim model: [Seeed-Projects/reBot-Isaacsim](https://github.com/Seeed-Projects/reBot-Isaacsim) `urdf/00-arm-rs_asm-v3/urdf/00-arm-rs_asm-v3.urdf` (MIT), which fixes the gripper limits (section 6.2). Originals: [Seeed-Projects/reBot-DevArm](https://github.com/Seeed-Projects/reBot-DevArm) `Rebot_Arm_description/` (Apache-2.0 / CERN-OHL-W-2.0). |
| Reference source | `intrinsic-core` checked out at the commit OMTS pins: `INTRINSIC_CORE_COMMIT` in `MODULE.bazel`: `50927e35`, the `20261022.0` release, since #169 (#161 had pinned the untagged commit `c40e02aa`). Check behavior against the pinned commit when it matters. |

Steps 1a–1d are done in simulation (section 5), which completes milestone 1:
the reBot picks a printed part with its gripper, carries it in Gazebo, and
places it, with RViz (the belief world) matching. Steps 3a–3c-2 are done
too, which completes milestone 2 (section 5b; step 3d is optional): OMTS's own
app runs the cell from the wrist camera, finding the part on a Prusa Core One's
bed, taking it to a drop-off and back. To deploy and run it, see
[`REBOT_OMTS_APP.md`](REBOT_OMTS_APP.md). The milestone 1 demo
(`//:rebot_demo`, `REBOT_DEMO.md`) was removed on 2026-10-30, once `omts_app`
did the same round trip with perception; it is in git history (`42fcafc`).

---

## 2. Setting Up the New Machine

```bash
# Upstream OMTS as origin (meshes are plain files; no Git LFS since #173)
git clone https://github.com/intrinsic-ai/intrinsic-omts.git
cd intrinsic-omts

# The 3D-printing fork, which holds the reBot cell
git remote add opensource https://github.com/intrinsic-opensource/intrinsic-omts-3d-printing.git
git fetch opensource && git switch -c added-rebot-solution --track opensource/added-rebot-solution

# intrinsic-core next to it, for reading drivers, skills and tutorials, at the
# commit OMTS pins (INTRINSIC_CORE_COMMIT in MODULE.bazel)
cd .. && git clone https://github.com/intrinsic-ai/intrinsic-core.git
cd intrinsic-core && git checkout --detach \
  "$(sed -n 's/^INTRINSIC_CORE_COMMIT = "\(.*\)"/\1/p' ../intrinsic-omts/MODULE.bazel)"
```

A clone made the way Intrinsic's getting-started guide does it
(`gh repo clone ... -- --revision=...`) has no fetch refspec, so `git fetch`
only gets `HEAD` and `main` tracks nothing. Fix it with
`git config remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'`,
`git fetch origin` and `git branch --set-upstream-to=origin/main main`.

`origin` is upstream (`intrinsic-ai/intrinsic-omts`) and `opensource` is
`intrinsic-opensource/intrinsic-omts-3d-printing`, where this work is pushed.

Perception (milestone 2, step 3b) also needs the NVIDIA pose estimator's
model assets, including the gated SAM 3 weights, exported once per machine;
see [`REBOT_OMTS_APP.md`](REBOT_OMTS_APP.md), quick start step 2.

The offline reach and clearance checks run through Bazel, which provides
numpy and scipy (`research/tools/README.md`). For other quick scripts (URDF
kinematics, 3MF parsing), install `numpy`. The original machine had no system
pip; it was installed per-user with `get-pip.py --user`, then
`python3 -m pip install --user numpy`.

---

## 3. Decisions Taken

### 3.1 Project decisions

| Decision | Consequence |
| --- | --- |
| **Arm: Seeed reBot Arm** | Replaces the SO-101 plan (study section 7, at commit `6b33ad7`). The B601-RS is the working assumption until the variant is confirmed. |
| **ICON support for the reBot is expected from Intrinsic Core** | Hardware only, likely for the B601-RS. This project does not write or validate a driver; the community-driver risks (section 6.3) apply only if that changes. The simulation model is ours to build. |
| **Target compute: NVIDIA Jetson (Orin or Thor)** | ARM64 support is expected. Seeed sells reBot kits bundled with Jetson Orin or Thor. |
| **Simulation first** | Hardware waits for ICON support for the arm. All milestone 1 work runs in Gazebo (`--operation_mode=sim`). |
| **No target printer yet** | The target printer stays undecided. Milestone 1 started in an empty cell; a stand-in printer joined in step 2a, and a Prusa Core One model replaced it in step 3c-2 as the cell's printer for now. |
| **Spiral workflow** | Start simple and add complexity in small steps, with something to demo at every step (section 5, and `CLAUDE.md`). |

### 3.2 From the study

Each is recorded in the study with its reasoning.

| Decision | Why | Study section |
| --- | --- | --- |
| Localize parts from the slicer's 3MF plate layout, not vision | The app starts each print and already has the 3MF; avoids per-job pose-estimator training | 4 |
| Plain RGB camera for presence checks (A, B, C), not depth | The project must be open source and accessible; the printer's own camera may cost $0 | 5 |
| **No force sensing** | Lets low-cost position-controlled arms qualify; accepts that short or collapsed prints go undetected | 4.3, 5.5 |
| Host-side loop, one behavior tree built per print job | The layout is only known per job; also the simplest "print done" detection (polling the printer API) | 1, 6.1 |
| Grasp planning through OMTS's `GraspPlannerInterface`, with a new plate-footprint backend as the default | Fits the localization/grasp split added upstream in #144/#150; MoveIt stays optional because it needs ROS 2 | 4.4 |
| Footprint grasp math in `src/core/footprint_grasp.py`, with a thin `PlateGraspPlanner` in `src/hardware/` | Pre-print layout validation must run without a solution connection, and `core/` cannot import `intrinsic.*` | 4.4, 6 |

### 3.3 Perception from the wrist camera (2026-10-26)

| Decision | Consequence |
| --- | --- |
| **Locate the print with an Orbbec camera on the wrist, as OMTS does** | Overrides two study decisions in 3.2: vision replaces the 3MF plate layout as the localization source, and a wrist depth camera replaces the fixed RGB camera. The plate layout stays as a later confidence check. |
| **Reuse OMTS and Intrinsic Core first; minimize custom code** | Part of the goal is to measure how easy the integration is. Every change to OMTS or a deviation from its design is flagged in the step that needs it. |
| **Run the reBot cell through `omts_app`** | The pick-and-place `rebot_demo` was custom; the perception milestone moves the cell onto OMTS's own app and tree, with `machine: None` like `lab_bb_01`. The demo was removed after step 3c (2026-10-30). |
| **No force sensing still holds** | OMTS's compliant touchdowns (`move_to_contact`) must become optional (milestone 2, step 3c). |

---

## 4. Open Questions

### 4.1 For Intrinsic Core

1. **Scope of the reBot ICON support:** expected to cover the hardware only,
   with no simulation model and no gripper. For simulation we use Intrinsic's
   generic Gazebo stand-in with a model built from the URDF (step 1b).
2. **Variant:** to be decided; the B601-RS is most likely.
4. **New (2026-10-20): expose `gazebo_hwm_stub_image` outside intrinsic-core.**
   A simulation-only hardware device for a new arm needs it, and OMTS patches
   the visibility for now (step 1b).
5. **New (2026-10-20): how will the reBot's gripper be exposed?** It is a
   motor on the arm's CAN bus. Step 1d simulates it as a pinch gripper
   commanded by `control_pinch_gripper` over GPIO signals (route a). If the
   real gripper is exposed differently, only the gripper device and
   `PinchGripper` adapter should need to change.
6. **New (2026-10-22): feature requests for faster iteration**, drafted in
   [`feature_requests/`](feature_requests/): keep RViz in sync without
   restarting `flowstate_ros_bridge`, and keep the Gazebo viewer valid across
   simulation resets.

7. **New (2026-10-26): does the NVIDIA pose estimator run on a Jetson, and
   which one?** `nvidia_pose_estimator_service` (FoundationPose with SAM 3)
   runs on the desktop GPU in sim, peaking at 15.3 GB with only the batch
   setting lowered (step 3b). A 16 GB Orin NX, whose memory is shared with
   the CPU, would not fit it as built; an Orin AGX (32/64 GB) or Thor would.
   Ask whether the service will expose FoundationPose's hypothesis count and
   FP16 precision, which the library already supports.
8. **New (2026-10-30): carry mimic joints into simulation**, drafted in
   [`feature_requests/mimic_joints.md`](feature_requests/mimic_joints.md).
   The reBot's fingers share one actuator, but Intrinsic's scene object
   conversion drops `<mimic>` (Gazebo itself supports it), and the gripper
   plugin drives each finger separately. In sim the fingers then come apart
   under contact: they drift while a grasp rests on the bed, and at release
   one finger can stay on the part or drag it. The cell presses the part
   onto its support before opening as a workaround.

### 4.2 Open project questions

1. **Target printer and firmware.** Deferred: decides the status API, camera
   source and 3MF variant. The cell uses a Prusa Core One model for its
   geometry (step 3c-2); whether the Prusa is the target is undecided. Needed
   before the printer adapter and per-job cycle (after milestone 2).
2. **Sheet swap or direct part grasping.** The study assumes direct grasping
   as the harder case.
3. **Is the uncovered "collapsed or short print" case acceptable?**
4. **MoveIt backend:** worth its ROS 2 setup for printed parts, or is the
   footprint planner enough?

---

## 5. Milestone 1: The reBot Replaces the UR in Simulation

Goal: OMTS runs a pick-and-place cycle in simulation with the reBot instead of
the UR5e, in an empty cell. Each step below ends in a demo.

### Step 1a: The reBot is in the world

**Status: done (2026-10-20).** Deployed to the local cluster in sim.

* New solution target `//:rebot_solution` (root `BUILD`), deployed in sim by
  default, with only the Gazebo simulator and the reBot. It is a separate
  target rather than a `//:setup` value: `tests/unit/test_behaviors.py` parses
  `omts_solution`'s text and requires its current shape, and a separate target
  leaves `omts` and `lab_bb_01` untouched.
* New model `models/rebot_b601_rs/`, generated from the reBot-Isaacsim RS URDF
  (section 6.2) by the new `//tools/models:urdf_to_sdf` (numpy only, unit
  tested in `tests/unit/test_urdf_to_sdf.py`). It writes one simplified,
  colored visual GLB and one coarse collision GLB per link (about 7 MB in all).
  The model is static for now; its README lists the step 1b and 1c follow-ups.
* Verified: `gz sdf -k` passes, `sdf_scene_object` converts the model, an
  offline render shows the arm assembled correctly at two poses,
  `bazel build --nobuild //...` passes, and all 22 unit tests pass.
* **Demo:**

  ```bash
  bazel run -c opt //:rebot_solution -- --address=localhost:17080
  ```

  The reBot stands alone in the world and in Gazebo.

* Result: the belief world holds `rebot` and `root` only. Gazebo
  (`rs-gazebo-simulator-0`) spawned the model with all eight joints and
  attached a `JointPositionController` to each
  (`/model/rebot/joint/<joint>/0/cmd_pos`).
* Learned for step 1b: Gazebo logs "The resource config proto for 'rebot' is
  not a HardwareModuleConfig, will not add a HardwareModuleLauncher system to
  it". ICON control in sim is attached through a hardware module config on the
  resource, which is what the step 1b hardware device provides.

### Step 1b: The reBot moves

**Status: done (2026-10-20).** Deployed to the local cluster in sim.

What was built:

* **Arm and gripper split into two objects.** Gazebo's simulated hardware
  module infers one joint group from all of a model's joints, which would have
  made the fingers part of an 8-DoF "arm". The converter gained
  `--root_link`/`--exclude_links`. `models/rebot_b601_rs` is now the 6-joint
  arm, and `models/rebot_b601_rs_gripper` is the gripper, mounted on the
  flange like the UR cell's Robotiq.
* **Simulation-only ICON hardware device** `ai.intrinsic.rebot_b601_rs`: the
  arm scene object (with `intrinsic:ik_solver` `kinematic_chain`, a `flange`
  frame, joint limits and the `home`/`ready` named configurations) plus a
  service shipping Intrinsic's Gazebo stub image.
* **Cell config** `configs/rebot/`: an ICON config with one `HalArmPart` on
  module `rebot`, the gripper attachment with `tool_frame` at the fingertips,
  and two top-down demo frames, `demo_a` and `demo_b`.
* **`//:rebot_solution`** now also installs ICON, the motion planner and the
  `move_robot`/`move_to_contact` skills (`Robot` looks up both when it is
  built). Instance names follow the OMTS defaults (`gripper`, `tool_frame`,
  `icon`), so the existing jogging tools work with `--arm_part_name=rebot`.

**Demo** (all 10 moves of two loops succeeded; the tool reaches the demo frames
within micrometres):

```bash
bazel run -c opt //:rebot_solution -- --address=localhost:17080
for i in 1 2 3; do
  bazel run //tools/jogging:move_to_joint -- home --arm_part_name=rebot
  bazel run //tools/jogging:move_to_joint -- ready --arm_part_name=rebot
  bazel run //tools/jogging:move_to_frame -- --frame=demo_a --arm_part_name=rebot
  bazel run //tools/jogging:move_to_frame -- --frame=demo_b \
    --motion_type=LINEAR --arm_part_name=rebot
done
```

Learned (friction worth knowing):

* **Intrinsic's stub image is not visible outside intrinsic-core**, and neither
  is the base image needed to build our own. OMTS patches the visibility
  (`bazel/patches/gazebo_hwm_stub_visibility.patch`), next to the existing
  Robotiq patch. Question 4.1.4 asks Intrinsic to expose it.
* **`hardware_module_manifest` requires a real-mode `image`**, despite the
  attribute being optional. The device passes the stub for both modes.
* **A service's `default_config` must be a `google.protobuf.Any` textproto.**
* **Right after a deploy, the first move fails** with `move_robot` "connection
  refused" until Gazebo has started the hardware module and ICON has enabled
  motion (a few seconds). Wait for "[rebot] Now enabled" in the
  `rs-gazebo-simulator-0` logs.
* **RViz works through `flowstate_ros_bridge`**, which `//:rebot_solution`
  deploys. It runs in sim even though its manifest has no `sim_spec`. Over
  Zenoh it publishes `/tf` (the whole belief world, frames like `rebot/link1`,
  `gripper/tool_frame`, `root/demo_a`, fixed frame `root`) and
  `/workcell_markers` (one mesh marker per link, fetched from the bridge's
  `/flowstate_get_resource` service). No URDF is needed. Open it as a Zenoh
  client of the local cluster with the cell's config:

  ```bash
  export RMW_IMPLEMENTATION=rmw_zenoh_cpp
  export ZENOH_CONFIG_OVERRIDE='mode="client";connect/endpoints=["tcp/127.0.0.1:7447"]'
  ros2 run rviz2 rviz2 -d configs/rebot/rebot.rviz
  ```

  One launch showed TF but no meshes; relaunching RViz fixed it.
* **The bridge gives up if the executive is not up when it starts**, and then
  never publishes. After a deploy, restart it if `/tf` stays empty:
  `kubectl -n app-resources delete pod rs-flowstate-ros-bridge-0`.
* **`/joint_states` uses UR joint names.** The bridge's default config
  hard-codes `override_joint_names` (`shoulder_pan_joint`, …) and
  `robot_base_frame_id: robot/robot/base_link`. The values are the reBot's,
  only the names are wrong. RViz doesn't care, but MoveIt or anything matching
  joints by name would: give the cell its own bridge config with `joint1`…
  `joint6` and `rebot/base_link` when that is needed.
* **Reload the Gazebo viewer after a redeploy or `--reset_sim`.** Each one
  rebuilds Gazebo's world, and a viewer that stays connected can keep stale
  entities. Symptoms seen here: arm links drawn scattered, and the nested
  gripper drawn at the origin while Gazebo had it mounted and moving.
* **Inspecting Gazebo directly:** the simulator container has no shell, but
  its gz-transport is reachable from the host with the local `gz` tools:

  ```bash
  export GZ_PARTITION=intrinsic_sim GZ_IP=10.42.0.1 \
    GZ_RELAY=$(kubectl get pod -n app-resources rs-gazebo-simulator-0 \
      -o jsonpath='{.status.podIP}')
  gz topic -e -t /world/default/pose/info -n 1   # live model/link poses
  gz service -s /world/default/generate_world_sdf \
    --reqtype gz.msgs.SdfGeneratorConfig --reptype gz.msgs.StringMsg \
    --timeout 20000 --req ''                     # the SDF Gazebo is running
  ```

  `GZ_IP` is the host's `cni0` address. In that SDF the gripper is nested in
  the `rebot` model with a fixed joint from `link6`, as intended.
* **Top-down is exact only in part of the workspace.** `joint4`'s upper limit
  (1.69 rad) stops the tool pointing straight down at some points, for example
  0.30 m out and 0.20 m up. Straight down works from about 0.25 to 0.40 m out
  and 0 to 0.15 m up (offline IK, checked live at the demo frames).

### Step 1c: The reBot picks and places a printed part

**Status: done in the belief world (2026-10-20); Gazebo does not carry the
part.** Superseded by step 1d, where the gripper carries it in Gazebo.
Deployed and verified in local simulation. Watch the demo in RViz. Decided
2026-10-20: keep this stand-in for now; step 1d makes Gazebo carry the part.

* Added `models/rebot_printed_part/`, a 40 × 40 × 30 mm, 20 g model with a box
  collision and a GLB visual, and fixed source A / destination B frames in
  `configs/rebot/rebot_pick_place.updates.pbtxt`.
* Added `models/rebot_ground/`, a static 2 × 2 m slab (box collision, GLB
  visual) with its top surface at `z=0`, so the printed part starts on solid
  ground instead of falling through empty space.
* Ground-to-part collision is excluded only on the position-only contact and
  immediate retract segments; transit keeps ground collision checking enabled.
* Added `//src:rebot_demo` / `//:rebot_demo` and a reBot-specific behavior tree.
  It uses `GridInfeedStrategy`, position-only linear approaches, and
  `attach_object_to_robot` / `detach_object` as the temporary sim-only grasp
  stand-in. The same part transfers A→B→A each cycle, so it can repeat without
  finger actuation or resetting the world.
* No gripper-finger actuation or `GripperInterface` implementation is included
  in this step. Defer it until Intrinsic confirms how the real reBot gripper
  will be exposed.
* **Demo:** `bazel run -c opt //:rebot_solution -- --address=localhost:17080`,
  then `bazel run //:rebot_demo -- --address=localhost:17080`. The tree performs
  A→B→A transfers; use `--num_cycles=N` to repeat the round trip.
* Verified: scene-object builds, `bazel build --nobuild //...`, focused
  behavior and config-schema tests, and two simulated A→B→A cycles via
  `bazel run //:rebot_demo -- --address=localhost:17080 --num_cycles=2`.
  Sampling the belief world during a cycle showed the part reparented to
  `rebot`, following the tool A→B→A, and returned to `root` on detach.

Learned:

* **`attach_object_to_robot` changes only the belief world; Gazebo's part
  stays put.** Simulation syncs Gazebo → world service (`sim_world`), never
  belief → Gazebo, so reparenting has no physical effect. Sampled
  `/world/default/pose/info` during a cycle: the part stayed at A throughout.
  Gazebo welds a part to the tool only through a gripper plugin. The weld-only
  option is `FixedJointGripper`, which Intrinsic enables for an EOAT
  `SuctionGripperConfig` and commands through ICON digital I/O. It needs the
  same simulated-DIO setup as route 2 below. Gazebo's stock `DetachableJoint`
  plugin survives SDF conversion but is triggered by gz-transport topics,
  which a behavior tree cannot publish.
* **RViz skips SDF primitive visuals.** `flowstate_ros_bridge` draws only
  visuals with a mesh `geo_ref`; `<box>` visuals are stored inline and
  silently dropped. Both new models therefore use GLB visuals (boxes written
  with `tools/models/urdf_to_sdf.write_glb`) and keep box collisions.
* **The bridge fetches meshes once, at pod start,** and a redeploy does not
  restart it. It does notice objects added later, but publishes a marker
  message for only those, and `/workcell_markers` keeps just the last message
  (`KeepLast(1)`, transient local). An RViz opened afterwards then shows only
  the new objects: after adding the wall, RViz showed the wall but not the
  robot. After adding objects, restart it:
  `kubectl -n app-resources delete pod rs-flowstate-ros-bridge-0`.
* **The part creeps up about 1 mm per transfer** in the belief world (z 0.017
  → 0.018 → 0.019 over one round trip): the attach captures the tool's actual
  pose, which settles slightly differently at grasp and place. Harmless for a
  few cycles; snap the part to its nominal pose after detach if long runs
  need it.

Gripper actuation in sim, investigated 2026-10-20 and deferred:

* **World updates don't move the fingers in Gazebo.** Setting the gripper's
  joints in the belief world (`update_object_joints`) changes nothing in the
  simulation.
* **Gazebo actuates an object as a gripper only when its instance has a gripper
  service config** (`WorldObjectPlugin` in intrinsic-core's
  `intrinsic/simulation/world/world_object_plugin.cc`). It then replaces the
  per-joint controllers with an actuated-gripper plugin that finds the
  prismatic joints itself. Two of Intrinsic's routes fit:
  1. **`PinchGripperPart`**, the Robotiq resource-type style: the gripper scene
     object plus Intrinsic's pinch-gripper server service. In sim, Gazebo serves
     the `GenericGripper`/`PinchGripperServer` API. No Intrinsic skill commands
     that API, so it would need a host-side call or a small custom skill.
  2. **`PinchGripperRealtimeControlServiceConfig`** with Intrinsic's
     `control_pinch_gripper` skill (grasp/release, usable as a `bt.Task`). The
     service signals the gripper through ICON digital I/O, so it also needs
     simulated DIO on the arm's module (a `DigitalInputOutput` plugin in the
     SDF, as the UR models have), a `HalADIOPart` in ICON and the signal
     mapping.
* Step 1c uses **no actuation**: it attaches the part to the robot with
  `attach_object_to_robot` as a sim-only stand-in. Real finger motion is later
  work.
* How Intrinsic's hardware support will expose the real gripper (a motor on
  the arm's CAN bus) is unknown; ask before investing in either route.

### Step 1d: The gripper moves and attachment works in simulation

**Status: done (2026-10-20).** Deployed and verified in local simulation with
command path a (`PinchGripperRealtimeControlServiceConfig` with
`control_pinch_gripper`). The part now moves in Gazebo, not only in RViz.

What intrinsic-core does, checked 2026-10-20 (`intrinsic/simulation/`):

* **Gazebo creates a sim gripper only for hardware-device instances.** At
  startup it lists hardware devices (`ListHardwareDevices` in
  `gazebo/server_main_impl.cc`) and configures a gripper plugin when the
  device's service config is one of: `PinchGripperPart`,
  `PinchGripperRealtimeControlServiceConfig`, `PinchGripperOpcuaServiceConfig`,
  an EOAT `GripperConfig`, or the suction equivalents. A plain scene object
  gets only per-joint controllers no skill can command.
* **The pinch-gripper plugin both moves the fingers and holds the part.**
  `ActuatedGripperPlugin` drives every prismatic or revolute joint with finite
  limits (both reBot fingers qualify). When a grasp stops at an object (and the
  commanded opening is under 2 cm), it welds the object touching a "sticky"
  finger link with a `FixedJointGripper` fixed joint. So one route gives both
  finger motion and a reliable carry, with no friction tuning.
* **In sim, route a needs no ICON digital I/O.** The gripper service
  (`gripper_services.cc`) skips the configured ICON endpoint in sim and talks
  to Gazebo's simulated GPIO service (`<simulation server>:12394`), where the
  gripper plugin registers the configured signals. The planned `DigitalInputOutput`
  SDF plugin and `HalADIOPart` were not needed; they matter only for real
  hardware.

What was built, one demo per sub-step:

1. **1d-i: the fingers move on command.** `models/rebot_b601_rs_gripper` is
   now a hardware device, `ai.intrinsic.rebot_b601_rs_gripper`: its scene
   object (renamed `..._gripper_scene_object`) plus intrinsic-core's
   `pinch_gripper_realtime_control_service`, which OMTS builds from source.
   The instance config `configs/rebot/gripper.instance.pbtxt` sets
   `hardware_device { service { service_config } }` with one grasp/release
   signal (`gripper_close`), a gripping-indicated signal (`gripper_holding`)
   and `is_default_closed: true` (finger joint 0 is closed). New
   `PinchGripper` adapter (`src/hardware/gripper.py`, `gripper.type: pinch`)
   and a `pinch` type in `//tools/gripper:control_gripper`. **Demo:**
   `control_gripper --gripper_type=pinch --action=open|close` moved both
   Gazebo fingers from ±0.1 mm to ±50.1 mm and back.
2. **1d-ii: a grasp holds the part.** `rebot_pick_place.py` opens the gripper
   above the part, descends, grasps, attaches, carries, releases, then
   detaches. Grasp frames dropped from z 0.05 to 0.01, so the fingertips close
   over the lower 20 mm of the part (open gap is 100 mm, finger length about
   50 mm). The `(gripper, part)` exclusion already covers the finger links.
   **Demo:** sampling `/world/default/pose/info` during a cycle, the fingers
   closed to ±22 mm on the part, which rose to z 0.12, moved A→B, landed at
   z 0.015, and came back to A.
3. **1d-iii: full cycle in Gazebo and RViz.** After each detach, a new
   `Robot.build_place_object_at_frame_task` (`update_world`) snaps the belief
   part onto the destination's rest frame (`part_a_rest` / `part_b_rest`).
   **Demo:**
   `bazel run //:rebot_demo -- --address=localhost:17080 --num_cycles=3`;
   afterwards Gazebo has the part at (0.300, −0.121, 0.015) and the belief
   world at (0.300, −0.120, 0.015). Without the snap, three cycles left the
   belief part 6 mm high.

Learned:

* **A redeploy does not rebuild Gazebo's world; a simulation reset does.**
  After adding the gripper device, Gazebo kept the old per-joint controllers
  until `solution.simulator.reset()`. Reset after deploys that change
  devices or object poses:
  `bazel run //tools/world:apply_scene_updates -- --address=localhost:17080 --files --reset_sim`
  (`--files` with no paths resets without applying updates).
* **The gripper service needs a gripping-indicated signal**, or it exits with
  "GrippingIndicated Config not set". It enables itself on startup; no enable
  skill is needed.
* **Hardware-device instance configs go in the `config` attribute.**
  `service_config` generates a plain `service {}` block, which a hardware
  device ignores. The `config` file avoids depending on the service's config
  proto, which intrinsic-core keeps internal.
* **`control_pinch_gripper` also moves the belief-world fingers**, to their
  lower limit on grasp and upper limit on release, so RViz shows the gripper
  opening and closing.
* **The step 1c commit had a failing test:** the tree had lost the
  part-to-ground exclusion that the test (and the planner) expect. Step 1d
  restores it.
* **`control_pinch_gripper` returns before the fingers stop.** It only sends
  the GPIO command, so the arm started lifting while the fingers were still
  closing. `PinchGripper` now follows each grasp and release with a dwell
  (`GripperConfig.settle_seconds`, default 1.5 s): a full stroke takes 0.45 s
  in Gazebo, and the part is welded 0.5 s after contact. Measured after the
  fix: the fingers stop on the part, then the part rises 1.5 s later. On real
  hardware, waiting for the gripping-indicated signal would be better than a
  fixed dwell.
* **The demo runs slower** (one A→B→A cycle in 27 s): the reBot's application
  limits, which the planner uses, are now 0.5 rad/s (joints 1–3), 0.75 rad/s
  (joints 4–6) and 3 rad/s², down from 1–1.5 rad/s and 8 rad/s². They are
  simulation placeholders; jogging is slower too.
* **The arm starts and ends folded at `home` with the gripper closed**, the
  reBot's standard resting state; the initial joint positions were `ready`
  before. A finite demo run ends by closing the gripper above A (clear of the
  released part) and folding back to `home`.
* **A redeploy or simulation reset keeps the arm's live pose.** Changing the
  initial joints updated `init_world`, but the belief and simulated worlds
  kept the arm at `ready`, because the reset rebuilds Gazebo from the belief
  world. `rebot_demo` now runs with `start_from_world_state=INITIAL` (flag
  `--from_initial_world`, default true), which resets both worlds to
  `init_world` first, rebuilds Gazebo's gripper, and puts the part back at A.
  So every run starts from the same state, even after a failed one.

Milestone 1 is done at the step 1d demo.

### Step 2a: The printer is in the cell

**Status: done (2026-10-23).** Deployed and run live in local simulation: two
A→B→A cycles in 71 s, and Gazebo has the part back at A, flat, within 1 mm.

* `//:rebot_solution` now deploys the stand-in printer model
  (`models/printer`, from the `omts` cell rework) in front of the reBot,
  placed by `configs/rebot/printer.updates.pbtxt`. Its open front faces the
  robot (yaw −90°), the spool stack is on the robot's left, and the bed centre
  is at x = 0.36 m, z = 0.0895 m.
* A and B are on opposite sides of the robot. A is on the ground behind it,
  0.30 m out at 145° from the printer's direction, where the part starts; B is
  the centre of the printer's bed.
* **One tilted grasp for both ends.** The tool is pitched 35° about the jaw
  axis, its approach leaning away from the robot along the part's x axis, and
  each rest pose's x axis points away from the robot (A's is yawed 145°). The
  grasp is therefore the same relative to the part at A and B, and the part is
  always set down flat. Pre-grasps back off along the approach axis (0.08 m
  at A, 0.06 m at B), so the descents follow the fingers.
* **The arm rests at a new `park_left` configuration**: the folded `home`
  turned 90° to the robot's left. The cell starts the arm there
  (`configs/rebot/scene.updates.pbtxt`), and the tree folds back to it
  (`rest_configuration`, default `home`). The step 1b demo frames
  `demo_a`/`demo_b` moved to the robot's left too, at 105° and 125°.
* The tree excludes the part against whatever it rests on at each end: the
  ground at A, the printer at B (`_SUPPORT_OBJECTS` in
  `src/behaviors/rebot_pick_place.py`).
* The printer replaces the wall obstacle from `be64fe5`, whose placement was
  inside it; the wall model and placement are removed.
* **Demo:** deploy and run as in [`REBOT_DEMO.md`](REBOT_DEMO.md): the reBot
  carries the part from behind it into the printer and back.

Learned (each item cost one failed live run):

* **`joint1` turns only ±160°, so straight behind the robot is unreachable.**
  Offline IK found contorted solutions there that ignore self-collision; the
  planner found none. A sits at 145°, which keeps about 0.27 rad of `joint1`
  margin.
* **`home` reaches into anything in front of the robot.** Folded, the tool is
  at (0.30, 0, 0.23), inside the printer's front opening, and the first move
  out clipped the printer's front edge. Hence `park_left`.
* **Straight down cannot reach into the printer.** At 0.36 m out the planner
  found no top-down IK above 0.15 m, and at 0.15 m its only solutions put the
  forearm (`link3`) into the printer's top, which starts at z = 0.45 m. Exact
  top-down came from the step 1b frames, not from any requirement; section 6.1
  had already suggested allowing tilt. Following the planner's elbow-up branch
  offline, B's pre-grasp clears the top only from about 25° of tilt, by 3.2 cm
  at 35°.
* **Offline IK is a guide, not a check.** FK from the generated SDF matches
  `ready` exactly, but numeric IK with random seeds finds branches the
  planner never returns, and the scan ignored self-collision. Scoring the
  branch the planner actually reported (from its error message) is what
  predicted the live result. Confirm frames live.
* **Placement.** The bed centre at 0.36 m leaves about 7 cm between the robot
  base (radius 0.12 m) and the printer's front edge (x = 0.146 m). The open
  fingertips clear the bed by 1 cm at B's grasp.
* **Gazebo's part yaw drifts slowly**: 145° → 148.6° over two cycles (four
  grasps and places), with position within 1 mm. The belief world snaps the
  part to its rest frame after each place; Gazebo does not.

### Step 2b: The fingers release the part cleanly

**Status: done (2026-10-26).** Run live in local simulation with Gazebo's
part and finger poses recorded through one cycle.

* Watching step 2a's demo, the part was set down off-centre on the bed and
  the next grasp shoved it back. Recorded in Gazebo: at the release on the
  bed, the part slid 17 mm with the left finger link (the robot's right),
  lifted 0.7 mm and turned 0.9°, while that finger stalled at 39 of 50 mm for
  1 s; then the part dropped free, off-centre.
* **Fix:** the fingers now collide as boxes. `//tools/models:urdf_to_sdf`
  gained `--collision_boxes` (a JSON of boxes per link, in the link frame,
  replacing that link's collision meshes), and the gripper was regenerated
  with `models/rebot_b601_rs_gripper/finger_collision_boxes.json`. It first
  had three boxes per finger; they are now a stack of 19 fitted slice by slice
  to the URDF's full-resolution finger mesh, which tapers to a near point
  (tip box 3 × 2 mm; within 1.6 mm of the surface along the pad). The 8 mm
  vertex clustering had blunted the finger (a 12 mm wide tip; the real tip
  widens from under 2 mm). Inner faces are the pads; the racks, inside the
  gripper body, have no collision.
* **Result:** the release on the bed moves the part 0.1 mm (was 17 mm), the
  fingers open fully in 0.48 s, and after a full A→B→A cycle the part is back
  at A within 0.1 mm and 0.02°.

Learned:

* **Gazebo doesn't collide with our meshes as written.** Intrinsic's world
  conversion gives every mesh collision `optimization='convex_decomposition'`
  (up to 32 convex hulls). On the coarse (8 mm clustered) finger meshes, the
  hulls bridged the pad and the rack, so the fingers stopped 1.75 mm short of
  a part (a 43.5 mm gap on 40 mm), and the tilted fingers' sloped hull faces
  caught the part. Read the generated world
  (`/world/default/generate_world_sdf`, section 1b) to see what Gazebo uses.
* **It was not the weld.** The plugin welds the part to one finger link (the
  first with collision, chosen arbitrarily) and removes the weld 2–4 ms after
  the release command, before the fingers move. The drag was contact.
* **The simulated fingers are weak.** Without gains in the SDF, the plugin
  derives critically damped PD gains from the finger's mass (0.075 kg →
  kp = 16.9 N/m, kd = 2.26), about 0.3 N of squeeze. A finger stalls against
  anything that holds the part with more than that, and the plugin's
  "stopped" check (first finger only, 0.01 mm per step) then fires.
* **Grasp B can still sit about 1.3 mm off-centre** (fingers at 21.3/18.6 mm),
  well inside what the fingers correct. Not chased further.
* **`bed_frame` is 6 mm off the printer's visual bed.** The GLB's bed plate is
  centred at printer (0.000, +0.0007, 0.0895); `bed_frame` is at
  (0.006, −0.001, 0.0895). B follows `bed_frame`, so it sits 6 mm to the
  robot's right of the visual centre. Fix in the model or the placement; open.

---

## 5b. Milestone 2: The reBot Locates the Print by Perception

Goal: the arm finds the part on the bed with the wrist camera alone and picks
it, running OMTS's own app (`omts_app`) with the existing perception pipeline.
Precision is secondary; no force sensing. Decisions in 3.3. Deviations from
the OMTS design are marked **Flag**.

### Step 3a: The camera is on the wrist and captures images

**Status: done (2026-10-28).** Deployed to the local cluster in sim. At `view`,
`capture_images` returns RGB and depth with the part on the bed in both, and
the step 2a demo still runs two cycles with the camera mounted.

* `rebot_solution` reuses `omts_solution`'s `orbbec_camera` and
  `orbbec_gemini_driver` instances unchanged, plus the `capture_images` skill.
  In sim the camera service proxies to Gazebo's camera plugin, so nothing else
  is needed.
* `configs/rebot/orbbec_gemini.updates.pbtxt` mounts the camera on the
  wrist, on the flange like `configs/omts/`: 7.6 cm out along the flange axis
  (OMTS: 7.8 cm), 7 cm off it, looking parallel to the tool axis (no tilt),
  with its baseline along the jaw axis. This step put it on the gripper's -x
  side, below the gripper in the tilted grasps and at `view`; step 3c moved
  it to the +x side, above, for the 60° grasp.
* **The mount pose is our guess, not a reBot part.** Only the `flange`
  frame comes from Seeed's model. No bracket exists for it, and the wrist's
  mounting points and cable routing are unchecked. Revisit when there is a
  real bracket; `view` depends on it.
* **Flag:** no mount model; the camera is attached directly (OMTS's
  `camera_mount` fits the UR flange).
* `view` (in `configs/rebot/scene.updates.pbtxt`) points the tool 60° down
  into the printer with its usual roll, so the camera hangs below the gripper
  outside the printer's front, 0.38 m from the bed centre, looking straight
  in. The whole bed has depth.
* **The printer moved 10 cm further out** (bed centre at x = 0.46, B's frames
  with it). With the bed at 0.36 m, no reachable view put the camera further
  than 0.30 m from the bed centre, which left about the near half of the bed
  inside the depth sensor's near clip. The step 2a demo still runs two
  cycles.
* First version (2026-10-27): camera on the gripper's upper side, tilted 20°
  in, `view` looking 40° down from just inside the printer. Moved under the
  wrist on 2026-10-28, as originally asked; see below.

Learned:

* **The view pose is tightly constrained.** The depth sensor's near clip is
  0.25 m and the printer's top is closed, so the camera must look in from the
  front at an angle. From further back or from the sides the reBot cannot
  reach the pose, and from the front corners the camera body hits a post.
  With the bed at 0.36 m from the base, the best view looked in from 0.30 m
  and lost about the near half of the bed to the near clip.
* **The camera, not the grasp, sets how close the printer can be.** At 0.36 m
  the bed was well within the arm's reach and the grasps planned fine; what
  failed was seeing it. The depth sensor needs 0.25 m to the bed, and the arm
  cannot hold the camera far enough back while it looks in, because that pose
  folds the gripper back toward its own base. So the minimum distance from the
  arm to the printer comes from the camera's near clip and view, not from IK.
  Place the arm for the view first, then check the grasps.
* **How far the printer can sit from the reBot** (offline, 35° grasp): views
  improve the further it is (5 cm out: 93% of the bed has depth; 10 cm: all
  of it). The tilted grasp reaches about 0.62 m from the base, so beyond 15 cm
  out the bed's far half is out of reach, and beyond 25 cm its centre. 10 cm
  keeps margin at the far edge.
* **Above or below the gripper is not a property of the mount.** A mount on
  the other side is the same mount turned 180° about the tool axis; the
  gripper is symmetric and joint 6 turns ±180°. Which side faces down is set by
  the tool's roll in each pose. We keep the usual roll (no wrist roll-over,
  which could hit joint 6's limit) and put the camera on the side that is
  then below.
* **The camera's tight spots are the bed at the grasps and the joint-5
  motor.** Offline checks with the links' collision meshes over the full
  joint ranges: the camera clears the bed and part by about 3 cm at the A and
  B grasps, the joint-5 motor (on link4) by 2.2 cm at worst, and link3, link5
  and link6 by 3 cm or more. Mounting the camera 12 cm back from the
  fingertips instead of 9 makes it hit the joint-5 motor; 7 cm gives 4 cm of
  room for a bracket. It touches link2 only when the arm is folded fully back.
* **No tilt toward the tool axis works only at a low view angle.** With the
  camera below the gripper and looking parallel to the tool, reachable views
  that clear the printer look in about 60° from vertical; tilting the camera
  in (20-40°) leaves almost none.
* **"No IK" does not say why.** The planner reports the same error for an
  unreachable pose and for one whose only solutions collide; the first
  candidate failed because the camera met the front-left post. Picking the
  pose took offline FK/IK plus a rough clearance check against the printer's
  boxes (scratch code, not in the repo). The OMTS route would be dragging the
  frame in RViz (`//tools/world:edit_frames_rviz`) and retrying.
* **No tool shows a capture.** OMTS has no capture-and-view tool; the demo
  images came from listening to Gazebo's camera topics (sim only) while the
  skill ran. The Gazebo GUI's image display shows the same topics. Captures
  are triggered, so the topics publish only when the skill runs.
* **The device config is OMTS's lab camera.** Its serial number only matters
  on hardware, where the reBot gets its own config.
* **Payload:** the camera model weighs 0.22 kg; check against the reBot's
  payload before hardware.

### Step 3b: The pose estimator finds the part

**Status: done (2026-10-28).** Deployed to the local cluster in sim. From
`view`, `run_pose_estimation` finds the part on the bed with score 0.999, 0.5
mm from its true position and within 0.1° of its orientation (modulo the box's
quarter turns). How to set up, deploy, register and run it is in
[`REBOT_OMTS_APP.md`](REBOT_OMTS_APP.md) (quick start steps 2 to 4, and debugging).

* `rebot_solution` adds `nvidia_pose_estimator_service`, `ioc_train_service`
  (omts_solution's instance) and the `estimate_pose_multi_view` skill. The
  estimator for `ai.intrinsic.rebot_printed_part` is registered with
  Intrinsic Core's `register_using_ioc_train_service` and the prompt "cube".
  Only the registration is new: FoundationPose fits the registered object's
  exact model, and OMTS's raw-stock registration does not match the part.
* **The model assets ride in the solution, behind `--//:perception_models`**
  (off by default). A deploy uninstalls every asset the solution does not
  declare, so the three model Data assets installed with `inctl` (as the
  `nvidia_pose_estimator` README says) were gone after the next deploy and the
  service failed with "foundationpose_models not found". Declaring them in
  the solution fixes that, but the SAM 3 target only analyzes when Bazel
  knows where its export is (`--repo_env=NVIDIA_POSE_ESTIMATOR_MODELS_DIR`),
  which CI and fresh machines do not have; hence the flag. Use the
  `<name>_bundle` targets for FoundationPose and FoundationStereo; the plain
  names are only the bundle files.
* **Flag: the reBot has its own pose estimator instance**, with
  `configs/rebot/nvidia_pose_estimator_config.textproto`: Intrinsic's default
  config with the FoundationPose refinement batch cut from 42 to 14. With the
  default, the first estimate ran out of GPU memory on the 16 GB laptop GPU
  ("Failed to create TensorRT execution context").

Learned:

* **OMTS's perception needs a gated model.** The service starts only once its
  three model assets are present: FoundationPose and FoundationStereo, which
  Bazel downloads, and SAM 3, which it cannot. `facebook/sam3` is gated with
  manual approval on HuggingFace, so each user must request access, log in
  (`hf auth login`) and run Intrinsic's export script on a GPU (3.3 GB of
  ONNX). Nothing in `intrinsic-core`'s guides avoids this.
* **The export script needs Python 3.12 or older.** It pins `numpy<2`, which
  has no packages for the system's Python 3.14, so its environment failed to
  build. Creating the environment with Bazel's Python 3.12 and passing it as
  `--venv-dir` works.
* **GPU memory is the pipeline's tightest limit, and the service config
  barely reaches it.** Measured on the 16 GB laptop GPU (sim, `nvidia-smi`
  every 0.1 s): 11.1 GB with the models loaded and idle; each estimate then
  steps to 15.3 GB for about a second and back. That leaves about 1 GB, with
  nothing else on the GPU. Where it goes:
  * SAM 3's engines are built in full 32-bit precision, the same size as the
    ONNX: vision encoder 1.8 GB, text encoder 1.4 GB, decoders 0.26 GB. Its
    input is fixed at 1008 x 1008 by the export.
  * Each estimate allocates FoundationPose's TensorRT working memory: the
    scoring network always runs all 252 hypotheses in one batch (3.35 GB at
    the default refinement batch, which ran out of memory), plus refinement in
    chunks of `batch_size`.
  * Everything stays loaded after warm-up by design; there is no setting to
    load models on demand.
  * FoundationStereo is not loaded with hardware depth, which the config
    already uses.
* **Minimum GPU memory (from these measurements, no further tests): 16 GB**
  dedicated, with the batch lowered to 14 and the GPU otherwise idle (15.3 GB
  peak). Intrinsic's default config needs more than 16.4 GB (roughly 17 GB
  from the failed allocation). Recommended: 24 GB. Jetson: 32 GB or more,
  since memory is shared with the OS and the rest of the cell. Caveats: one
  GPU (RTX 4090 Laptop, x86, TensorRT TF32), one registered part, one
  estimate at a time; up to four detections did not raise the peak, but
  several registered parts or a full plate are untested; Gazebo or a camera
  driver sharing the GPU comes on top.
* **Only `foundation_pose.batch_size` changes the peak.** The service builds
  FoundationPose with the image size and `batch_size` only, so the library's
  hypothesis count and precision stay at its defaults (252, TF32), although
  the library supports both (`RuntimeConfig.n_hypotheses`,
  `tensorrt_precision=FP16`). Setting `n_hypotheses: 126` changed the guesses
  generated but not the scoring engine (still `score_tf32_b252`; the peak went
  15.30 -> 15.24 GB), so it is back at the default. Lowering it, FP16 engines,
  or dropping the text encoder once a prompt is cached would need changes in
  Intrinsic's service.
* **More detections cost time, not memory.** At the registration's 0.15
  confidence threshold SAM 3 passed four candidates (the part and three false
  positives) and an estimate took 5.9 s; registered at 0.5, only the part
  passed (SAM 3 scored it 0.58) and it took 1.9 s, same pose, same 15.3 GB
  peak. The service caches each estimator's threshold, so re-registering under
  the same id does not change it until the service restarts; use a new id.
* **Stale engine plans override settings.** The service picks a cached plan
  by filename prefix, so after a setting changes the old plan keeps being used
  (two refinement plans, `b14` and `b42`, were cached). Clearing it means
  deleting the plans inside the pod and restarting it.
* **The registration does not survive a deploy either.** It is saved as a
  Data asset, so register again after every deploy (about a minute).
* **The first warm-up is slow, later ones are not.** The service builds its
  TensorRT engines on first start (201 s); after a redeploy it was ready in
  18 s.
* **Weak false positives come back too.** Besides the part (0.999), two
  detections elsewhere in the scene scored 0.36 and 0.28, above the
  registration's 0.15 threshold. Step 3c must use the best detection, or
  raise the threshold.
* **Sim accuracy is an upper bound.** The images are clean renders with exact
  depth, the camera pose is exact, and the part is a plain cube; expect worse
  on hardware.
* **The original machine ran the older pipeline.** OMTS switched to
  `nvidia_pose_estimator_service` upstream in #161 (2026-10-22). Before that
  it used Intrinsic Core's `ioc_pose_estimator` on Triton, with an RF-DETR
  segmentation model from OMTS's GitHub release and FoundationPose weights
  from NGC, all fetched by Bazel with no gate. Restoring it would avoid SAM 3
  but re-add code current OMTS removed (`git show 29635ca^`); not needed now
  that SAM 3 works.

### Step 3c: `omts_app` runs the cell from perception

**Status: done (2026-10-29).** Run live in local simulation: OMTS's own app
(`omts_app --config=configs/rebot/app_config.yaml --num_cycles=3`) ran two
consecutive three-cycle runs successfully, about 50 s per cycle. Each cycle
finds the part on the bed from `view`, picks it with a 35° tilted grasp, sets
it down at A and picks it up again, then returns it to the bed at a random
offset, so every pick after the first is located by perception alone. How to
run it is the quick start in [`REBOT_OMTS_APP.md`](REBOT_OMTS_APP.md).

* `configs/rebot/app_config.yaml`: no machine, pinch gripper, perception
  infeed, `cuboid_center` with the new tilt and symmetry options, the printer
  as the enclosure, `view` as the transit frame, and a return shift of 4 x 4
  cm and ±10° around the bed centre.
* **No machine still means a placement.** OMTS's load and unload subtrees run
  without a machine too: they set the part down at the "machine" frames and
  pick it up again, skipping only door, vise and cycle actions (the plan had
  assumed pick then return). The reBot's machine frames are A, from the step
  2a grasp, in `configs/rebot/scene.updates.pbtxt`, which turns the cycle into
  the printer-tending round trip. The frame config test checks them again; it
  was briefly loosened on the wrong assumption.
* The pose estimator is registered at confidence 0.5 as
  `ai.intrinsic.rebot_printed_part_estimator`: the vision adapter uses the
  first estimate (`estimates[0]`), and at 0.15 the printer's toolhead came
  back first once.

* **Printer moved 10 cm further out, grasp tilted 60°, camera on top
  (2026-10-30).** For more clearance reaching into the printer, the bed
  centre is now at x = 0.56. At 35° the bed's far edge is out of reach there,
  so the grasp tilts 60° from vertical (`grasp.approach_tilt_degrees`). With
  the camera below the gripper, anything past about 50° put it into the bed
  (offline: 6 mm clear at 50°, 15 mm into the bed at 60°), and rolling the
  tool to lift it needs the wrist roll past ±180°. So the camera moved to the
  gripper's upper side (same offsets, `x: 0.07`): about 10 cm clear of the
  bed at the grasps. `view` moved to 0.38 m from the bed centre with the
  camera above the gripper, and A to 0.45 m at 130° with its frames
  recomputed for 60° (joints at least 0.21 rad from their limits at the
  pre-place pose; at 0.30 m there is no IK). Three cycles ran successfully in
  simulation.

OMTS changes, all defaulting to the old behaviour (**Flag**):

* **`grasp.approach_tilt_degrees`** (`cuboid_center`): pitches the grasp about
  the jaw axis so the approach leans away from the robot base, with the
  pre-grasp backed off along it. Needed because straight down cannot reach the
  bed at 0.46 m (offline: only the bed's near edge, barely, and no
  pre-grasp). With it, the computed grasp at the bed centre matched the step
  2a B frame exactly.
* **`grasp.yaw_symmetry_degrees`** (180 or 90): with 90, a tilted grasp may
  take the other pair of faces of a square part. FoundationPose returns any of
  a cube's equivalent orientations, so the long-axis rule leaned the first
  tilted grasp sideways, out of reach.
* **`robot.force_sensing`**: `false` replaces compliant touchdowns with linear
  moves to the seated pose. OMTS's existing runtime fallback could not help:
  `move_to_contact` fails while the tree is built, because no robot resource
  has a force-torque sensor to bind to.
* **Return placement keeps the pre-grasp offset.** `randomize_placement_frame`
  put the pre-grasp straight above the grasp; it now shifts the grasp and
  keeps the pre-grasp's offset, rotated with it (unchanged for vertical
  grasps).
* **The pick approach excludes workpiece<->enclosure contact.** Perception
  puts the part at its estimated pose, a fraction of a millimetre inside the
  bed, and the planner rejected the starting state.
* **`cycle.place_press_meters`**: without force sensing, the set-down moves
  (machine load and infeed return) go this far past the place pose along the
  approach, pressing the part onto its support before release, as a
  force-controlled touchdown would. Grasps are unaffected.
* **`cycle.workpiece_support_objects`**: objects the part rests on besides the
  enclosure (`rebot_ground` at A); their contact with the part is excluded
  wherever the enclosure's is, so the press is not a collision.

Learned:

* **A failed run leaves the part attached.** The app does not reset the world;
  if a run stops between attach and detach, the part stays a child of the arm,
  and later runs fail with collisions or "no path". Reparenting it to `root`
  fixes it (`REBOT_OMTS_APP.md`, quick start step 5).
* **Long swings near the printer need a waypoint.** One three-cycle run failed
  when a planned trajectory failed validation (link4 against the printer's
  base). Blending through `view` (`frames.transit_frame`) fixed it in the next
  two runs.
* **An unsupported part rides out with a finger.** Released even 1 mm above
  its support, the part often moved with one finger as the gripper opened:
  9.7, 30.1, 0.4, 30.1 and 30.1 mm at A in five recorded cycles (30 mm is a
  finger's full travel), while releases pressed onto the bed stayed put. It
  is intermittent, which is why the first single-cycle recordings missed it.
  Pressing the part onto its support before opening fixes it: with
  `cycle.place_press_meters: 0.003` all ten releases in five recorded cycles
  moved 0.3 mm or less (pressed 2.3 mm into the ground at A, 1.5 mm into the
  bed). Pressing in A's place pose itself does not work: the re-grasp there
  uses the same pose, so the part then sat lower in the gripper and hung
  above the bed on return (one 28.8 mm drag there). The gripper plugin's
  "stopped moving and failed to reach the commanded position" warning right
  after a release is a false alarm; it fires before the fingers move.
* **Still open:** the tilt follows the part's long axis, so an elongated part
  lying across the line to the robot would lean sideways (later work); the
  enclosure setting also excludes gripper<->printer while placing on the bed,
  broader than the demo's part<->printer.

### Step 3c-2: The Prusa Core One replaces the stand-in printer

**Status: done (2026-10-30).** Three `omts_app` cycles pass in simulation
with the Prusa Core One model (`models/printer`, from `feat/printer-sdf`).

* **Printer** (`configs/rebot/printer.updates.pbtxt`): turned yaw +90° so its
  front faces the arm, bed centre at x = 0.56. The bed top is at z = 0.1434,
  so the part (z = 0.1584), `view` and `vision.min_safe_z` (0.13) moved with
  it.
* **Grasp tilted 75°** (`grasp.approach_tilt_degrees`). At 60° the top of the
  wrist (link4) hits the Prusa's front rail (z 0.37–0.40) at the pre-grasp.
  At 75° the arm and camera clear the printer by at least 3.4 cm over the
  return area, with joints at least 0.61 rad from their limits.
* **`view`** has the camera 0.36 m from the bed centre at 60° elevation; it
  sees all four bed corners, and the pose estimator finds the part there
  (score 0.999, 0.36 m straight ahead).
* **A** moved out to 0.55 m at 130°, with its frames recomputed for 75°. At
  0.45 m the pre-place pose has no IK at this tilt; from 0.50 m it does, and
  at 0.55 m the joints stay at least 0.37 rad from their limits.
* **Press 6 mm** (`cycle.place_press_meters`). The press runs along the
  tilted approach, so its downward part is the press times cos(tilt): the
  3 mm that worked at 60° (1.5 mm down) is only 0.8 mm at 75°, and the part
  rode out with a finger again.
* **Return shift ±1 cm and ±5°** (was ±2 cm and ±10°). The gripper box is
  18 cm across the jaws, and the Prusa's internal towers leave about 25 cm.
  Offline, the gripper clears them by 0.7 cm at ±1 cm and ±5°, and hits one
  at ±2 cm and ±10° (one run failed that way).

Learned:

* **Check every arm link, not just the tool, against a new printer.** The
  first offline check covered the gripper and camera and passed; the run then
  failed on link4. [`research/tools/`](tools/) has the offline checks used
  here: `grasp_clearance` and `config_clearance` sample each link's collision
  mesh against the printer's boxes.
* **The fingers are two independent actuators in simulation.** Seeed's URDF,
  and so our SDF, has two prismatic finger joints with no coupling, while the
  real gripper drives both from one actuator. Intrinsic's scene object
  conversion drops `<mimic>` (Gazebo and Bullet support it), and the gripper
  plugin runs one PD controller per finger joint. Under contact the fingers
  come apart: they drift while a grasp rests on the bed and snap back when
  the arm lifts, and at release one finger can stay on the part or drag it.
  This is the likely cause of the release drag found in step 3c; the press
  remains the workaround. Feature request: question 4.1.8.
* **Weaker fingers don't fix the release.** The plugin derives its gains from
  finger mass (about 0.3 N of squeeze). With the finger mass quartered (an
  uncommitted experiment, about 0.08 N), part drift at release fell from
  0.7–2.8 mm to 0.2–0.9 mm over six releases without the press, but one
  finger then stayed on the part for 0.8–1.8 s in four of them. Whichever is
  lighter, part or finger, gets dragged. Reverted.
* **Finger speed and force are fixed in simulation.** The plugin counts a
  grasp as done, and welds, on the first 1 ms step where the first finger
  moves less than 0.01 mm. From rest that needs about 10 m/s², which today's
  closing force (0.85 N on 75 g) barely gives, so a lower joint effort or a
  slower controller would end grasps before the fingers close. The response
  rate is a constant in Intrinsic's code (15 rad/s), and the SDF velocity
  limit is not enforced on these force-driven joints (the fingers reach
  0.3 m/s against 0.243).
* **Prusa model notes:** its `bed_joint` is prismatic along Y, while a Core
  One's bed moves along Z (nothing moves it yet). `frame.obj` is a 29 MB
  plain file. The same merge moved the `omts` cell's printer (z 1.02 to 1.0,
  yaw +90° to −90°), which these checks did not cover.

### Step 3d: Camera-to-robot calibration in sim (optional)

* Run OMTS's hand-eye calibration tools (Charuco board, calibration skills,
  `tools/README.md`) on the reBot in sim. Not needed for accuracy in sim; it
  rehearses the path the hardware will need.

### After milestone 2 (sketch, to be re-planned at each step)

* Place at A (an outfeed) instead of returning to the bed.
* Cross-check perception against the 3MF plate layout for confidence.
* Try the MoveIt grasp planner backend for non-cuboid parts.
* Move to hardware on a Jetson once ICON support for the arm is available.
* Printer adapter and per-job cycle.

Found during milestone 2, not yet planned:

* **Pick one part among several detections.** The vision adapter takes the
  first estimate (`estimates[0]`); the 0.5 confidence threshold keeps false
  positives out today, but a bed with several parts, or a part next to a
  look-alike, needs a choice (nearest, most confident, or matched to the
  plate layout).
* **Elongated parts.** Studied in step 4a: with `yaw_symmetry_degrees: 90`
  a long part lying across the line to the robot is gripped by its ends, not
  leaned sideways, while its length fits the jaws.
* **Drop the press before release** once the fingers are coupled in
  simulation (question 4.1.8). The press is a simulation workaround, and on
  hardware it may not be wanted.
* **Fix the Prusa model's `bed_joint`:** prismatic along Y, while a Core
  One's bed moves along Z (step 3c-2). Nothing moves it yet; needed before
  the cell drives the bed.
* **Tight clearances in the Prusa.** The gripper spans most of the bed
  between the internal towers, so the return area is ±1 cm sideways and
  ±5°, and parts printed off-centre may be out of reach. Options: a narrower
  gripper; a horizontal grasp (approach along the bed, never tried); or
  moving the arm, whose placement is free.
* **A real camera bracket.** The mount pose is a guess (step 3a), and `view`
  and the tilt limits depend on it; check them again against a real bracket
  and its cable routing.
* **Offline checks don't model self-collision**, and only `cuboid_sweep`
  checks the ground at A ([`tools/README.md`](tools/README.md)); confirm
  changes near the ground in simulation.

## 5c. Milestone 3: More Graspable Geometries

Goal: know which printed parts the cell can pick, and widen the set. Starting
with cuboids under 100 mm a side, brute force: sweep sizes offline, then
confirm the boundaries in simulation.

### Step 4a: Which cuboids are graspable

**Status: done (2026-11-03).** Offline sweep of cuboids standing as printed
on the Prusa's bed, and trials in simulation with six test parts.

* **`research/tools/cuboid_sweep`** replays the grasp `omts_app` publishes
  for a cuboid at the bed centre and checks: fit between the open jaws (5 mm
  per side); the open fingers and gripper body against the part and printer
  on the approach; the closed fingers and body at the grasp and through the
  press back onto the bed; the same at A on the ground; and reach. It also
  reports the finger pad area on the gripped face.
* **Trials:** `models/test_cuboids/` holds five test cuboids, deployed with
  `//:rebot_solution` only under `--//:test_cuboids` and parked out of
  reach. `research/tools/cuboid_trial` puts one on the bed and writes A's
  frames at its height and an `app_config` naming it. Register each part
  with the prompt "cube": "box" found nothing.

Results (75° tilt, yaw symmetry 90):

| Limit | Boundary | What sets it |
| --- | --- | --- |
| Height | at least 25 mm | The gripper body reaches the bed (or the ground at A) when the part is pressed down before release; 22 mm failed at A in simulation. |
| Width between the jaws | 90 mm with 5 mm per side; 95 mm worked in simulation | 100 mm maximum opening. |
| Turn on the bed | within ±14° of a grasp direction, any size | The gripper body or the open fingers hit the internal towers; 12° passed and 16° failed in simulation. |
| Reach | not limiting at the bed centre | |

| Part (mm) | Yaw | Simulation |
| --- | --- | --- |
| 40×40×22, 40×40×20 | 0° | Picked; then the gripper body hit the ground at A during the press. |
| 80×20×40, 95×20×40 | 90° | Picked by their ends and returned. |
| 40×40×40 | 12° / 16° | Passed / gripper body hit a tower. |

Learned:

* **Elongated parts don't lean sideways with yaw symmetry 90.** The grasp
  turns a quarter and grips the ends instead, as long as the length fits the
  jaws. With symmetry 180 the lean goes sideways and the open fingers hit a
  tower, as step 3c warned.
* **Thin parts are held by the fingertips only.** `cuboid_center` puts the
  fingertips at the part's centre, so a part thin along the approach (the
  20 mm ends of the long parts) only meets the tapered tips, which narrow to
  about 3 × 2 mm. The weld in simulation holds anyway, so a pass there does
  not mean a real grip.
* **Deeper grasps raise the contact area.** Pushing the grasp 30 mm past
  the centre, horizontally along the approach, raised the smallest pad
  contact over the sweep from 93 to 365 mm² (median 207 to 777), and the
  long parts, the 40 mm cube and the default part passed in simulation that
  way. Pushing along the tilted approach instead lowers the gripper onto the
  bed. The limit is the gripper body, 73 mm behind the tips, reaching the
  part's near face: at 30 mm, 89 of 125 sizes still fit. **Stashed:** the
  option (`grasp.grasp_depth_meters`, a change to OMTS's config, vision
  adapter, pick and frame calculator) is in `git stash` on
  `rebot-grasp-target`. A's frames must include the same push
  (`a_frames --depth`).
* **The offline checks needed two fixes.** The gripper body's bounding box
  made them too strict (now its collision mesh), and they did not check A
  or the press before release (now both). Even so, the 20 mm part's pick
  passed in simulation where the sweep puts the body 1–2 mm into the bed, so
  treat the height limit as ±3 mm.

Next:

* Decide on the grasp depth: restore the stashed option and pick a default
  per part, or derive it from the part's size (the calculator does not know
  the size today).
* Make the yaw symmetry a per-part choice: 90 suits square parts and lets
  long ones be gripped by their ends; 180 keeps long parts gripped across.
* Other shapes: cylinders, L-shapes, parts lying on another face.

---

## 6. Findings

### 6.1 reBot top-down reach (checked offline, 2026-10-20)

Method: sample 300k random joint configurations within the URDF limits, and
keep those where the tool (`gripper_end`, the TCP in Seeed's MoveIt config)
points within 14° of straight down. Horizontal reach is measured from the base
axis; tip height from the base frame. Self-collision is ignored.

| Tip height above base | Top-down horizontal reach |
| --- | --- |
| −0.10 m | ~0.05–0.55 m |
| 0.00 m | ~0.02–0.52 m |
| +0.10 m | ~0.06–0.49 m |
| +0.20 m | ~0.16–0.36 m |

* Both RS URDFs below agree within a few centimetres.
* The wrist roll (`joint6`) turns exactly about the approach axis, with
  ±3.14 rad of travel, so top-down grasps at any yaw work.
* Maximum reach in any orientation is 0.78 m, consistent with Seeed's 754 mm
  figure.

So the gripper can point roughly down (within 14°) over about half a metre
around the base, at bed heights near the base. That is wider than the SO-101's
0.32 m, so reach is not a concern for milestone 1.

Step 1b refined this: pointing **exactly** straight down works over a narrower
band, about 0.25–0.40 m out at 0–0.15 m up, because `joint4`'s upper limit
(1.69 rad) runs out first. Intrinsic's motion planner reached the two demo
frames inside that band (0.30 m out, 0.05 m up). Size the bed position and
grasp heights to that band, or allow a few degrees of tilt.

### 6.2 reBot gripper finger limits

Seeed's RS URDF (identical in reBot-DevArm, reBotArm_control_py and
reBotArmController_ROS2, apart from mesh paths) gives the two fingers different
travel: 0–0.05 m and 0–0.0715 m, with no mimic tag.

Seeed's [reBot-Isaacsim](https://github.com/Seeed-Projects/reBot-Isaacsim) repo
(MIT) fixed this in its RS URDF, `urdf/00-arm-rs_asm-v3/urdf/00-arm-rs_asm-v3.urdf`
(commit of 2026-08-02):

* 0.0715 m was an authoring error. Both fingers use the same mesh, their axes
  are exactly opposed, and the real gripper is one motor driving two racks
  through one pinion, so the fingers move 1:1. Both are now 0–0.05 m, a
  50 mm stroke per finger, matching the motor's calibrated travel.
* Finger effort and velocity are derived from the motor (1904 N, 0.243 m/s)
  instead of placeholder values.
* The 1:1 coupling is authored in the repo's USD and MuJoCo models, but **not**
  as a `<mimic>` tag in the URDF. Our sim model has to add the coupling.
* The same commit documents real-gripper measurements (backlash about ±0.37 mm)
  and Python SDK pitfalls worth reading before hardware work.

That URDF also uses a different sign convention for `joint2`/`joint3`
(−3.14–0 instead of 0–3.14) and slightly wider `joint4` limits. The reach is the
same either way. **Use the reBot-Isaacsim RS URDF as the base for the sim model,
add a finger mimic, and confirm the joint conventions against Intrinsic's
hardware support once it exists.**

---

### 6.3 Getting a non-UR arm into ICON, and fallback arms

From the arm comparison done before the reBot was chosen (removed
2026-10-30; the full comparison is in git history at `b5b4eee`). It matters
again if ICON support for the reBot does not materialize or another arm is considered.

* **The path for a third-party arm.** ICON accepts a non-UR arm through its
  ROS 2 bridge, `icon_hwm_controller`, which needs a `ros2_control` hardware
  plugin for the arm (intrinsic-core `ros2_bridge_tutorial.md`). The bridge
  runs in lockstep with ICON, carries arm joints only (the gripper is
  commanded outside ICON), and targets ROS 2 Kilted. Without a working
  plugin, the fallback is a custom real-time ICON hardware module in C++,
  weeks of work. The arms therefore differ mainly in how much driver work
  comes first: vendor-maintained, community-maintained, or none.
* **reBot driver risks, if we had to drive it ourselves.** The only
  `ros2_control` plugin is the community
  [`robstride_ros2_control`](https://github.com/s2015-turtle/robstride_ros2)
  (MIT), tested only against a simulated motor. Open: it has never run on
  hardware; it passes CAN frames as ROS messages through `ros2_socketcan`,
  not built for hard deadlines (the bus itself should allow about 500 Hz for
  seven motors at 1 Mbit/s); the gripper is a seventh motor on the same bus,
  and only one process can own the bus, so it must run in the same plugin;
  and the motors must use RobStride's private protocol (Seeed's configuration
  suggests they do). Seeed's own ROS 2 stack drives the real arm from a
  Python node; its `ros2_control` setup is a MoveIt stand-in.
* **Fallback arms.** UFactory Lite 6: the only low-cost candidate with a
  vendor-maintained plugin
  ([`xarm_ros2`](https://github.com/xArm-Developer/xarm_ros2), no Kilted
  branch yet; its gripper is outside `ros2_control`, so it needs its own
  `GripperInterface`), closed hardware, about twice the reBot's price.
  SO-101: by far the cheapest, open hardware, a generic Feetech plugin, but
  five joints, a pivoting jaw that does not self-centre, and ±3–5 mm
  (estimate). Ruled out: Annin AR4 (60 Hz serial driver, backlash),
  OpenMANIPULATOR-X (no wrist roll, so no top-down grasps at any yaw), AgileX
  PiPER, Interbotix and ARX X5 (no usable `ros2_control` driver), and larger
  vendor-supported arms (two to five times the price for capability a print
  does not need).
* **What the arm has to do,** for any replacement: pick parts of tens of
  grams (the gripper counts against the payload), grasp top-down at any yaw
  (a wrist roll), work without a force-torque sensor, and stay low-cost and
  preferably open hardware. Accuracy has no fixed requirement; the gripper's
  sideways slack and its margin above the bed set it.

## 7. Unverified Items

Check these before building on them.

* **Getting images back to the host through Intrinsic.** Triggering a
  capture from a host script works (the `capture_images` skill, and pose
  estimation; `REBOT_OMTS_APP.md`, Debugging), but the images were viewed on
  Gazebo's camera topics, never returned to the host through Intrinsic
  (`tools/calibration/sample_calibration_poses.py` still sets
  `camera = None`). The study avoids it by reading the printer's camera
  directly.

---

## 8. Housekeeping

* **Local fixes for `20261012.0`:** written when OMTS pinned that release;
  it now pins `20261022.0` (`50927e35`, #169). `b7cc503` (no camera args to
  `estimate_pose_multi_view`) is no longer a local fix: upstream made the same
  change in #157. `c98d44a` (attach and detach via the robot, on this branch
  as `828bbf3`) works around `attach_object_to_robot` parenting to the
  reference's final entity. The pinned release includes `3d137157`, which
  attaches to a gripper's base entity again, so the workaround is now
  optional, though still correct; going back to attaching via the gripper is
  untested.
* **Upstream gap, still open at `48be90d`:** the solution does not declare
  `dio_wait_for_input`, so `DioCncMachine.build_wait_cycle_complete_task`
  sleeps and never checks the input (study section 1).
* **Abandoned draft:** an early draft of the study was started as a Claude Doc
  (`https://claude.ai/code/artifact/3ea4bddf-2151-46ba-b2d6-65779142ea43`),
  with only two sections filled in. The Markdown study replaces it; it can be
  deleted.
