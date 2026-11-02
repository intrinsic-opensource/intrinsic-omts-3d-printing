# Running OMTS on the reBot

How to deploy the reBot printer-tending cell and run OMTS's own app
(`omts_app`) on it, with the wrist camera locating the part (milestone 2,
`HANDOFF.md` section 5b). It assumes the OMTS solution already deploys and
runs on this machine: Bazel and the local cluster at `localhost:17080` work.

The cell is a Seeed reBot Arm B601-RS with its pinch gripper and an Orbbec
Gemini 335Le under its wrist, a stand-in 3D printer in front of it
(`models/printer`; the target printer is undecided), and a printed part.
Each cycle, the arm looks at the printer's bed from a `view` pose, the pose
estimator finds the part, and the arm picks it, sets it down at A on the
ground behind the robot, picks it up again and puts it back on the bed at a
random offset, so the next cycle has to find it again. Simulation only.

**Before you start:**

* **GPU memory.** The pose estimator needs at least 16 GB of dedicated GPU
  memory: it peaks at about 15.3 GB with the reBot's config, which lowers the
  FoundationPose batch, and with nothing else on the GPU. Intrinsic's default
  config runs out of memory on 16 GB. 24 GB leaves room for the default config
  and other GPU programs; on a Jetson, whose memory is shared with the system,
  plan for 32 GB or more. Measured on one RTX 4090 Laptop GPU with one part
  registered (`HANDOFF.md` step 3b).
