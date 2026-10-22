# Feature Request: flowstate_ros_bridge should keep RViz in sync with the world

**Component:** `flowstate_ros_bridge`
([intrinsic-ai/sdk-ros](https://github.com/intrinsic-ai/sdk-ros),
`flowstate_ros_bridge/src/bridges/world_bridge.cpp`)

## Summary

The bridge's `/workcell_markers` topic stops matching the belief world after
common development actions, so RViz shows missing or stale objects until the
bridge pod is restarted by hand. Publishing the full scene on every change,
and noticing geometry changes as well as new objects, would remove that manual
step.

## Current behavior

* **Only new objects are published after start-up.** The bridge sends markers
  for all objects when it starts. Later, it detects new objects from new TF
  frame names and publishes a marker array for only those objects. The topic
  is `KeepLast(1)` with transient-local durability, so it then holds just the
  newest objects. An RViz opened afterwards receives only those.
* **Changed geometry is never re-sent.** Re-sending is triggered only by new
  TF frame names. If an existing object's mesh changes (same object, new
  geometry), the bridge keeps publishing the old mesh. Meshes are cached by
  their content-addressed geometry refs, so a re-send would fetch the new one;
  nothing triggers it.

## Observed impact

In a simulation cell under active development (OMTS printer tending, reBot
arm), every scene change needed `kubectl -n app-resources delete pod
rs-flowstate-ros-bridge-0` before RViz could be trusted:

* After a static wall was added, RViz showed the wall but not the robot, which
  looked like a deployment fault until traced to the marker topic.
* After a model was resized and redeployed, RViz kept the old mesh.

## Suggested fix

1. **Publish the complete scene on every change.** Whenever any object is
   added, removed or changed, publish one `MarkerArray` with markers for all
   current objects (with `DELETEALL` first, or stable namespaces and IDs).
   With `KeepLast(1)` transient-local durability, late subscribers then always
   receive the full scene.
2. **Detect geometry changes, not just new frames.** Compare each object's
   geometry refs (`exact_geometry_ref`, `renderable_ref`) with the last
   published ones, or subscribe to the world's update stream, and re-send
   objects whose geometry changed.

## Benefit

Shorter iteration loops. Each scene or model change currently costs a bridge
pod restart (about 40 s until it has re-fetched every mesh), an RViz relaunch,
and the risk of debugging a stale view as if it were a real fault. With the
fix, a redeploy is enough, and RViz can stay open across the edit, deploy and
run cycle.
