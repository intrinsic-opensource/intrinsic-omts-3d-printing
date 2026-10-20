load("@intrinsic-core//intrinsic/scene/build_defs:sdf_scene_object.bzl", "sdf_scene_object")
load("@intrinsic-core//intrinsic_sdk/intrinsic/assets/scene_objects/build_defs:scene_object.bzl", "intrinsic_scene_object")

package(default_visibility = ["//visibility:public"])

sdf_scene_object(
    name = "rebot_ground_scene_object",
    src = "rebot_ground.sdf",
    sdf_assets = ["ground_visual.glb"],
)

intrinsic_scene_object(
    name = "rebot_ground",
    manifest = "rebot_ground_manifest.textproto",
    scene_object = ":rebot_ground_scene_object",
)
