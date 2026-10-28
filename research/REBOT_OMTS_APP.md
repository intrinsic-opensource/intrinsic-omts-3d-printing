# Running OMTS on the reBot

How to deploy the reBot printer-tending cell and run OMTS's own app
(`omts_app`) on it, with the wrist camera locating the part (milestone 2,
`HANDOFF.md` section 5b). It assumes the OMTS solution already deploys and
runs on this machine: Bazel, Git LFS and the local cluster at
`localhost:17080` work.

The cell is a Seeed reBot Arm B601-RS with its pinch gripper and an Orbbec
Gemini 335Le under its wrist, a stand-in 3D printer in front of it
(`models/printer`; the target printer is undecided), and a printed part. The
goal is OMTS's lab-cell flow with no machine: the arm looks at the
printer bed from a `view` pose, the pose estimator finds the printed part, and
the arm picks it and sets it back down at a random offset, so the next cycle
has to find it again. Simulation only.

**Status.** This is built one step at a time; sections marked *Not yet* are the
plan, not working commands.

| Step | What works | Section |
| --- | --- | --- |
| 3a | Camera on the wrist; `capture_images` returns RGB and depth at `view` | 3 |
| 3b | Pose estimator registered for the part | 4, *not yet* |
| 3c | `omts_app` picks the part from perception | 5, *not yet* |
| 3d | Camera-to-robot calibration in sim (optional) | *not yet* |

## 1. Get the code

```bash
git checkout research
git lfs pull   # the reBot meshes are LFS files
```

## 2. Deploy

```bash
bazel run -c opt //:rebot_solution -- --address=localhost:17080
```

This replaces whatever solution is deployed. Then reset the simulation, so
Gazebo rebuilds its world with the gripper and camera (a deploy alone does
not):

```bash
bazel run //tools/world:apply_scene_updates -- \
  --address=localhost:17080 --files --reset_sim
```

Wait until the arm is enabled (a few seconds) before moving it. This prints a
line once ICON has enabled the arm; rerun it until it does:

```bash
kubectl -n app-resources logs --since=2m rs-gazebo-simulator-0 | grep "\[rebot\] Now enabled"
```

Redeploying the same solution restarts nothing, so the arm stays enabled and
no new line appears; drop `--since=2m` to see the earlier one.

The camera runs as two pods, `rs-orbbec-camera-0` and
`rs-orbbec-gemini-driver-0`:

```bash
kubectl get pods -n app-resources | grep orbbec
```

## 3. Look through the camera (step 3a)

Move the arm to `view`:

```bash
bazel run //tools/jogging:move_to_frame -- --frame=view --arm_part_name=rebot
```

The camera, which hangs below the gripper, then sees the whole bed from just
outside the printer's front, about 0.30 m from the bed centre. After a reset the part is on the ground behind the
robot, not on the bed. To have something to look at, put it in the middle of
the bed in both worlds, then move to `view` again:

```bash
cat > /tmp/part_on_bed.updates.pbtxt <<'EOF'
updates {
  update_transform {
    node_a { by_name { object { object_name: "root" } } }
    node_b { by_name { object { object_name: "rebot_printed_part" } } }
    node_to_update { by_name { object { object_name: "rebot_printed_part" } } }
    a_t_b { position { x: 0.36 y: 0 z: 0.1045 } orientation { w: 1 } }
  }
}
EOF
bazel run //tools/world:apply_scene_updates -- --address=localhost:17080 \
  --files /tmp/part_on_bed.updates.pbtxt $PWD/configs/rebot/scene.updates.pbtxt \
  --reset_sim
```

The reset also returns the arm to `park_left`, its folded resting pose.

To see an image:

1. Open the Gazebo GUI against the cluster's simulation:

   ```bash
   export GZ_PARTITION=intrinsic_sim GZ_IP=10.42.0.1 \
     GZ_RELAY=$(kubectl get pod -n app-resources rs-gazebo-simulator-0 -o jsonpath='{.status.podIP}')
   gz sim -g
   ```

2. Add an **Image Display** (plugins menu, top right) and pick the topic
   `/orbbec_camera/rgb` (or `/orbbec_camera/depth/image`).
3. Trigger a capture. The simulated camera publishes only when something
   captures, which is what `capture_images` does. OMTS has no command-line
   capture tool yet, so for now run the skill from a short script in the
   environment of a built OMTS tool:

   ```bash
   bazel build //tools/jogging:move_to_frame
   R=$PWD/bazel-bin/tools/jogging/move_to_frame.runfiles
   RUNFILES_DIR=$R $R/_main/tools/jogging/_move_to_frame.venv/bin/python3 -c '
   from intrinsic.solutions import deployments
   s = deployments.connect(address="localhost:17080")
   s.executive.run(s.skills.ai.intrinsic.capture_images(
       camera=s.resources["orbbec_camera"], sensor_ids=[1, 4]))'
   ```

   It prints `Execution successful`, and the image display updates.

What to expect in the image:

* The bed fills the middle, seen at a low angle, with the printer's posts at
  the sides.
* About the near half of the bed (bottom of the image) has no depth: it is
  closer than the depth sensor's 0.25 m minimum. The middle and far half have
  depth.
* The gripper is out of view.

## 4. Register the pose estimator (step 3b, *not yet*)

Planned: add `nvidia_pose_estimator_service` and `ioc_train_service` to
`rebot_solution`, then register an estimator for the printed part with
Intrinsic Core's tool, as the OMTS README (section 4.3) does for the raw stock:

```bash
# Not yet: the services are not in rebot_solution.
bazel run @intrinsic-core//intrinsic_perception/intrinsic/perception/service/ioc_train_service/tools:register_using_ioc_train_service -- \
  --address="localhost:17080" \
  --scene_object_id="ai.intrinsic.rebot_printed_part" \
  --pose_estimator_id="ai.intrinsic.rebot_printed_part_estimator_text" \
  --text_prompt="cube"
```

and check it from `view` with `run_pose_estimation` (OMTS README 4.3).

## 5. Run `omts_app` (step 3c, *not yet*)

Planned: a cell config `configs/rebot/app_config.yaml` (no machine, pinch
gripper, perception infeed, `cuboid_center` grasp planner), run like the other
cells:

```bash
# Not yet: configs/rebot/app_config.yaml does not exist.
bazel run //src:omts_app -- --address=localhost:17080 \
  --config=configs/rebot/app_config.yaml --num_cycles=3
```

Two OMTS behaviours stand in the way (`HANDOFF.md` step 3c): its pick and
return end in a force-controlled touchdown, which the reBot cannot do, and
`cuboid_center` only grasps straight down, which the reBot cannot reach inside
the printer.

## 6. Go back to OMTS

```bash
bazel run -c opt //:omts_solution -- --address=localhost:17080
```

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `move_to_frame` reports "IK solver couldn't find any solutions" for a frame you edited | The planner gives the same error for an unreachable pose and for one where the arm or camera would collide, for example the camera against a printer post. Move the frame or check clearances. |
| The image display stays empty | Nothing has captured yet; trigger a capture (step 3). Check the GUI is on the cluster's partition (`GZ_PARTITION=intrinsic_sim`). |
| First move fails with `move_robot` "connection refused" | The arm is not enabled yet; wait for "[rebot] Now enabled" (step 2). |
| Gazebo shows no camera, or the gripper doesn't move | Gazebo still has the old world; run the reset in step 2. |
