# Handoff: 3D Printer Tending

Current state and plan for the printer-tending project, so work can continue on
any machine. The printer-side design is [`PRINTER_UNLOADING.md`](PRINTER_UNLOADING.md);
the arm comparison is [`ARM_SELECTION_REQUEST.md`](ARM_SELECTION_REQUEST.md).
This file records what has been decided and what to do next.

---

## 1. Where Things Are

| Item | Location |
| --- | --- |
| Repo | Fork `https://github.com/NachoRosa95/intrinsic-omts`, branch `research` |
| Research commit | `fbb9606` "Printer unloading viability research", on top of upstream `main` at `48be90d` (#151). Upstream has since been merged in through #156. |
| Printer design notes | `research/PRINTER_UNLOADING.md` (trimmed 2026-10-22; the full feasibility study, including the SO-101 evaluation, is at commit `6b33ad7`) |
| Arm comparison (decided) | `research/ARM_SELECTION_REQUEST.md` |
| SO-101 URDF | `research/so101_new_calib.urdf`, from the earlier SO-101 evaluation; superseded by the reBot decision |
| reBot URDFs | Base for the sim model: [Seeed-Projects/reBot-Isaacsim](https://github.com/Seeed-Projects/reBot-Isaacsim) `urdf/00-arm-rs_asm-v3/urdf/00-arm-rs_asm-v3.urdf` (MIT), which fixes the gripper limits (section 6.2). Originals: [Seeed-Projects/reBot-DevArm](https://github.com/Seeed-Projects/reBot-DevArm) `Rebot_Arm_description/` (Apache-2.0 / CERN-OHL-W-2.0). |
| Reference source | `intrinsic-core` at `main` (past `20261012.0`). OMTS itself pins the `20261012.0` release in `MODULE.bazel` (`INTRINSIC_CORE_RELEASE`), so check behavior against that tag when it matters. |

Steps 1a–1d are done in simulation (section 5), which completes milestone 1:
the reBot picks a printed part with its gripper, carries it in Gazebo, and
places it, with RViz (the belief world) matching. To deploy and run the demo,
see [`REBOT_DEMO.md`](REBOT_DEMO.md). Milestone 2 (section 5b) moves the cell
onto OMTS's own app with a wrist camera; how to run what works so far is in
[`REBOT_OMTS_APP.md`](REBOT_OMTS_APP.md).

---

## 2. Setting Up the New Machine

```bash
# Upstream OMTS as origin (Git LFS is required for *.glb meshes)
git lfs install
git clone https://github.com/intrinsic-ai/intrinsic-omts.git
cd intrinsic-omts

# The fork, which holds the research branch
git remote add fork https://github.com/NachoRosa95/intrinsic-omts.git
git fetch fork && git checkout -b research fork/research

# intrinsic-core next to it, for reading drivers, skills and tutorials
cd .. && git clone https://github.com/intrinsic-ai/intrinsic-core.git
```

This matches the working machine: `origin` is upstream
(`intrinsic-ai/intrinsic-omts`) and `fork` is
`NachoRosa95/intrinsic-omts`. Push research work to `fork`.

Perception (milestone 2, step 3b) also needs the NVIDIA pose estimator's
model assets, including the gated SAM 3 weights; see step 3b.

For quick analysis scripts (URDF kinematics, 3MF parsing), install `numpy`. The
original machine had no system pip; it was installed per-user with
`get-pip.py --user`, then `python3 -m pip install --user numpy`.

---

## 3. Decisions Taken

### 3.1 Kickoff with Intrinsic (2026-10-20)

| Decision | Consequence |
| --- | --- |
| **Arm: Seeed reBot Arm** | Replaces the SO-101 plan (study section 7, at commit `6b33ad7`). The B601-RS is the working assumption until the variant is confirmed. |
| **Intrinsic adds ICON support for the reBot** | Hardware only, likely for the B601-RS. We do not write or validate a driver; the community-driver risks in `ARM_SELECTION_REQUEST.md` no longer apply to us. The simulation model is ours to build. |
| **Deadline: end of 2026, scope flexible** | Intrinsic's hard deadline. Cut scope rather than slip; the spiral steps make that possible. |
| **Target compute: NVIDIA Jetson (Orin or Thor)** | Intrinsic is adding ARM support; treat it as a given. Seeed sells reBot kits bundled with Jetson Orin or Thor. |
| **Simulation first** | Hardware waits for Intrinsic's ICON support. All milestone 1 work runs in Gazebo (`--operation_mode=sim`). |
| **No printer yet** | The target printer stays undecided. The arm first works on its own in an empty cell, with no obstacles. |
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
| **Locate the print with an Orbbec camera under the wrist, as OMTS does** | Overrides two study decisions in 3.2: vision replaces the 3MF plate layout as the localization source, and a wrist depth camera replaces the fixed RGB camera. The plate layout stays as a later confidence check. |
| **Reuse OMTS and Intrinsic Core first; minimize custom code** | Part of the goal is to measure how easy the integration is. Every change to OMTS or a deviation from its design is flagged in the step that needs it. |
| **Run the reBot cell through `omts_app`** | The pick-and-place `rebot_demo` was custom; the perception milestone moves the cell onto OMTS's own app and tree, with `machine: None` like `lab_bb_01`. |
| **No force sensing still holds** | OMTS's compliant touchdowns (`move_to_contact`) must become optional (milestone 2, step 3c). |

---

## 4. Open Questions

### 4.1 For Intrinsic (1–3 answered 2026-10-20)

1. **Scope of the reBot ICON support:** hardware only. No simulation model and
   no gripper. For simulation we use Intrinsic's generic Gazebo stand-in with a
   model built from the URDF (step 1b).
2. **Variant:** to be decided; the B601-RS is most likely.
3. **Timeline:** hard deadline at the end of 2026, with scope flexible to meet
   it.
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

7. **New (2026-10-26): does the NVIDIA pose estimator run on a Jetson?**
   `nvidia_pose_estimator_service` (FoundationPose with SAM 3) runs on the
   desktop GPU in sim. Milestone 2 depends on it; the Jetson target needs an
   ARM64 build with enough GPU memory.

### 4.2 For the project owner

1. **Target printer and firmware.** Deferred: decides the status API, camera
   source and 3MF variant. Needed before the printer enters the cell.
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
* `configs/rebot/orbbec_gemini.updates.pbtxt` mounts the camera under the
  wrist, on the flange like `configs/omts/`: 7.6 cm out along the flange axis
  (OMTS: 7.8 cm), 7 cm off it on the gripper's -x side, which is below the
  gripper in the tilted grasps and at `view`. It looks parallel to the tool
  axis (no tilt), with its baseline along the jaw axis.
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

**Status: blocked (2026-10-28), waiting for SAM 3 access.** Access to
`facebook/sam3` has been requested on HuggingFace.

* Add `nvidia_pose_estimator_service` and `ioc_train_service`, and register an
  estimator for `ai.intrinsic.rebot_printed_part` with
  `register_using_ioc_train_service` (README 4.3). The service is OMTS's,
  unchanged; only the registration is new, because FoundationPose fits the
  registered object's exact model and OMTS's raw-stock registration does not
  match the printed part.
* Demo: `run_pose_estimation` at `view`, compared with the part's pose in
  Gazebo. Record the error and how yaw behaves on a near-square part.

Learned so far:

* **OMTS's perception needs a gated model.** `nvidia_pose_estimator_service`
  starts only once three model Data assets are installed on the cluster
  (Intrinsic Core's `nvidia_pose_estimator` README, section 2): FoundationPose
  and FoundationStereo, which Bazel downloads, and SAM 3, which it cannot.
  `facebook/sam3` is gated with manual approval on HuggingFace, so each user
  must request access, log in (`hf auth login`), run Intrinsic's export script
  on a GPU and install a 3.3 GB bundle with `inctl asset install`. Nothing in
  `intrinsic-core`'s guides avoids this. None of it was set up on this
  machine.
* **The original machine ran the older pipeline.** OMTS switched to
  `nvidia_pose_estimator_service` upstream in #161 (2026-10-22). Before that
  it used Intrinsic Core's `ioc_pose_estimator` on Triton, with an RF-DETR
  segmentation model from OMTS's GitHub release (`segmentation.tar.gz`) and
  FoundationPose weights from NGC, all fetched by Bazel with no gate, and
  registration without a text prompt.
* **Stopgap, not taken:** restore that pipeline in `rebot_solution` while
  waiting. `ioc_pose_estimator` is still in the pinned Intrinsic Core
  (`20261012.0`) and its weights still download freely, but #161 removed the
  model packaging, build rules, dependencies and registration tool from OMTS
  (see `git show 29635ca^`), so it would re-add code current OMTS dropped
  (**Flag**). It is also unknown whether the pretrained RF-DETR model segments
  the printed part. Worth trying only if access takes long.
* Unchecked: whether deploying `rebot_solution` removes separately installed
  model assets, as it replaced `omts_solution`'s. If it does, add the three
  model Data asset targets (in `nvidia_pose_estimator`'s BUILD) to the
  solution.

### Step 3c: `omts_app` picks the part from perception

* Add `configs/rebot/app_config.yaml`: `machine` omitted, `pinch` gripper,
  `perception` infeed, `cuboid_center` grasp planner, the `view` frame. The
  lab cell's flow then runs: pick from perception, return to the infeed at a
  random `return_shift`.
* **Flag: compliant touchdown.** OMTS's pick and return end in
  `move_to_contact`, which needs force sensing the reBot does not have. Try
  user settings first: OMTS already wraps the touchdown in a retry and a
  fallback linear move to the seated pose (`create_seated_approach_tasks`,
  added for Gazebo timeouts), so adding `move_to_contact` to `rebot_solution`
  and a short `touchdown_timeout_seconds` may be enough. Unverified: whether
  the skill fails at run time (the fallback catches it) or when the tree is
  built (no force-torque part in the reBot's ICON), and every pick and place
  would log two failed attempts. The clean fix is code: a config switch for a
  plain linear move. Giving the simulated reBot a force sensor would also work
  but hides the gap until hardware, so not that.
* **Flag: top-down grasp only.** The `cuboid_center` frame calculator makes a
  vertical grasp (it only chooses among four yaws) and has no orientation
  setting, and the reBot could not reach straight down inside the printer
  (step 2a). Also check its raw-stock axis assumptions on the printed part.
  Options, not yet decided:
  * **Move the arm.** Its placement is free; further back, or at another
    height, may open up straight-down grasps inside the printer.
  * **Horizontal grasp.** Never tried. The `moveit` backend can sample side
    approaches (square to a face), but needs a MoveIt setup for the reBot.
  * **Code change:** an approach tilt in `cuboid_center`'s config, as in the
    step 2a frames.
* `rebot_demo` stays as it is.
* Demo: `omts_app --config=configs/rebot/app_config.yaml --num_cycles=N`.
  Each cycle sets the part down at a new random offset, so every pick after
  the first is located by perception alone.

### Step 3d: Camera-to-robot calibration in sim (optional)

* Run OMTS's hand-eye calibration tools (Charuco board, calibration skills,
  `tools/README.md`) on the reBot in sim. Not needed for accuracy in sim; it
  rehearses the path the hardware will need.

### After milestone 2 (sketch, to be re-planned at each step)

* Place at A (an outfeed) instead of returning to the bed.
* Cross-check perception against the 3MF plate layout for confidence.
* Try the MoveIt grasp planner backend for non-cuboid parts.
* Move to hardware on a Jetson once Intrinsic's ICON support lands.
* Printer adapter and per-job cycle.

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

## 7. Unverified Items

Check these before building on them.

* **Host-side image capture through Intrinsic** was never exercised in this
  repo (`tools/calibration/sample_calibration_poses.py` sets `camera = None`).
  The study avoids it by reading the printer's camera directly.

---

## 8. Housekeeping

* **Local fixes for `20261012.0`:** both are still needed with the pinned
  release. `b7cc503` (no camera args to `estimate_pose_multi_view`) stays
  needed on intrinsic-core `main` too. `c98d44a` (attach and detach via the
  robot) works around `attach_object_to_robot` parenting to the reference's
  final entity. intrinsic-core `main` (`3d137157`) attaches to a gripper's
  base entity again, so `c98d44a` becomes optional, though still correct,
  once OMTS pins a release that includes that change.
* **Upstream gap, still open at `48be90d`:** the solution does not declare
  `dio_wait_for_input`, so `DioCncMachine.build_wait_cycle_complete_task`
  sleeps and never checks the input (study section 1).
* **Abandoned draft:** an early draft of the study was started as a Claude Doc
  (`https://claude.ai/code/artifact/3ea4bddf-2151-46ba-b2d6-65779142ea43`),
  with only two sections filled in. The Markdown study replaces it; it can be
  deleted.
