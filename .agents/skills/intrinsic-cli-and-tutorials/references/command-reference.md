# Command reference (what each command does and why)

Conventions:

- The cluster gateway is `localhost:17080` (gRPC). Zenoh (ROS 2 bridge): `7447` goes through the Istio ingress, and `17447` goes to the `zenoh-router-host` LoadBalancer. Both reach the same router (verified on this cluster). `ss -ltn` does **not** list them because k3s svclb uses iptables. Probe with `timeout 2 bash -c '</dev/tcp/127.0.0.1/17447' && echo open` or `kubectl get svc -A | grep 7447`.
- Every `inctl` subcommand accepts `--address`. Alternatives are `--org` + `--solution`/`--cluster` for Flowstate.
- Global flag `-o/--output text|json|ndjson|tab`.
- OMTS commands run from the repo root, `/home/berti/gits/intrinsic-omts`. The tutorials say `~/intrinsic-omts`.

## One-time setup (getting_started.md)

| Command | What / why |
|---|---|
| `sudo apt install -y git git-lfs && git lfs install` | Meshes and models are git-lfs objects. Without them, glb files are pointer stubs and SDF conversion fails. |
| `gh auth login` | Lets you fetch the repos and release artifacts. |
| `export CORE_TAG=20261012.0; gh repo clone intrinsic-ai/intrinsic-core -- --revision="$CORE_TAG"` | Gets core sources (scripts, models, docs). |
| `~/intrinsic-core/intrinsic_runtime/setup_k3s.sh` | Installs single-node Kubernetes (k3s), which hosts the runtime. |
| `sudo apt install -y util-linux-extra && newgrp containerd` | Gives your shell containerd group access. |
| `gh release download --repo intrinsic-ai/intrinsic-core "$CORE_TAG" --pattern intrinsic-base-linux-amd64.tar --output /tmp/intrinsic-base-linux-amd64.tar --clobber && tar -C /tmp -xvf /tmp/intrinsic-base-linux-amd64.tar && /tmp/intrinsic-base` | Deploys the Intrinsic Core runtime ("intrinsic-base") into k3s. Expect `ChartAssignment app-intrinsic-base All pods are running`. |
| `gh release download ... --pattern inctl-linux-amd64` then `sudo mv` it to `/usr/local/bin/inctl` and `chmod +x` | Installs the CLI. |
| `sudo ~/intrinsic-core/intrinsic_runtime/setup_nvidia.sh` | GPU support in k3s, needed for perception and FoundationPose. |
| `sudo ~/intrinsic-core/intrinsic_runtime/setup_realtime.sh && sudo reboot` | RT kernel parameters and node labels. **Only for real robots.** Without it ICON pods stay Pending in real mode. |
| Bazelisk to `/usr/bin/bazelisk`, plus `ln -sf /usr/bin/bazelisk /usr/bin/bazel` | Bazel version manager. **Never `sudo bazel`.** |
| `sudo ln -s /usr/lib/x86_64-linux-gnu/libxml2.so.16 /usr/lib/x86_64-linux-gnu/libxml2.so.2` | LLVM compatibility on Ubuntu 26.04. |

## Deploy and solution lifecycle

| Command | What / why |
|---|---|
| `bazel run //:omts_solution -c opt [--config=lab_bb_01 \| --//:setup=lab_bb_01] -- --address localhost:17080 --operation_mode=sim` | Builds all assets, uploads them, deploys, and waits for ready. This **records the initial world** from instances + `object_world_updates`. Flags before `--` go to Bazel (`-c opt`, `--config`); flags after go to the deployer. The first build is long, because core builds from source at the pinned commit. OMTS `default_operation_mode="real"`, so **always pass `--operation_mode=sim`**. |
| `TMPDIR=~/tmp bazel run //:omts_solution -- ...` | Use when `/tmp` is too small for container images. |
| `inctl asset instance list --address localhost:17080` + `kubectl get pods -n app-resources` | Shows what is deployed locally. `inctl solution list`/`get` only work against Flowstate (`--org`/`--project`) and **reject `--address`** (verified in the 20261012.0 binary and the c40e02a source). |
| `kubectl logs -n app-resources rs-gazebo-simulator-0 --tail=20` | Sim vs real: `hardware_module_launcher` lines mean sim; `noop.go ... Server is now listening` means real. |
| `inctl solution stop --address localhost:17080` | Stops the solution. Required before switching sim/real or swapping a robot HWM. |
| `bazel run //src:omts_app -- --address=localhost:17080 --config=configs/<cell>/app_config.yaml [--num_cycles=N] [--simulation_mode=reality\|preview\|fast_preview] [--grasp_planner=cuboid_center\|moveit]` | Runs the OMTS process (SBL behavior tree). The cell must match the deploy. `--simulation_mode` is the executive preview mode, not the deploy mode; keep `reality` for Gazebo runs. |
| `bazel run @intrinsic-core//intrinsic_perception/intrinsic/perception/service/ioc_train_service/tools:register_using_ioc_train_service -- --address=localhost:17080 --scene_object_id=ai.intrinsic.raw_stock_2x3x5 --pose_estimator_id=ai.intrinsic.raw_stock_2x3x5_estimator_text --refinement_iters=5 --confidence_threshold=0.15 --visibility_threshold=0.15 --text_prompt="cuboid"` | Registers the text-prompted pose estimator that `app_config.yaml` uses with `nvidia_pose_estimator_service` (OMTS README §4.3). Re-run it after a solution restart if `omts_app` reports the estimator NOT_FOUND. The old `//tools/pose_estimation:*` targets were removed in OMTS #161. |
| `bazel run @intrinsic-core//intrinsic_perception/intrinsic/perception/service/ioc_pose_estimator:run_pose_estimation -- --address=localhost:17080 --service_name=nvidia_pose_estimator_service --camera_name=orbbec_camera --pose_estimator_id=ai.intrinsic.raw_stock_2x3x5_estimator_text` | Optional check of the detection against the camera feed. |
| `bazel build --nobuild //...`, `bazel test //tests/...`, `bazel test //tests/unit:test_world_configs` | Analysis, unit tests, and scene-config tests. Avoid a bare `bazel test //...`, which builds the solution images. |

