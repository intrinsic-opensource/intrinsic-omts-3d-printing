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
        "@ai_intrinsic_sdks_pip_deps//pyyaml",
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

py_library(
    name = "cell_checks",
    srcs = ["cell_checks.py"],
    deps = [
        ":a_frames_lib",
        ":cell",
        ":kin",
        "@ai_intrinsic_sdks_pip_deps//numpy",
    ],
)

py_binary(
    name = "configure_cell",
    srcs = ["configure_cell.py"],
    main = "configure_cell.py",
    deps = [
        ":a_frames_lib",
        ":cell",
        ":cell_checks",
        ":part_trial_lib",
        "@ai_intrinsic_sdks_pip_deps//numpy",
    ],
)

py_binary(
    name = "cell_limits",
    srcs = ["cell_limits.py"],
    main = "cell_limits.py",
    deps = [
        ":cell",
        ":cell_checks",
        "@ai_intrinsic_sdks_pip_deps//numpy",
    ],
)

py_library(
    name = "part_trial_lib",
    srcs = ["part_trial.py"],
    deps = [
        ":a_frames_lib",
        ":cell",
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

# Needs onnxruntime on PYTHONPATH, installed separately (README.md); it is not
# among the solution's Python dependencies.
py_binary(
    name = "prompt_sweep",
    srcs = ["prompt_sweep.py"],
    main = "prompt_sweep.py",
    deps = [
        "@ai_intrinsic_sdks_pip_deps//ftfy",
        "@ai_intrinsic_sdks_pip_deps//numpy",
        "@ai_intrinsic_sdks_pip_deps//pillow",
        "@ai_intrinsic_sdks_pip_deps//regex",
        "@foundationpose_perception_pipeline//:perception_pipeline",
    ],
)
