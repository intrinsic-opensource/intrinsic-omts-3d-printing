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

"""Watches the printer's job; pulls each new job's G-code and builds its STL.

Every poll asks the printer for its job. A job not read before (by id, file
name and size) is downloaded into `<storage>/<id>_<name>/`, checked, converted
by `tools.printer.gcode_to_stl`, and recorded. The same file sent again gets a
new job id, so it is read again, but its conversion is copied from the earlier
one when the content (SHA-256) is identical. Nothing here talks to a robot.
"""

import dataclasses
import datetime
import hashlib
import json
import logging
import re
import shutil
import threading
from pathlib import Path

from services.prusalink import client
from services.prusalink import prusalink_pb2 as pb
from tools.printer import gcode_to_stl

_GCODE_NAME = re.compile(r".+\.(?:gcode|bgcode|gco)", re.IGNORECASE)
_MODEL_FILE = re.compile(
  r"model\.stl|part\.stl|supports\.stl|by_type/[A-Za-z0-9_]{1,60}\.stl"
)
_TRANSIENT = (502, 504)


def _safe(name: str) -> str:
  return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")[:80] or "job"


def _key(job: client.JobFile) -> tuple:
  return (job.job_id, job.name, job.size, job.m_timestamp)


def _now() -> datetime.datetime:
  return datetime.datetime.now(datetime.timezone.utc)


@dataclasses.dataclass
class JobRecord:
  job_id: int
  file_name: str
  size: int | None
  folder: Path
  m_timestamp: int | None = None
  state: int = pb.DOWNLOADING
  sha256: str = ""
  layers: int = 0
  warnings: list[str] = dataclasses.field(default_factory=list)
  error: str = ""
  reused: bool = False
  transient: bool = False
  updated_at: datetime.datetime = dataclasses.field(default_factory=_now)

  @property
  def key(self) -> tuple:
    return (self.job_id, self.file_name, self.size, self.m_timestamp)

  @property
  def stl(self) -> Path:
    return self.folder / "compound.stl"

  def set(self, state: int, error: str = "") -> None:
    self.state, self.error, self.updated_at = state, error, _now()

  def to_proto(self, poll_error: str = "") -> pb.ModelStatus:
    ready = self.state == pb.MODEL_READY
    result = pb.ModelStatus(
      state=self.state,
      job_id=self.job_id,
      file_name=self.file_name,
      file_bytes=self.size or 0,
      sha256=self.sha256,
      stl_path=str(self.stl) if ready else "",
      http_path=f"/v1/jobs/{self.job_id}/model.stl" if ready else "",
      layers=self.layers,
      warnings=self.warnings,
      error=self.error,
      reused=self.reused,
      poll_error=poll_error,
    )
    result.updated_at.FromDatetime(self.updated_at)
    result.observed_at.GetCurrentTime()
    return result