## Assets and instances

| Command | What / why |
|---|---|
| `inctl asset list --address localhost:17080 [-o json \| jq]` | Installed asset types. Use `--asset_types` to filter and `--output_type id\|id_version\|...` to change the format. |
| `inctl asset install <bundle.tar \| id.version \| solution/id>... --address localhost:17080 [--policy add_new_only\|update_unused\|update_compatible]` | Uploads and registers asset types. It does **not** create an instance. |
| `tarball=$(bazel --quiet cquery --output=files //pkg:target)` | Finds the bundle path that a target produced. |
| `inctl asset uninstall <id> --address localhost:17080` | Removes an asset type, e.g. a skill. |
| `inctl asset instance list --address localhost:17080` | Lists instances (scene objects + services). The alias `instances` also works. |
| `inctl asset instance get <name> --view full --address localhost:17080` | Shows an instance's config. |
| `inctl service add <asset_id> --name <instance> --address localhost:17080 [--config file.binpb]` | Creates an instance of a service, hardware device **or scene object**. `--config` is a *binary* Any. Run `inctl world reset` afterwards so a scene object appears. |
| `inctl service delete <name> --address localhost:17080` | Removes an instance. |
| `inctl service state list\|get <name>\|restart <name>\|enable <name>\|disable <name> --address localhost:17080` | Service runtime state. |
| `inctl skill list --address localhost:17080` | Lists installed skills. |
| `bazel build @intrinsic-core//intrinsic/skills/examples:adder_skill` | Example of building a core skill bundle from OMTS. |

## World

| Command | What / why |
|---|---|
| `inctl world reset --address localhost:17080` | Copies `init_world` to the belief `world`, then restarts the simulation from it. Undoes live edits and makes newly added instances appear. Warn the user if real hardware is attached. |
| `bazel --quiet run //tools/world:inspect_world -- --address localhost:17080` | Prints objects, joint configs, skills, resources and key frame poses. |
| `bazel --quiet run //tools/world:apply_scene_updates -- --address localhost:17080 [--setup omts\|lab_bb_01] --files <f1> [<f2>...] [--no-reset_sim] [--update_init_world]` | Applies `.updates.pbtxt` files live. **With no `--files`** it applies every `configs/<setup>/*.updates.pbtxt` alphabetically, including `raw_stock_in_vise`. On real hardware it skips joint updates. |
| `bazel run //tools/world:edit_frames_rviz -- --address=localhost:17080 --zenoh_endpoint=tcp/127.0.0.1:7447 [--setup=lab_bb_01] [--frame view place_vise] [--apply_on_start]` | 6-DoF RViz frame editor that auto-saves to the pbtxt. Needs a sourced ROS 2 shell. `--apply_on_start` is off by default. |
| `inctl world print [--world_id world\|init_world\|sim_world]` | Prints a world. **Only in inctl built from core ≥ c40e02a**; the 20261012.0 release binary lacks it. Otherwise use `inspect_world`. |
| `bazel run //tools/jogging:store_frame -- <name> --address=localhost:17080 [--scene_updates_file ...]` | Saves the current TCP pose as a frame in the pbtxt and the live world. |
| `bazel run //tools/jogging:store_joint_config -- <name> --address=localhost:17080` | Saves current joints as a named config in world + init_world (no file). |
| `bazel run //tools/calibration:calibrate_camera -- --address=localhost:17080 --camera=orbbec_camera --output_updates_file=configs/omts/orbbec_gemini.updates.pbtxt` | Hand-eye calibration. Writes the camera mount pose file. The OMTS README calls the target `calibrate_camera_to_robot`, but the BUILD target is `calibrate_camera`. |
| `bazel run //tools/calibration:update_robot_kinematics -- --address=localhost:17080 --resource_id=ur_module` | Syncs real UR factory kinematics into the world. |

