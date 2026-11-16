# Feature Request: Keep only the top N SAM 3 proposals, sorted by score

**Component:** NVIDIA pose estimator service
(`nvidia_pose_estimator_service`; SAM 3 post-processing in
`foundationpose_perception_pipeline`, `inference/sam3/trt_processor.py`, and
`Sam3DetectionConfig` in `nvidia_service_config.proto`)

## Summary

The pose estimator runs FoundationPose on every SAM 3 proposal above a fixed
confidence threshold, with no limit on their number and in the decoder's
order rather than by score. A cap on the number of proposals, keeping the
best-scoring ones, would bound the cost of an estimate in any scene and
remove the need to tune the threshold for each part.

## Current behavior

* SAM 3's mask decoder always returns 200 candidate regions. `_postprocess`
  keeps those whose score (region score times presence) exceeds
  `confidence_threshold` and returns them in query order, unsorted.
* Every surviving region goes to FoundationPose; nothing caps their number.
  Each costs a pose search, about 2.6 s on an RTX 4090 Laptop GPU (16 GB),
  plus a second search when SAM 3 refinement replaces its mask.
* The only control is the threshold, in the service config or the
  estimator's registration. It is an absolute score, so it has to be chosen
  per part and per prompt.

## Observed impact

OMTS printer tending (a reBot arm picking printed parts off a 3D printer's
bed, in simulation) needs one registration that works for any printed part,
so it uses a generic prompt and lets FoundationPose's fit choose the part.
That works, but the threshold cannot be set once:

* With the prompt "object", the part was always the top-scoring region, but
  its score depended on the shape: 0.20 for a plain 80 × 20 × 40 mm cuboid,
  0.31 for a 40 mm box, 0.57 to 0.69 for a 3DBenchy. Keeping every part
  needed a threshold under 0.2, which passed 3 to 7 regions in a simple
  scene (8 to 18 s per estimate). At 0.5, only the Benchy was found.
* Finding a better prompt took a sweep of 50 phrases offline. "object on a
  table" at 0.35 passes 1 to 3 regions in the same scenes with every part
  still first, but the cuboid clears that threshold by only 0.1, and the
  margin will differ for other parts and real cameras.
* A scene with many similar objects can pass far more. With a grid of 100
  small cubes in view and the prompt "cube", 175 of the 200 regions passed
  0.1: minutes of pose searches for one estimate, with GPU memory already
  near its 16 GB limit (15.3 GB peak).

In every case the part was ranked first or second by score. A top-N cut
would have kept it with any reasonable threshold.

## Suggested fix

1. **Sort the surviving proposals by score**, descending, in
   `_postprocess`.
2. **Add `max_proposals` to `Sam3DetectionConfig`** (and the per-request
   detection overrides), keeping only the first N after sorting. Unset keeps
   today's behavior.
3. Optionally, a relative cut (keep proposals scoring at least a fraction
   of the best one), so that a weak scene does not pass N poor regions.

With these, a registration can use a low threshold and a small N, say 5,
and the cost of an estimate is bounded by N pose searches whatever the
scene.

## Benefit

Predictable estimate times and GPU use in cluttered scenes, and generic,
threshold-free registrations that work across parts. Users no longer need
to search for a prompt and threshold per part, which today needs tooling
outside the service (we compared prompts offline by running the SAM 3
export with onnxruntime).
