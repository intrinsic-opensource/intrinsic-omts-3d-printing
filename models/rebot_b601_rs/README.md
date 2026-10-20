# Seeed reBot Arm B601-RS (`ai.intrinsic.rebot_b601_rs`)

Scene model of the Seeed Studio reBot Arm B601-RS: 6 revolute joints and a
two-finger rack-and-pinion gripper. Used by `//:rebot_solution`.

## Source

Generated from Seeed's
[reBot-Isaacsim](https://github.com/Seeed-Projects/reBot-Isaacsim) RS URDF,
`urdf/00-arm-rs_asm-v3/` at commit `158f87317fcaa35a7d1706ef364e324d3565939e`
(2026-09-22), licensed MIT (see [`LICENSE.reBot-Isaacsim`](LICENSE.reBot-Isaacsim)).
That URDF corrects the finger travel of Seeed's other RS URDFs (both fingers
0–0.05 m); `research/HANDOFF.md` §6.2 has the details.

## Regenerating

Every file here except this README, `BUILD`, the manifest, the license and
`mesh_colors.json` is generated. To regenerate:

```bash
git clone --depth 1 https://github.com/Seeed-Projects/reBot-Isaacsim.git /tmp/reBot-Isaacsim
git -C /tmp/reBot-Isaacsim checkout 158f87317fcaa35a7d1706ef364e324d3565939e
M=/tmp/reBot-Isaacsim/urdf/00-arm-rs_asm-v3
bazel run //tools/models:urdf_to_sdf -- \
  --urdf=$M/urdf/00-arm-rs_asm-v3.urdf --mesh_dir=$M/meshes \
  --out_dir=models/rebot_b601_rs --model_name=rebot_b601_rs \
  --colors=models/rebot_b601_rs/mesh_colors.json \
  --visual_cell_size=0.002 --collision_cell_size=0.008 --static
```

## Current limitations (milestone 1, step 1a)

* **Static.** The model holds its pose in Gazebo because nothing controls it
  yet. Step 1b removes `--static` and adds the ICON hardware device.
* **No Intrinsic kinematics tags** (`intrinsic:ik_solver`, flange frame).
  Added in step 1b.
* **Fingers are independent joints.** The real gripper moves both fingers 1:1;
  the coupling is added with the gripper in step 1c.
* **Collision meshes are coarse simplifications** (8 mm vertex clustering),
  not conservative hulls. Revisit before relying on motion planning near
  obstacles.
* **Joint sign convention** follows the reBot-Isaacsim URDF (`joint2`,
  `joint3` from −3.14 to 0), which differs from Seeed's other RS URDFs.
  Confirm against Intrinsic's hardware support when it lands.