## Motion and I/O (moves hardware in real mode, so confirm with the user)

| Command | What / why |
|---|---|
| `inctl icon status --address localhost:17080 --instance_name icon` | Operational status (ENABLED/FAULTED), faults, safety. `Unimplemented` means a wrong instance name or ICON is not running. |
| `inctl icon clear-faults ... --instance_name icon` | Clears faults, e.g. after a Gazebo restart (`The server is gone`). It may need to run twice. |
| `inctl icon enable\|disable ... --instance_name=icon` | Enables or disables all parts. Disable then enable to kill a stale session (`Part 'arm' is already in use`). |
| `inctl icon list-parts\|config\|list-actions --address localhost:17080 [--instance_name icon]` | Introspects ICON parts, the active config, and action signatures. |
| `inctl gpio list-signals\|read-signals --signal_names=a,b\|write-signal --signal_name=x --value=true --address localhost:17080` | GPIO through ICON ADIO. |
| `bazel run //tools/jogging:jog_interactive -- --host=localhost --port=17080 --instance=icon` | Keyboard joint jog. Pick a joint 0–5, then the arrow keys move it ±0.01 rad. |
| `bazel run //tools/jogging:move_to_frame -- --address=localhost:17080 --frame=view --motion_type=ANY` | Moves the TCP to a named frame. |
| `bazel run //tools/jogging:move_to_joint -- home --address=localhost:17080` or `--joints 0 -1.57 1.57 -1.57 -1.57 0` | Moves to a joint target. |
| `bazel run //tools/gripper:control_gripper -- --address=localhost:17080 --gripper_type=robotiq\|dio --action=open\|close` | Opens or closes the gripper. |
| `bazel run //tools/machine:control_machine -- --address=localhost:17080 --action=open_door\|close_door\|open_vise\|close_vise\|trigger_cycle\|wait_cycle` | CNC door and vise DIO, plus belief joint sync. |

## Visualization

**RViz (belief world):**

```bash
sudo apt install ros-lyrical-desktop ros-lyrical-rmw-zenoh-cpp
source /opt/ros/lyrical/setup.sh
export RMW_IMPLEMENTATION=rmw_zenoh_cpp
export ZENOH_CONFIG_OVERRIDE='mode="client";connect/endpoints=["tcp/127.0.0.1:7447"]'   # 17447 on newer runtimes
choom -n 1000 ros2 run rviz2 rviz2
```

`choom` lets the kernel OOM-kill RViz first. In RViz:

1. Set Fixed Frame `root`.
2. Add a MarkerArray on `/workcell_markers` with Durability **Transient Local**.
3. Add TF for frames.

**Gazebo (simulated world):**

```bash
mkdir -p /tmp/service_volumes/intrinsic
sudo cp -r /proc/$(pgrep asset_sim)/root/mnt/gzserver-meshes/ /tmp/service_volumes/intrinsic/
sudo ln -s /tmp/service_volumes/intrinsic/gzserver-meshes /mnt/
GZ_PARTITION=intrinsic_sim gz sim -g
```

Only run the copy step if the directory is missing. The symlink is a mesh workaround. After a scene or robot change, restart the GUI.

**RViz troubleshooting (verified 2026-10-23, `ros:lyrical-ros-base` container with `--net=host`):**

