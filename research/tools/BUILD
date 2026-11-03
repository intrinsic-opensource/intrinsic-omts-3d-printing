load("@intrinsic-core//bazel:python.bzl", "py_binary", "py_library")

package(default_visibility = ["//visibility:public"])

# Offline checks for the reBot cell (README.md). They read configs/rebot/ and
# the models from the checkout at run time (BUILD_WORKSPACE_DIRECTORY), so use
# `bazel run`.

py_library(
    name = "kin",
    srcs = ["kin.py"],
    deps = [
        "@ai_intrinsic_sdks_pip_deps//numpy",
        "@ai_intrinsic_sdks_pip_deps//scipy",
    ],
)

py_library(
    name = "cell",
    srcs = ["cell.py"],
    deps = [
        ":kin",
        "@ai_intrinsic_sdks_pip_deps//numpy",
    ],
)

py_binary(
    name = "grasp_clearance",
    srcs = ["grasp_clearance.py"],
    main = "grasp_clearance.py",
    deps = [
        ":cell",
        "@ai_intrinsic_sdks_pip_deps//numpy",
    ],
)

py_binary(
    name = "config_clearance",
    srcs = ["config_clearance.py"],
    main = "config_clearance.py",
    deps = [
        ":cell",
        ":kin",
        "@ai_intrinsic_sdks_pip_deps//numpy",
    ],
)

py_binary(
    name = "a_frames",
    srcs = ["a_frames.py"],
    main = "a_frames.py",
    deps = [
        ":cell",
        ":kin",
        "@ai_intrinsic_sdks_pip_deps//numpy",
    ],
)

py_binary(
    name = "view_search",
    srcs = ["view_search.py"],
    main = "view_search.py",
    deps = [
        ":cell",
        ":kin",
        "@ai_intrinsic_sdks_pip_deps//numpy",
    ],
)

py_binary(
    name = "release_drift",
    srcs = ["release_drift.py"],
    main = "release_drift.py",
)

py_binary(
    name = "cuboid_sweep",
    srcs = ["cuboid_sweep.py"],
    main = "cuboid_sweep.py",
    deps = [
        ":a_frames_lib",
        ":cell",
        ":kin",
        "@ai_intrinsic_sdks_pip_deps//numpy",
    ],
)

py_library(
    name = "a_frames_lib",
    srcs = ["a_frames.py"],
    deps = [
        ":cell",
        ":kin",
        "@ai_intrinsic_sdks_pip_deps//numpy",
    ],
)

py_binary(
    name = "part_trial",
    srcs = ["part_trial.py"],
    main = "part_trial.py",
    deps = [
        ":a_frames_lib",
        ":cell",
        "@ai_intrinsic_sdks_pip_deps//numpy",
    ],
)
