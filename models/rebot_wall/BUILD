load("@intrinsic-core//intrinsic/scene/build_defs:sdf_scene_object.bzl", "sdf_scene_object")
load("@intrinsic-core//intrinsic_sdk/intrinsic/assets/scene_objects/build_defs:scene_object.bzl", "intrinsic_scene_object")

package(default_visibility = ["//visibility:public"])

sdf_scene_object(
    name = "rebot_wall_scene_object",
    src = "rebot_wall.sdf",
    sdf_assets = ["wall_visual.glb"],
)

intrinsic_scene_object(
    name = "rebot_wall",
    manifest = "rebot_wall_manifest.textproto",
    scene_object = ":rebot_wall_scene_object",
)
