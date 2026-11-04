# Feature Request: Gazebo viewer should follow simulation resets and redeploys

**Component:** Intrinsic Gazebo simulator
(`intrinsic/simulation/gazebo/server_main_impl.cc` in intrinsic-core)

## Summary

A Gazebo GUI connected to Intrinsic's simulator (`gz sim -g` on the
simulator's transport partition) shows a stale or broken scene after every
simulation reset or redeploy, until the GUI is restarted. Signalling the
rebuild to connected viewers, or supporting a viewer that reconnects, would
remove that manual step.

## Current behavior

* On a simulation reset (`solution.simulator.reset()`, or a run with
  `start_from_world_state`), the simulator rebuilds its world: it generates a
  new SDF and builds a new `gz::sim::Server` (`GazeboRunner`), with the same
  world name (`default`) and transport topics. Deploys that restart the
  simulator have the same effect.
* A GUI that was already connected keeps the scene it built from the previous
  server. Nothing tells it the world was replaced, so it can show the old
  entities, a mix of old and new, or links at wrong poses.
* Mesh files are not the cause: the shared mesh directory uses content-hashed
  file names, so changed meshes get new paths.

## Observed impact

In a simulation cell under active development (OMTS printer tending, reBot
arm), the GUI had to be reloaded after every deploy and reset. For example,
after a redeploy and reset the arm's links were drawn scattered and a nested
gripper was drawn at the world origin, while the simulator itself had them
assembled and mounted correctly (checked with
`/world/default/generate_world_sdf` and `/world/default/pose/info`).

## Suggested fix

Either of these would work:

1. **Signal the rebuild to connected viewers.** Before replacing the server,
   publish a scene deletion for all entities of the old world; after it
   starts, publish the full scene so viewers rebuild from it. The standard GUI
   already handles `/world/<name>/scene/deletion` and
   `/world/<name>/scene/info`.
2. **Supported viewer that reconnects.** Ship a viewer launch or GUI plugin
   that detects a new simulator session (for example from the world-sync
   session start or a generation counter on a status topic) and reloads its
   scene.

Documenting the supported way to attach a Gazebo GUI to the simulator (topics,
partition, network address, mesh path) would also help; today it has to be
worked out from logs.

## Benefit

Shorter iteration loops. Each deploy or reset currently costs a GUI restart,
and the risk of chasing rendering artifacts that look like model or
kinematics bugs. With the fix, the viewer can stay open while a developer
edits, deploys, resets and runs.
