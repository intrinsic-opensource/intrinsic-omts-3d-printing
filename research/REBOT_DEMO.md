# Running the reBot Demo

How to deploy the reBot printer-tending cell and run its pick-and-place demo
(milestone 1, `HANDOFF.md` section 5). It assumes the OMTS solution already
deploys and runs on this machine: Bazel, Git LFS and the local cluster at
`localhost:17080` work.

The demo runs in simulation only. The reBot starts folded at its `home`
resting pose with the gripper closed, picks a printed part at A, carries it to
B with its gripper, brings it back, then closes the gripper and folds up again.

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
Gazebo rebuilds its world with the gripper device (a deploy alone does not):

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

## 3. Check the arm and gripper (optional)

```bash
bazel run //tools/jogging:move_to_joint -- ready --arm_part_name=rebot
bazel run //tools/jogging:move_to_joint -- home --arm_part_name=rebot
bazel run //tools/gripper:control_gripper -- --gripper_type=pinch --action=open
bazel run //tools/gripper:control_gripper -- --gripper_type=pinch --action=close
```

## 4. Run the demo

```bash
bazel run //:rebot_demo -- --address=localhost:17080 --num_cycles=2
```

Each run first resets the belief and simulated worlds to the deployed initial
world: arm folded at `home`, part at A. Pass `--from_initial_world=false` to
start from wherever the last run left them. Each cycle moves the part A→B→A
and takes about 30 s; a finite run ends by closing the gripper and folding
back to `home`.
`--num_cycles=0` repeats until stopped. The command prints
`Execution successful` when done.
To change the arm speed, edit the application limits in
`models/rebot_b601_rs/rebot_b601_rs_limits.updates.pbtxt` and redeploy; the
gripper's pause after each grasp and release is `PinchGripper`'s
`settle_seconds`.

## 5. Watch it

* **Gazebo viewer:** shows the physics simulation, where the gripper carries
  the part. Reload the viewer after each deploy or reset; a connected viewer
  can show stale objects.
* **RViz:** shows the belief world (what the planner sees). Restart the ROS
  bridge after a deploy so it fetches the new meshes, then open the cell's
  config as a Zenoh client of the local cluster:

  ```bash
  kubectl -n app-resources delete pod rs-flowstate-ros-bridge-0
  export RMW_IMPLEMENTATION=rmw_zenoh_cpp
  export ZENOH_CONFIG_OVERRIDE='mode="client";connect/endpoints=["tcp/127.0.0.1:7447"]'
  ros2 run rviz2 rviz2 -d configs/rebot/rebot.rviz
  ```

## 6. Go back to OMTS

```bash
bazel run -c opt //:omts_solution -- --address=localhost:17080
```

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| First move fails with `move_robot` "connection refused" | The arm is not enabled yet; wait for "[rebot] Now enabled" (step 2). |
| Gripper command succeeds but the fingers don't move in Gazebo | Gazebo still has the old world; run the reset in step 2. |
| RViz shows TF but no meshes, or misses the ground or part | Restart the bridge pod (step 5) and relaunch RViz. |
| A run failed midway and the arm or part is in the wrong place | Run the demo again; it resets to the initial world first. |
