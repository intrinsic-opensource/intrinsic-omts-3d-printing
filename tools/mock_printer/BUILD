load("@intrinsic-core//bazel:python.bzl", "py_binary", "py_library")

package(default_visibility = ["//visibility:public"])

# Only so unit tests can import it. The tool runs on its own:
#   python3 tools/mock_printer/mock_printer.py
py_library(
    name = "mock_printer_lib",
    srcs = ["mock_printer.py"],
)

py_binary(
    name = "mock_printer",
    srcs = ["mock_printer.py"],
    main = "mock_printer.py",
)
