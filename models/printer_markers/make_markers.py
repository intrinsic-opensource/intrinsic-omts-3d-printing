# Copyright 2026 Intrinsic Innovation LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Writes the ArUco marker tiles as GLB files with an embedded texture.

Each tile is a flat quad in the marker frame of src/core/door.py (origin at
the centre, x right and y down in the image, z into the marker), with the
marker on a white quiet zone. The SDF material ignores texture maps, so the
texture has to be embedded in the mesh.

  bazel run //models/printer_markers:make_markers -- \
      --out_dir=$PWD/models/printer
"""

import argparse
import json
import pathlib
import struct

import cv2
import numpy as np

from src.core import door

QUIET = 0.17  # quiet zone, as a fraction of the marker side
PIXELS = 600  # marker pixels per side (cells are 100 px)


def tile_png(marker_id: int) -> bytes:
  marker = cv2.aruco.generateImageMarker(
    cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50), marker_id, PIXELS
  )
  pad = round(PIXELS * QUIET)
  tile = np.full((PIXELS + 2 * pad,) * 2, 255, np.uint8)
  tile[pad : pad + PIXELS, pad : pad + PIXELS] = marker
  ok, buf = cv2.imencode(".png", tile)
  assert ok
  return buf.tobytes()


def tile_glb(marker_id: int, size_m: float) -> bytes:
  """A quad facing -z (toward the viewer) with the marker's PNG."""
  h = size_m * (1 + 2 * QUIET) / 2.0
  # Image top-left is at (-h, -h): x right, y down.
  pos = np.array(
    [[-h, -h, 0], [h, -h, 0], [h, h, 0], [-h, h, 0]], dtype=np.float32
  )
  nrm = np.tile(np.array([0, 0, -1], np.float32), (4, 1))
  uv = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float32)
  # Triangles wound counter-clockwise seen from -z.
  idx = np.array([0, 2, 1, 0, 3, 2], dtype=np.uint16)
  png = tile_png(marker_id)
  blobs = [pos.tobytes(), nrm.tobytes(), uv.tobytes(), idx.tobytes(), png]
  offsets, data = [], b""
  for b in blobs:
    offsets.append(len(data))
    data += b + b"\x00" * (-len(b) % 4)
  doc = {
    "asset": {"version": "2.0", "generator": "make_markers.py"},
    "scene": 0,
    "scenes": [{"nodes": [0]}],
    "nodes": [{"mesh": 0, "name": f"aruco_{marker_id}"}],
    "meshes": [
      {
        "primitives": [
          {
            "attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2},
            "indices": 3,
            "material": 0,
            "mode": 4,
          }
        ]
      }
    ],
    "materials": [
      {
        "pbrMetallicRoughness": {
          "baseColorTexture": {"index": 0},
          "metallicFactor": 0.0,
          "roughnessFactor": 1.0,
        },
        "doubleSided": True,
      }
    ],
    "textures": [{"source": 0, "sampler": 0}],
    "samplers": [{"magFilter": 9729, "minFilter": 9729}],
    "images": [{"bufferView": 4, "mimeType": "image/png"}],
    "buffers": [{"byteLength": len(data)}],
    "bufferViews": [
      {"buffer": 0, "byteOffset": offsets[0], "byteLength": pos.nbytes},
      {"buffer": 0, "byteOffset": offsets[1], "byteLength": nrm.nbytes},
      {"buffer": 0, "byteOffset": offsets[2], "byteLength": uv.nbytes},
      {"buffer": 0, "byteOffset": offsets[3], "byteLength": idx.nbytes},
      {"buffer": 0, "byteOffset": offsets[4], "byteLength": len(png)},
    ],
    "accessors": [
      {
        "bufferView": 0,
        "componentType": 5126,
        "count": 4,
        "type": "VEC3",
        "min": pos.min(axis=0).tolist(),
        "max": pos.max(axis=0).tolist(),
      },
      {"bufferView": 1, "componentType": 5126, "count": 4, "type": "VEC3"},
      {"bufferView": 2, "componentType": 5126, "count": 4, "type": "VEC2"},
      {"bufferView": 3, "componentType": 5123, "count": 6, "type": "SCALAR"},
    ],
  }
  js = json.dumps(doc, separators=(",", ":")).encode()
  js += b" " * (-len(js) % 4)
  total = 12 + 8 + len(js) + 8 + len(data)
  return (
    struct.pack("<III", 0x46546C67, 2, total)
    + struct.pack("<II", len(js), 0x4E4F534A)
    + js
    + struct.pack("<II", len(data), 0x004E4942)
    + data
  )


def main() -> None:
  parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
  parser.add_argument("--out_dir", required=True, type=pathlib.Path)
  args = parser.parse_args()
  args.out_dir.mkdir(parents=True, exist_ok=True)
  for marker_id in sorted(door.MARKERS):
    path = args.out_dir / f"aruco_{marker_id}.glb"
    path.write_bytes(tile_glb(marker_id, door.MARKER_SIZE_M))
    print(f"wrote {path}")


if __name__ == "__main__":
  main()