class JobWatcher:
  def __init__(
    self,
    printer: client.PrusaLinkClient,
    storage_dir: Path,
    interval: float = 2.0,
    max_bytes: int = client.MAX_DOWNLOAD_BYTES,
    convert=gcode_to_stl.convert,
    exclude: tuple[str, ...] = ("Custom",),
  ):
    self.printer = printer
    self.root = Path(storage_dir) / "jobs"
    self.interval = interval
    self.max_bytes = max_bytes
    self.convert = convert
    self.exclude = exclude
    self.poll_error = ""
    self._records: list[JobRecord] = []
    self._lock = threading.RLock()
    self._stop = threading.Event()
    self._thread: threading.Thread | None = None
    self.root.mkdir(parents=True, exist_ok=True)
    self._load_existing()

  # -- lifecycle -------------------------------------------------------------

  def start(self) -> None:
    self._thread = threading.Thread(
      target=self._run, name="job-watcher", daemon=True
    )
    self._thread.start()

  def stop(self) -> None:
    self._stop.set()
    if self._thread is not None:
      self._thread.join(timeout=10)

  def _run(self) -> None:
    while not self._stop.is_set():
      try:
        self.poll_once()
      except Exception:  # The watcher must outlive any single bad job.
        logging.exception("Job watcher poll failed")
      self._stop.wait(self.interval)

  def _load_existing(self) -> None:
    """Remembers jobs converted before a restart, so they are not re-read."""
    for meta in sorted(self.root.glob("*/job.json")):
      try:
        data = json.loads(meta.read_text())
        record = JobRecord(
          job_id=int(data["job_id"]),
          file_name=str(data["name"]),
          size=data.get("bytes"),
          m_timestamp=data.get("m_timestamp"),
          folder=meta.parent,
          state=pb.MODEL_READY,
          sha256=str(data.get("sha256", "")),
          layers=int(data.get("layers", 0)),
          warnings=list(data.get("warnings", [])),
          reused=bool(data.get("reused", False)),
        )
      except (OSError, ValueError, KeyError, TypeError):
        continue
      if record.stl.is_file():
        self._records.append(record)

  # -- polling ---------------------------------------------------------------

  def poll_once(self) -> None:
    try:
      job = self.printer.get_job_file()
    except client.ServiceError as exc:
      # A job without a downloadable file is not an error of the printer.
      self.poll_error = (
        "" if exc.code == "no_download_reference" else f"{exc.code}: {exc}"
      )
      return
    self.poll_error = ""
    if job is None:
      return
    with self._lock:
      record = next(
        (
          r
          for r in self._records
          if r.key == _key(job)
        ),
        None,
      )
      if record is not None and not record.transient:
        return  # Already read (or permanently failed): never read twice.
      if record is None:
        record = JobRecord(
          job_id=job.job_id,
          file_name=job.name,
          size=job.size,
          m_timestamp=job.m_timestamp,
          folder=self._new_folder(job),
        )
        self._records.append(record)
      record.transient = False
      record.set(pb.DOWNLOADING)
    logging.info("Job %s (%s): new, downloading", job.job_id, job.name)
    self._process(record, job)

  def _new_folder(self, job: client.JobFile) -> Path:
    base = self.root / f"{job.job_id}_{_safe(job.name)}"
    folder, n = base, 1
    while folder.exists() and not any(
      r.folder == folder and r.key == _key(job) for r in self._records
    ):
      n += 1
      folder = base.with_name(f"{base.name}-{n}")
    return folder

  def _process(self, record: JobRecord, job: client.JobFile) -> None:
    try:
      if not _GCODE_NAME.fullmatch(job.name):
        raise ValueError(
          f"{job.name!r} is not a G-code file (.gcode, .bgcode or .gco)"
        )
      record.folder.mkdir(parents=True, exist_ok=True)
      suffix = ".bgcode" if job.name.lower().endswith(".bgcode") else ".gcode"
      downloaded = record.folder / f"job{suffix}"
      size = self.printer.download(job.download_path, downloaded, self.max_bytes)
      record.size = record.size if record.size is not None else size
      digest = hashlib.sha256()
      with open(downloaded, "rb") as stream:
        while chunk := stream.read(1 << 20):
          digest.update(chunk)
      record.sha256 = digest.hexdigest()
      earlier = self._converted_with(record)
      if earlier is not None:
        shutil.copytree(
          earlier.folder,
          record.folder,
          dirs_exist_ok=True,
          ignore=shutil.ignore_patterns("job.*"),
        )
        record.layers, record.warnings = earlier.layers, list(earlier.warnings)
        record.reused = True
        logging.info(
          "Job %s: same content as job %s, model reused",
          job.job_id,
          earlier.job_id,
        )
      else:
        record.set(pb.CONVERTING)
        summary = self.convert(downloaded, record.folder, self.exclude)
        if "compound" not in summary:
          raise ValueError(
            "no extrusion moves found; this does not look like G-code"
          )
        record.layers = int(summary["layers"])
        record.warnings = list(summary["warnings"])
      (record.folder / "job.json").write_text(
        json.dumps(
          {
            "job_id": record.job_id,
            "name": record.file_name,
            "bytes": size,
            "m_timestamp": record.m_timestamp,
            "sha256": record.sha256,
            "layers": record.layers,
            "warnings": record.warnings,
            "reused": record.reused,
            "pulled_at": _now().isoformat(),
          },
          indent=2,
        )
      )
      record.set(pb.MODEL_READY)
      logging.info("Job %s: model ready at %s", job.job_id, record.stl)
    except client.ServiceError as exc:
      record.transient = exc.status in _TRANSIENT
      record.set(pb.MODEL_FAILED, f"{exc.code}: {exc}")
      logging.warning("Job %s: %s", job.job_id, record.error)
    except (ValueError, OSError, RuntimeError, UnicodeError, EOFError) as exc:
      record.set(pb.MODEL_FAILED, f"{type(exc).__name__}: {exc}")
      logging.warning("Job %s: %s", job.job_id, record.error)

  def _converted_with(self, record: JobRecord) -> JobRecord | None:
    with self._lock:
      return next(
        (
          r
          for r in self._records
          if r is not record
          and r.state == pb.MODEL_READY
          and r.sha256 == record.sha256
          and r.stl.is_file()
        ),
        None,
      )

  # -- reading ---------------------------------------------------------------

  def find(self, job_id: int | None = None) -> JobRecord | None:
    with self._lock:
      records = [
        r for r in self._records if job_id is None or r.job_id == job_id
      ]
      return records[-1] if records else None

  def status(self, job_id: int | None = None) -> pb.ModelStatus:
    record = self.find(job_id)
    if record is None:
      if job_id is not None:
        raise client.ServiceError(404, "unknown_job", f"No job {job_id} seen")
      none = pb.ModelStatus(state=pb.NO_JOB, poll_error=self.poll_error)
      none.observed_at.GetCurrentTime()
      return none
    return record.to_proto(self.poll_error)

  def list(self) -> pb.ModelList:
    with self._lock:
      return pb.ModelList(
        models=[r.to_proto(self.poll_error) for r in self._records]
      )

  def model_file(self, job_id: int, relative: str) -> Path:
    if not _MODEL_FILE.fullmatch(relative):
      raise client.ServiceError(404, "not_found", "Unknown model file")
    record = self.find(job_id)
    if record is None or record.state != pb.MODEL_READY:
      raise client.ServiceError(404, "model_not_ready", "No model for that job")
    path = record.stl if relative == "model.stl" else record.folder / relative
    if not path.is_file():
      raise client.ServiceError(404, "not_found", "Unknown model file")
    return path