| Symptom | Cause | Fix / test |
|---|---|---|
| `failed to load shared library 'librmw_zenoh_cpp.so' ... libzenohc.so: cannot open shared object file` | The shell sourced ROS **before** `ros-lyrical-rmw-zenoh-cpp` was installed. `libzenohc.so` lives in `/opt/ros/lyrical/opt/zenoh_cpp_vendor/lib`, which only gets onto `LD_LIBRARY_PATH` through that package's env hook (the library has no RUNPATH). | `source /opt/ros/lyrical/setup.bash` again, or open a new shell. Test: `echo $LD_LIBRARY_PATH \| tr : '\n' \| grep zenoh_cpp_vendor` and `ldd /opt/ros/lyrical/lib/librmw_zenoh_cpp.so \| grep zenohc`. |
| `ros2 topic list --no-daemon` shows only `/flowstate_ros_bridge/transition_event`, `/parameter_events`, `/rosout`; RViz reports `Frame [root] does not exist` | The `rs-flowstate-ros-bridge-0` pod started while the executive was unreachable, so its lifecycle stays `unconfigured` (log: `No transition matching 3 found for current state unconfigured`). A redeploy does **not** restart it, because the imported bundle is unchanged. | `kubectl -n app-resources delete pod rs-flowstate-ros-bridge-0`. Test: `/tf` and `/workcell_markers` appear in `ros2 topic list --no-daemon`, and `ros2 topic echo --no-daemon --once --qos-durability transient_local --qos-reliability reliable /workcell_markers` prints markers. |
| `ros2 topic list` hangs or shows nothing | Zenoh endpoint unreachable, or `RMW_IMPLEMENTATION` not exported. | `timeout 2 bash -c '</dev/tcp/127.0.0.1/17447' && echo open`. The container needs `--net=host`, or use the host IP. |
| `Authorization required, but no authorization protocol specified` / `could not connect to display :1`, followed by a misleading `xcb-cursor0 ... is needed` hint | The host Xorg (`-auth /run/user/1000/gdm/Xauthority`, access list `SI:localuser:berti` only) rejects the container's root user. `libxcb-cursor0` *is* installed; Qt prints that hint whenever xcb fails to start. | Either on the host run `xhost +si:localuser:root` (revoke with `xhost -si:localuser:root`), or run the container with `-v $XAUTHORITY:/root/.Xauthority:ro -e XAUTHORITY=/root/.Xauthority`. Host `~/.Xauthority` is an **empty directory** created by an old docker bind mount, so don't mount it. Test from the host without opening a window: `docker exec <ctr> python3 -c 'import ctypes;x=ctypes.CDLL("libX11.so.6");x.XOpenDisplay.restype=ctypes.c_void_p;print(bool(x.XOpenDisplay(b":1")))'` should print `True`. |
| RViz slow, or software rendering despite `--gpus all` | `NVIDIA_DRIVER_CAPABILITIES` is empty, so the NVIDIA OpenGL libraries aren't injected and Mesa llvmpipe is used. | Add `-e NVIDIA_DRIVER_CAPABILITIES=all`. Test: `ls /usr/lib/x86_64-linux-gnu/libGLX_nvidia.so.0` inside the container. |
| Packages gone after the container exits | `docker run --rm` discards `apt install`s. | Bake `ros-lyrical-rviz2 ros-lyrical-rmw-zenoh-cpp` plus the Zenoh `ENV`s into a 4-line Dockerfile `FROM ros:lyrical-ros-base`. |

## Kubernetes (k9s / kubectl)

| Namespace | Contents | Typical action |
|---|---|---|
| `app-intrinsic-base` | Runtime: artifacts, world, executive, ... | `k9s -n app-intrinsic-base -c pods`. Delete `artifacts-deployment-*` on containerd.sock errors. |
| `app-resources` | Solution services: `rs-icon-0`, `rs-gazebo-simulator-0`, `rs-flowstate-ros-bridge`, the pose-estimator service, ... | Press `l` for logs and Ctrl+D to restart a pod. Delete `rs-flowstate-ros-bridge` if RViz shows no TF or meshes. |
| `skills` | Skill servers (as k8s services) | `k9s -n skills -c services` |

The core tutorial's `kubectl -n app-resources delete pod rs-inference-service-0` (pose-estimator load race) applies to the pre-#161 pipeline. Current OMTS has no `inference_service`, so restart the `nvidia_pose_estimator_service` pod instead; find its name in k9s.

Reset the whole cluster (IP changed, CAS unreachable): `sudo /usr/local/bin/k3s-uninstall.sh && sudo rm -rf /var/lib/rancher /etc/rancher/ /var/lib/longhorn/ /etc/cni/`, then redo setup.

## Bzlmod workspace without installed inctl (robot_bringup)

- The tutorial's `env.sh` defines `inctl()` as `bazel run @intrinsic-core//intrinsic/tools/inctl:inctl_external -- "$@"`. **That label is wrong**, because `intrinsic/tools/inctl` has no BUILD file (at 20261012.0 or at the pin). Use `bazel run @intrinsic-core//intrinsic_sdk/intrinsic/tools/inctl:inctl_external -- "$@"`.
- `bazel fetch @intrinsic-core//...` fetches the dependency.
- The same tutorials load `intrinsic_asset_instance` from `@intrinsic-core//intrinsic/assets/build_defs:asset.bzl`. That works at 20261012.0 but is deleted at c40e02a. Use `@intrinsic-core//intrinsic_sdk/intrinsic/assets/build_defs:asset.bzl`.

## Formatting and lint

- **OMTS:** `./tools/format.sh` runs buildifier + ruff. `./tools/lint.sh` runs the CI checks.
- **Core style:**
  - `buildifier -lint=fix <BUILD>`
  - `clang-format -i` for C++/proto
  - `pyink --line-length=80 --indent-spaces=2` plus `isort --profile=google` for Python
