# Copyright 2026 Intrinsic Innovation LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Rebuilds what a print job deposits, as STL meshes, from its G-code alone.

The printer always has the G-code (`.gcode`, or `.bgcode` on a Core One), so
this needs nothing from the slicer: no project file, no source STL. Every
extruded move becomes a small box (length x width x height, as the slicer
tagged it), grouped by the slicer's `;TYPE:` (perimeter, infill, support...).

  python3 gcode_to_stl.py job.bgcode --out job_toolpaths

Writes to `--out`:
  compound.stl    everything printed except the excluded types (default:
                  `Custom`, the purge line), in the bed frame (mm, origin at
                  the bed corner as the printer sees it).
  part.stl        the designed object alone: no supports, brim/skirt or
                  wipe tower (written when the job has any such extrusion).
  supports.stl    the support structures alone (`Support material` and
                  `Support material interface`), when the job has any.
  by_type/*.stl   the same, one file per `;TYPE`, to inspect each part.
  summary.json    types, segment counts, volumes, bounds, layers, warnings.

What this is and is not: a faithful envelope of the extruded plastic at
toolpath resolution, not the designer's mesh. Fine detail below the nozzle
width is gone, surfaces are layer-stepped, and the boxes of neighbouring
paths touch or overlap (it is not a boolean union). Arcs (G2/G3) are
approximated by chords, and moves are assumed to be in millimetres.

Binary G-code (libbgcode, version 1) is decoded with a pure-Python
heatshrink and MeatPack implementation. Standard library only.
"""

import argparse
import json
import math
from pathlib import Path
import re
import struct
import sys
import zlib

Triangles = list[tuple[tuple[float, float, float], ...]]
Segment = tuple[str, float, float, float, float, float, float, float]

_MAX_CHORD_MM = 0.4
_MAX_CHORD_RAD = math.radians(8)
_DEFAULT_EXCLUDE = ("Custom",)


def _is_support(kind: str) -> bool:
  return kind.lower().startswith("support")


def _is_part(kind: str) -> bool:
  """The designed object: not supports, brim/skirt or the wipe tower."""
  lowered = kind.lower()
  return not (
    _is_support(kind) or lowered.startswith(("skirt", "wipe tower", "custom"))
  )
_WORD = re.compile(r"([A-Z])(-?\d*\.?\d+)")
_COMMAND = re.compile(r"^\s*([GM]\d+)", re.IGNORECASE)

# libbgcode block types and codes.
_BLOCK_GCODE = 1
_BLOCK_NAMES = {
    0: "file_metadata",
    2: "slicer_metadata",
    3: "printer_metadata",
    4: "print_metadata",
}
_COMPRESSION_NONE, _COMPRESSION_DEFLATE = 0, 1
_COMPRESSION_HEATSHRINK = {2: (11, 4), 3: (12, 4)}
_ENCODING_MEATPACK, _ENCODING_MEATPACK_COMMENTS = 1, 2


def heatshrink_decompress(data: bytes, window_bits: int, lookahead_bits: int):
  """Decodes a heatshrink stream (MSB-first bits, tag 1 = literal).

  The decoder's window starts zero-filled, so a back-reference may reach
  before the first output byte.
  """
  window = 1 << window_bits
  out = bytearray(window)
  acc = accbits = pos = 0
  size = len(data)

  def take(n: int):
    nonlocal acc, accbits, pos
    while accbits < n:
      if pos >= size:
        return None
      acc = (acc << 8) | data[pos]
      pos += 1
      accbits += 8
    accbits -= n
    value = (acc >> accbits) & ((1 << n) - 1)
    acc &= (1 << accbits) - 1
    return value

  while True:
    tag = take(1)
    if tag is None:
      break
    if tag:
      byte = take(8)
      if byte is None:
        break
      out.append(byte)
      continue
    index = take(window_bits)
    count = take(lookahead_bits)
    if index is None or count is None:
      break  # trailing padding bits
    offset, count = index + 1, count + 1
    if offset > window:
      raise ValueError("corrupt heatshrink stream")
    for _ in range(count):
      out.append(out[-offset])
  return bytes(out[window:])


_MP_TABLE = b"0123456789. \nGX\0"
_MP_TABLE_NO_SPACES = b"0123456789.E\nGX\0"
_MP_CMD_DISABLE, _MP_CMD_ENABLE = 250, 251
_MP_CMD_RESET, _MP_CMD_NO_SPACES_ON, _MP_CMD_NO_SPACES_OFF = 249, 247, 246


def meatpack_decode(data: bytes) -> bytes:
  """Decodes MeatPack: two characters per byte, 0xFF 0xFF starts a command."""
  out = bytearray()
  packing, table = False, _MP_TABLE
  i, size = 0, len(data)
  while i < size:
    b = data[i]
    if b == 0xFF and i + 1 < size and data[i + 1] == 0xFF:
      command = data[i + 2] if i + 2 < size else 0
      i += 3
      if command == _MP_CMD_ENABLE:
        packing = True
      elif command == _MP_CMD_DISABLE:
        packing = False
      elif command == _MP_CMD_RESET:
        packing, table = False, _MP_TABLE
      elif command == _MP_CMD_NO_SPACES_ON:
        table = _MP_TABLE_NO_SPACES
      elif command == _MP_CMD_NO_SPACES_OFF:
        table = _MP_TABLE
      continue
    i += 1
    if not packing:
      out.append(b)
      continue
    low, high = b & 0xF, b >> 4
    if i + (low == 0xF) + (high == 0xF) > size:
      break  # truncated stream
    first = data[i] if low == 0xF else table[low]
    i += low == 0xF
    second = data[i] if high == 0xF else table[high]
    i += high == 0xF
    out.append(first)
    out.append(second)
  return bytes(out)


def read_bgcode(data: bytes) -> tuple[str, dict]:
  """Returns the G-code text and the metadata blocks of a .bgcode file."""
  if data[:4] != b"GCDE":
    raise ValueError("not a binary G-code file")
  version, checksum = struct.unpack("<IH", data[4:10])
  if version != 1:
    raise ValueError(f"unsupported bgcode version {version}")
  pos, text, meta = 10, [], {}
  while pos + 8 <= len(data):
    block, compression, size = struct.unpack("<HHI", data[pos : pos + 8])
    pos += 8
    stored = size
    if compression != _COMPRESSION_NONE:
      stored = struct.unpack("<I", data[pos : pos + 4])[0]
      pos += 4
    encoding = struct.unpack("<H", data[pos : pos + 2])[0]
    pos += 6 if block == 5 else 2  # thumbnails carry three u16 parameters
    payload = data[pos : pos + stored]
    pos += stored + (4 if checksum == 1 else 0)
    if block == 5:
      continue
    if compression == _COMPRESSION_DEFLATE:
      payload = zlib.decompress(payload)
    elif compression in _COMPRESSION_HEATSHRINK:
      payload = heatshrink_decompress(
          payload, *_COMPRESSION_HEATSHRINK[compression]
      )
    if len(payload) != size:
      raise ValueError(f"block {block}: decoded {len(payload)} != {size}")
    if block == _BLOCK_GCODE:
      if encoding in (_ENCODING_MEATPACK, _ENCODING_MEATPACK_COMMENTS):
        payload = meatpack_decode(payload)
      text.append(payload.decode("utf-8", errors="replace"))
    elif block in _BLOCK_NAMES:
      meta[_BLOCK_NAMES[block]] = dict(
          line.split("=", 1)
          for line in payload.decode("utf-8", errors="replace").splitlines()
          if "=" in line
      )
  return "".join(text), meta


def read_gcode(path: Path) -> tuple[str, dict]:
  """G-code text and metadata from a .gcode or .bgcode file."""
  data = path.read_bytes()
  if data[:4] == b"GCDE":
    return read_bgcode(data)
  return data.decode("utf-8", errors="replace"), {}


def _arc_points(x, y, nx, ny, i, j, clockwise):
  """Points along a G2/G3 arc (centre = start + (i, j)), end included."""
  cx, cy = x + i, y + j
  radius = math.hypot(x - cx, y - cy)
  a0, a1 = math.atan2(y - cy, x - cx), math.atan2(ny - cy, nx - cx)
  sweep = a1 - a0
  if clockwise and sweep >= 0:
    sweep -= 2 * math.pi
  elif not clockwise and sweep <= 0:
    sweep += 2 * math.pi
  if radius < 1e-9:
    return [(nx, ny)]
  step = min(_MAX_CHORD_RAD, _MAX_CHORD_MM / radius)
  count = max(1, math.ceil(abs(sweep) / step))
  points = [
      (cx + radius * math.cos(a0 + sweep * k / count),
       cy + radius * math.sin(a0 + sweep * k / count))
      for k in range(1, count)
  ]  # fmt: skip
  return points + [(nx, ny)]


def parse_toolpaths(text: str) -> tuple[list[Segment], dict]:
  """Every extruding move as (type, x0, y0, x1, y1, z, width, height).

  `z` is the top of the deposited layer. Returns the segments and
  `{"warnings": [...], "layers": n}`.
  """
  x = y = z = e = 0.0
  absolute_xy = absolute_e = True
  kind, width, height = "Unknown", 0.4, 0.2
  unretracting = False  # PrusaSlicer 3.x: de-retraction done while moving
  segments: list[Segment] = []
  warnings: set[str] = set()
  layer_tops: set[float] = set()
  for raw in text.splitlines():
    line = raw.strip()
    if line.startswith(";"):
      try:
        if line.startswith(";TYPE:"):
          kind = line[6:].strip()
        elif line.startswith(";WIDTH:"):
          width = float(line[7:])
        elif line.startswith(";HEIGHT:"):
          height = float(line[8:])
        elif line.startswith(";MOVING_UNRETRACT_START"):
          unretracting = True
        elif line.startswith(";MOVING_UNRETRACT_END"):
          unretracting = False
      except ValueError:
        pass
      continue
    body = line.split(";", 1)[0]
    match = _COMMAND.match(body)
    if not match:
      continue
    # Binary G-code may have spaces removed ("G1Z20F720"), so words are
    # found by pattern, not by splitting.
    cmd = match.group(1).upper()
    rest = body[match.end() :].upper()
    if cmd == "G90":
      absolute_xy = True
    elif cmd == "G91":
      absolute_xy = False
    elif cmd == "M82":
      absolute_e = True
    elif cmd == "M83":
      absolute_e = False
    elif cmd == "G92":
      vals = dict(_WORD.findall(rest))
      if "E" in vals:
        e = float(vals["E"])
    elif cmd in ("G0", "G1", "G2", "G3"):
      vals = {k: float(v) for k, v in _WORD.findall(rest)}
      nx = vals["X"] if "X" in vals and absolute_xy else x + vals.get("X", 0)
      ny = vals["Y"] if "Y" in vals and absolute_xy else y + vals.get("Y", 0)
      nz = vals["Z"] if "Z" in vals and absolute_xy else z + vals.get("Z", 0)
      de = 0.0
      if "E" in vals:
        de = vals["E"] - e if absolute_e else vals["E"]
        if absolute_e:
          e = vals["E"]
      if de > 1e-9 and (nx, ny) != (x, y) and not unretracting:
        if cmd in ("G2", "G3"):
          if "I" in vals or "J" in vals:
            points = _arc_points(
                x, y, nx, ny, vals.get("I", 0), vals.get("J", 0), cmd == "G2"
            )
          else:
            warnings.add("arc with radius (R) form drawn as a straight line")
            points = [(nx, ny)]
        else:
          points = [(nx, ny)]
        px, py = x, y
        for qx, qy in points:
          if math.hypot(qx - px, qy - py) > 1e-6:
            segments.append((kind, px, py, qx, qy, nz, width, height))
          px, py = qx, qy
        layer_tops.add(round(nz, 4))
      x, y, z = nx, ny, nz
  return segments, {"warnings": sorted(warnings), "layers": len(layer_tops)}


def merge_segments(segments: list[Segment]) -> list[Segment]:
  """Joins consecutive collinear segments of one type, layer and width."""
  merged: list[list] = []
  for seg in segments:
    kind, x0, y0, x1, y1, z, w, h = seg
    if merged:
      pk, px0, py0, px1, py1, pz, pw, ph = merged[-1]
      ux, uy, vx, vy = px1 - px0, py1 - py0, x1 - x0, y1 - y0
      if (
          (kind, x0, y0, z, w, h) == (pk, px1, py1, pz, pw, ph)
          and abs(ux * vy - uy * vx)
          < 1e-6 * math.hypot(ux, uy) * math.hypot(vx, vy)
          and ux * vx + uy * vy > 0
      ):
        merged[-1][3], merged[-1][4] = x1, y1
        continue
    merged.append(list(seg))
  return [tuple(m) for m in merged]


def _prism(x0, y0, x1, y1, z_top, w, h) -> Triangles:
  """A closed, outward-facing box along one toolpath segment."""
  length = math.hypot(x1 - x0, y1 - y0)
  nx, ny = -(y1 - y0) / length * w / 2, (x1 - x0) / length * w / 2
  ring = [
      (x0 + nx, y0 + ny),
      (x1 + nx, y1 + ny),
      (x1 - nx, y1 - ny),
      (x0 - nx, y0 - ny),
  ]
  v = [(cx, cy, z_top - h) for cx, cy in ring]
  v += [(cx, cy, z_top) for cx, cy in ring]
  faces = [(0, 1, 2), (0, 2, 3), (4, 7, 6), (4, 6, 5)]
  for i in range(4):
    j = (i + 1) % 4
    faces += [(j, i, i + 4), (j, i + 4, j + 4)]
  return [tuple(v[k] for k in f) for f in faces]


def to_triangles(segments: list[Segment]) -> Triangles:
  triangles: Triangles = []
  for _, *seg in merge_segments(segments):
    triangles += _prism(*seg)
  return triangles


def _normal(tri):
  (ax, ay, az), (bx, by, bz), (cx, cy, cz) = tri
  ux, uy, uz, vx, vy, vz = bx - ax, by - ay, bz - az, cx - ax, cy - ay, cz - az
  n = (uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)
  length = math.sqrt(sum(c * c for c in n))
  return (0.0, 0.0, 0.0) if length == 0 else tuple(c / length for c in n)


def write_stl(path: Path, triangles: Triangles) -> None:
  """Writes a binary STL."""
  with open(path, "wb") as f:
    f.write(b"omts gcode_to_stl".ljust(80, b"\0"))
    f.write(struct.pack("<I", len(triangles)))
    for tri in triangles:
      f.write(struct.pack("<3f", *_normal(tri)))
      for p in tri:
        f.write(struct.pack("<3f", *p))
      f.write(b"\0\0")


def _bounds(triangles: Triangles) -> dict:
  points = [p for tri in triangles for p in tri]
  return {
      "min": [round(min(p[k] for p in points), 3) for k in range(3)],
      "max": [round(max(p[k] for p in points), 3) for k in range(3)],
  }


def _slug(kind: str) -> str:
  return re.sub(r"[^A-Za-z0-9]+", "_", kind).strip("_").lower() or "unknown"


def convert(
    gcode_path: Path,
    out_dir: Path,
    exclude: tuple[str, ...] = _DEFAULT_EXCLUDE,
    by_type: bool = True,
) -> dict:
  """Writes compound.stl, by_type/*.stl and summary.json; returns summary."""
  text, meta = read_gcode(gcode_path)
  segments, info = parse_toolpaths(text)
  out_dir.mkdir(parents=True, exist_ok=True)
  groups: dict[str, list[Segment]] = {}
  for seg in segments:
    groups.setdefault(seg[0], []).append(seg)
  kept = {k: v for k, v in groups.items() if k not in exclude}
  summary = {
      "source": str(gcode_path),
      "format": "bgcode" if gcode_path.read_bytes()[:4] == b"GCDE" else "gcode",
      "printer_model": meta.get("printer_metadata", {}).get("printer_model"),
      "layers": info["layers"],
      "excluded_types": [k for k in groups if k in exclude],
      "warnings": info["warnings"],
      "types": {},
  }
  for kind, segs in sorted(groups.items()):
    triangles = to_triangles(segs)
    summary["types"][kind] = {
        "segments": len(segs),
        "triangles": len(triangles),
        "volume_mm3": round(sum(
            math.hypot(s[3] - s[1], s[4] - s[2]) * s[6] * s[7] for s in segs
        ), 1),
        "bounds": _bounds(triangles),
        "included": kind in kept,
    }  # fmt: skip
    if by_type and kind in kept:
      (out_dir / "by_type").mkdir(exist_ok=True)
      write_stl(out_dir / "by_type" / f"{_slug(kind)}.stl", triangles)
  compound = [t for segs in kept.values() for t in to_triangles(segs)]
  if compound:
    write_stl(out_dir / "compound.stl", compound)
    summary["compound"] = {
        "triangles": len(compound),
        "bounds": _bounds(compound),
    }
  for name, pick in (("part", _is_part), ("supports", _is_support)):
    chosen = [
        t for k, segs in groups.items() if pick(k) for t in to_triangles(segs)
    ]
    if chosen:
      write_stl(out_dir / f"{name}.stl", chosen)
      summary[name] = {
          "types": sorted(k for k in groups if pick(k)),
          "triangles": len(chosen),
          "bounds": _bounds(chosen),
      }
  (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
  return summary


def main(argv: list[str]) -> int:
  parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
  parser.add_argument("gcode", type=Path, help=".gcode or .bgcode file")
  parser.add_argument("--out", type=Path, help="output folder")
  parser.add_argument(
      "--exclude",
      default=",".join(_DEFAULT_EXCLUDE),
      help="comma-separated ;TYPE names to leave out of compound.stl "
      "(default: %(default)s; use '' to keep all)",
  )
  parser.add_argument("--no-by-type", action="store_true")
  args = parser.parse_args(argv[1:])
  out = args.out or args.gcode.with_name(args.gcode.stem + "_toolpaths")
  exclude = tuple(t for t in args.exclude.split(",") if t)
  summary = convert(args.gcode, out, exclude, not args.no_by_type)
  print(f"wrote {out}/compound.stl  (+ included, - excluded)")
  for kind, t in summary["types"].items():
    mark = "+" if t["included"] else "-"
    print(
        f" {mark} {kind:28s} {t['segments']:7d} segs"
        f" {t['volume_mm3']:9.1f} mm3"
    )
  for warning in summary["warnings"]:
    print("warning:", warning)
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv))
