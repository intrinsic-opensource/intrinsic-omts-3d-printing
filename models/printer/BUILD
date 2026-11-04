load("@bazel_skylib//rules:common_settings.bzl", "string_flag")
load("@intrinsic-core//intrinsic/scene/build_defs:sdf_scene_object.bzl", "sdf_scene_object")
load("@intrinsic-core//intrinsic_sdk/intrinsic/assets/scene_objects/build_defs:scene_object.bzl", "intrinsic_scene_object")

package(default_visibility = ["//visibility:public"])

string_flag(name = "door", build_setting_default = "open",
            values = ["closed", "open"])
config_setting(name = "door_closed", flag_values = {":door": "closed"})
config_setting(name = "door_open", flag_values = {":door": "open"})

sdf_scene_object(
    name = "printer_scene_object",
    src = "3d_printer.sdf",
    sdf_assets = [
        "frame.obj",
        "heatbed.obj",
        "door.obj",
    ],
)

intrinsic_scene_object(
    name = "printer",
    manifest = "printer_manifest.textproto",
    scene_object = ":printer_scene_object",
)
