# Seeed reBot Arm B601-RS (`ai.intrinsic.rebot_b601_rs`)

Simulation-only ICON hardware device for the Seeed Studio reBot Arm B601-RS:
6 revolute joints, without the gripper, which is the separate hardware device
[`//models/rebot_b601_rs_gripper`](../rebot_b601_rs_gripper/). Used by
`//:rebot_solution`.

In sim, Gazebo runs the hardware module itself and infers its interfaces
(`joint_position_command`, `joint_position_state`, `joint_velocity_state`,
`payload_*`, `safety_status`) from the arm's six joints. The device ships only
Intrinsic's Gazebo stub image, made visible by
`//bazel/patches:gazebo_hwm_stub_visibility.patch`, for both sim and real
mode. Real hardware support comes from Intrinsic.

## Files

| File | Origin |
| --- | --- |
| `rebot_b601_rs.sdf`, `*.glb` | Generated (see below). The arm carries `intrinsic:ik_solver` (`kinematic_chain`) and a `flange` attachment frame at `link6`. |
| `rebot_b601_rs_limits.updates.pbtxt` | Hand-written. Initial joint positions (folded `home`, the reBot's resting pose) and joint limits. Positions come from the URDF; velocity, acceleration and jerk are simulation placeholders, not measured on the arm. The application limits the planner uses are kept slow (0.5–0.75 rad/s, 3 rad/s²) so the demo is easy to follow. |
| `rebot_b601_rs.named_configurations.pbtxt` | Hand-written. `home` (folded), `park_left` (`home` turned 90° to the left, for cells with something in front of the robot) and `ready` (tool pointing straight down, 0.30 m in front of the base, 0.10 m up). |
| `rebot_b601_rs_*manifest.textproto`, `rebot_b601_rs_default_config.pbtxt`, `BUILD` | Hardware device, scene object and service packaging. |
| `mesh_colors.json` | Color rules for the generator, shared with the gripper. |

## Source

Generated from Seeed's
[reBot-Isaacsim](https://github.com/Seeed-Projects/reBot-Isaacsim) RS URDF,
`urdf/00-arm-rs_asm-v3/` at commit `158f87317fcaa35a7d1706ef364e324d3565939e`
(2026-09-22), licensed MIT (see [`LICENSE.reBot-Isaacsim`](LICENSE.reBot-Isaacsim)).
That URDF corrects the finger travel of Seeed's other RS URDFs (both fingers
0–0.05 m); `research/HANDOFF.md` §6.2 has the details.

## Regenerating

```bash
git clone --depth 1 https://github.com/Seeed-Projects/reBot-Isaacsim.git /tmp/reBot-Isaacsim
git -C /tmp/reBot-Isaacsim checkout 158f87317fcaa35a7d1706ef364e324d3565939e
M=/tmp/reBot-Isaacsim/urdf/00-arm-rs_asm-v3
COMMON="--urdf=$M/urdf/00-arm-rs_asm-v3.urdf --mesh_dir=$M/meshes \
  --colors=models/rebot_b601_rs/mesh_colors.json \
  --visual_cell_size=0.002 --collision_cell_size=0.008"

# Arm: everything except the gripper subtree.
bazel run //tools/models:urdf_to_sdf -- $COMMON \
  --out_dir=models/rebot_b601_rs --model_name=rebot_b601_rs \
  --exclude_links=gripper_end --ik_solver=kinematic_chain --flange_link=link6

# Gripper: the subtree from gripper_end.
bazel run //tools/models:urdf_to_sdf -- $COMMON \
  --out_dir=models/rebot_b601_rs_gripper --model_name=rebot_b601_rs_gripper \
  --root_link=gripper_end
```

The gripper is mounted on the flange by `configs/rebot/rebot.attachments.updates.pbtxt`,
with the URDF's `j_gripper_end` transform, which also adds `tool_frame` at the
fingertips.

The gripper is a simulation-only hardware device: its scene object plus
Intrinsic's pinch gripper realtime control service, commanded by
`ai.intrinsic.control_pinch_gripper`. Its instance config,
[`configs/rebot/gripper.instance.pbtxt`](../../configs/rebot/gripper.instance.pbtxt),
names the grasp/release signals. In sim, the service drives Gazebo's simulated
GPIO directly (no ICON digital I/O), and Gazebo's actuated gripper plugin moves
both fingers and holds a grasped object with a fixed joint. Finger joint 0 is
closed and 0.05 m is open, so the config sets `is_default_closed`.

## Current limitations

* **Joint limits beyond position are placeholders.** Revisit them against the
  real arm once Intrinsic's hardware support lands.
* **The gripper's command path is a simulation choice.** Real hardware will
  depend on how Intrinsic exposes the gripper motor (HANDOFF question 4.1.5);
  the signal names in the instance config are placeholders until then.
* **Collision meshes are coarse simplifications** (8 mm vertex clustering),
  not conservative hulls. Revisit before relying on motion planning near
  obstacles.
* **Joint sign convention** follows the reBot-Isaacsim URDF (`joint2`,
  `joint3` from −3.14 to 0), which differs from Seeed's other RS URDFs.
  Confirm against Intrinsic's hardware support when it lands.
