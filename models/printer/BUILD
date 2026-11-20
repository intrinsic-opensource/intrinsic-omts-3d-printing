load("@bazel_skylib//rules:common_settings.bzl", "string_flag")
load("@intrinsic-core//intrinsic/scene/build_defs:sdf_scene_object.bzl", "sdf_scene_object")
load("@intrinsic-core//intrinsic_sdk/intrinsic/assets/scene_objects/build_defs:scene_object.bzl", "intrinsic_scene_object")

package(default_visibility = ["//visibility:public"])

exports_files(["3d_printer.sdf"])

# layout=default: the printer where the committed cell has it. layout=door_test:
# printer at d 0.70, shifted 0.3 m left, for the door tests (the deploy then
# starts with the printer in place, so nothing has to be teleported later).
string_flag(
    name = "layout",
    build_setting_default = "default",
    values = [
        "default",
        "door_test",
    ],
)

config_setting(
    name = "layout_door_test",
    flag_values = {":layout": "door_test"},
)

string_flag(
    name = "door",
    build_setting_default = "open",
    values = [
        "closed",
        "open",
    ],
)

config_setting(
    name = "door_closed",
    flag_values = {":door": "closed"},
)

config_setting(
    name = "door_open",
    flag_values = {":door": "open"},
)

# hinge=held (default): Gazebo's position controller holds the door joint at
# the angle the belief world gives it. hinge=passive: a Gazebo
# JointStatePublisher plugin in the model replaces the default controller
# (core world_object_plugin.cc), so the door turns freely under contact; belief
# joint writes then no longer move it in Gazebo.
string_flag(
    name = "hinge",
    build_setting_default = "held",
    values = [
        "held",
        "passive",
    ],
)

config_setting(
    name = "hinge_passive",
    flag_values = {":hinge": "passive"},
)

genrule(
    name = "printer_passive_sdf",
    srcs = ["3d_printer.sdf"],
    outs = ["3d_printer_passive.sdf"],
    cmd = "sed 's|</model>|<plugin filename=\"gz-sim-joint-state-publisher-system\" name=\"gz::sim::systems::JointStatePublisher\"><joint_name>door_hinge</joint_name></plugin></model>|' $< > $@",
)

sdf_scene_object(
    name = "printer_scene_object",
    src = select({
        ":hinge_passive": ":3d_printer_passive.sdf",
        "//conditions:default": "3d_printer.sdf",
    }),
    sdf_assets = [
        "frame.obj",
        "heatbed.obj",
        "door.obj",
        "aruco_1.glb",
    ],
)

intrinsic_scene_object(
    name = "printer",
    manifest = "printer_manifest.textproto",
    scene_object = ":printer_scene_object",
)