* **SAM 3 access.** The pose estimator segments with Meta's SAM 3, which is
  gated: request access to [facebook/sam3](https://huggingface.co/facebook/sam3)
  on HuggingFace and accept the license. Approval is manual and can take a
  while.

## Quick start

### 1. Get the code

The reBot cell is on the `added-rebot-solution` branch of
[intrinsic-opensource/intrinsic-omts-3d-printing](https://github.com/intrinsic-opensource/intrinsic-omts-3d-printing):

```bash
git remote add opensource https://github.com/intrinsic-opensource/intrinsic-omts-3d-printing.git
git fetch opensource
git switch -c added-rebot-solution --track opensource/added-rebot-solution
```

### 2. Export the SAM 3 model (once per machine)

1. Log in to HuggingFace on this machine:

   ```bash
   python3 -m pip install --user --break-system-packages -U huggingface_hub
   ~/.local/bin/hf auth login   # paste a Read token
   ```

2. Export the model with Intrinsic Core's script, at the commit OMTS pins (see
   `HANDOFF.md` section 2 for the checkout). Its pinned dependencies need
   Python 3.12 or older; on a newer system Python, give it a 3.12 environment
   first (Bazel's copy works once OMTS has been built; run `bazel info` from
   the OMTS checkout):

   ```bash
   PY312=$(ls -d $(bazel info output_base)/external/rules_python++python+python_3_12_x86_64-unknown-linux-gnu)/bin/python3
   $PY312 -m venv ~/intrinsic-models/sam3_export_venv
   cd ~/intrinsic-core
   ./intrinsic_perception/intrinsic/perception/service/nvidia_pose_estimator/scripts/prepare_sam3_models.sh \
     --output-dir ~/intrinsic-models/nvidia_pose_estimator \
     --venv-dir ~/intrinsic-models/sam3_export_venv
   ```

   This downloads the checkpoint and writes four ONNX files and a vocabulary
   (3.3 GB) to `~/intrinsic-models/nvidia_pose_estimator`.

### 3. Deploy

Deploy the solution with the pose estimator's models, then reset the
simulation so Gazebo rebuilds its world with the gripper and camera (a deploy
alone does not):

```bash
bazel run -c opt --//:perception_models \
  --repo_env=NVIDIA_POSE_ESTIMATOR_MODELS_DIR=$HOME/intrinsic-models/nvidia_pose_estimator \
  //:rebot_solution -- --address=localhost:17080
bazel run //tools/world:apply_scene_updates -- \
  --address=localhost:17080 --files --reset_sim
```

This replaces whatever solution is deployed. The first deploy uploads 4 GB of
models. The arm starts folded at `park_left` (its resting pose, turned to the
left, away from the printer) and the part in the middle of the printer's bed.

Wait for two things before going on; rerun each command until it prints a
line:

```bash
# The arm is enabled (a few seconds after the reset)
kubectl -n app-resources logs --since=2m rs-gazebo-simulator-0 | grep "\[rebot\] Now enabled"
# The pose estimator has loaded its models onto the GPU
# (several minutes the first time, under a minute later)
kubectl -n app-resources logs rs-nvidia-pose-estimator-service-0 | grep "Server listening"
```

Redeploying the same solution restarts nothing, so the arm stays enabled and
no new line appears; drop `--since=2m` to see the earlier one.

### 4. Register the part (after every deploy)

The registration tells the pose estimator which object to look for: the
part's model and a text prompt. It is stored on the cluster as an asset,
which a deploy removes, so register again after each deploy (about a minute):

```bash
bazel run -c opt \
  --repo_env=NVIDIA_POSE_ESTIMATOR_MODELS_DIR=$HOME/intrinsic-models/nvidia_pose_estimator \
  @intrinsic-core//intrinsic_perception/intrinsic/perception/service/ioc_train_service/tools:register_using_ioc_train_service -- \
  --address="localhost:17080" \
  --scene_object_id="ai.intrinsic.rebot_printed_part" \
  --pose_estimator_id="ai.intrinsic.rebot_printed_part_estimator" \
  --refinement_iters=5 --confidence_threshold=0.5 --visibility_threshold=0.15 \
  --text_prompt="cube"
```

It ends with `Complete! Pose estimator ai.intrinsic.rebot_printed_part_estimator saved.`

The threshold is 0.5, not the 0.15 OMTS uses for the raw stock: at 0.15,
weak false positives such as the printer's toolhead come back too, and the
app uses the first estimate it gets. SAM 3 scores the part about 0.58 from
`view`. The service caches each estimator's threshold until it restarts, so
to change it, register under a new id.

### 5. Run `omts_app`

```bash
bazel run //src:omts_app -- --address=localhost:17080 \
  --config=configs/rebot/app_config.yaml --num_cycles=3
```

It prints `Execution successful`; a cycle takes about 50 s. `--num_cycles=0`
repeats until stopped. Each cycle:

1. moves to `view`, finds the part on the bed and picks it with a grasp
   tilted 60° (the reBot cannot reach straight down into the printer);
2. sets it down at A on the ground behind the robot and picks it up again
   (OMTS's load and unload steps, at A instead of a machine);
3. puts it back on the bed within 4 x 4 cm of the centre, turned up to ±10°,
   so the next cycle has to find it again.

Watch it in the Gazebo GUI (see "Look through the camera" below for how to
open it against the cluster).

Further runs continue from wherever the last one left the part. The app does
not reset the world, though: if a run fails while the part is in the gripper,
the part stays attached to the arm in the planner's world, and the next run
fails with collisions or "could not find a path". Put the part back in the
middle of the bed, which also reattaches it to the world and folds the arm:

```bash
bazel run //tools/world:apply_scene_updates -- --address=localhost:17080 \
  --files $PWD/configs/rebot/printed_part.updates.pbtxt \
  $PWD/configs/rebot/scene.updates.pbtxt --reset_sim
```

## Debugging

Optional checks of the camera and the pose estimator on their own, without
running the app. Both start from a deployed cell with the part on the bed
(quick start step 3; put the part back as in step 5 if a run moved it).

### Look through the camera

Move the arm to `view`:

```bash
bazel run //tools/jogging:move_to_frame -- --frame=view --arm_part_name=rebot
```

The camera, which sits above the gripper, then sees the whole bed from just
outside the printer's front, about 0.38 m from the bed centre.

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

* The bed fills the middle with the part on it, and the printer's posts and
  toolhead around it.
* The whole bed has depth; only nearby parts of the printer, such as its
  display, are closer than the depth sensor's 0.25 m minimum.
* The gripper is out of view.

### Estimate the part's pose

With the arm at `view` and the part registered (quick start step 4):

```bash
bazel run -c opt \
  --repo_env=NVIDIA_POSE_ESTIMATOR_MODELS_DIR=$HOME/intrinsic-models/nvidia_pose_estimator \
  @intrinsic-core//intrinsic_perception/intrinsic/perception/service/ioc_pose_estimator:run_pose_estimation -- \
  --address=localhost:17080 --service_name=nvidia_pose_estimator_service \
  --camera_name=orbbec_camera \
  --pose_estimator_id=ai.intrinsic.rebot_printed_part_estimator
```

It prints detections in the camera frame, best first. With the part in the
middle of the bed, the only one scores about 1.0 and sits about 0.38 m
straight ahead.

## Deploy without perception

Without the SAM 3 export, deploy the plain solution; everything but the pose
estimator works (the service does not start, so `omts_app` cannot find the
part):

```bash
bazel run -c opt //:rebot_solution -- --address=localhost:17080
```

## Go back to OMTS

```bash
bazel run -c opt //:omts_solution -- --address=localhost:17080
```

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| First move fails with `move_robot` "connection refused" | The arm is not enabled yet; wait for "[rebot] Now enabled" (quick start step 3). |
| Gazebo shows no camera, or the gripper doesn't move | Gazebo still has the old world; run the reset in quick start step 3. |
| `rs-nvidia-pose-estimator-service-0` keeps restarting | The models are missing: deploy with `--//:perception_models` and `--repo_env` (quick start step 3). |
| Pose estimation fails because the estimator is not found | A deploy removed the registration; register again (quick start step 4). |
| `omts_app` fails with a collision between `rebot_printed_part` and the printer, or "could not find a path" | A failed run left the part attached to the arm; put it back on the bed (end of quick start step 5). |
| Pose estimation fails with "Failed to create TensorRT execution context" | The GPU ran out of memory. The reBot's service config already uses a smaller FoundationPose batch for a 16 GB GPU; close other GPU programs, or lower `batch_size` further in `configs/rebot/nvidia_pose_estimator_config.textproto`. |
| `move_to_frame` reports "IK solver couldn't find any solutions" for a frame you edited | The planner gives the same error for an unreachable pose and for one where the arm or camera would collide, for example the camera against a printer post. Move the frame or check clearances. |
| The image display stays empty | Nothing has captured yet; trigger a capture ("Look through the camera"). Check the GUI is on the cluster's partition (`GZ_PARTITION=intrinsic_sim`). |
