load("@intrinsic-core//bazel:python.bzl", "py_binary")

package(default_visibility = ["//visibility:public"])

py_binary(
    name = "pick_and_place",
    srcs = ["pick_and_place.py"],
    data = ["//configs:all_configs"],
    main = "pick_and_place.py",
    deps = [
        "//src/core:config",
        "//src/hardware:gripper",
        "//src/hardware:robot",
        "@intrinsic-core//intrinsic_sdk/intrinsic/math/python:data_types",
        "@intrinsic-core//intrinsic_sdk/intrinsic/solutions:behavior_tree",
        "@intrinsic-core//intrinsic_sdk/intrinsic/solutions:deployments",
        "@intrinsic-core//intrinsic_sdk/intrinsic/solutions:worlds",
    ],
)
