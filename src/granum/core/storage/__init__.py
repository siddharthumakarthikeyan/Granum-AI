"""Local fsync/replace and writer locks; remote fsspec stores remain single-writer.

Object metadata is the publication commit marker. Uncommitted directories have no
metadata and are not indexed. These guarantees require a local filesystem, not NFS.
"""
from __future__ import annotations

import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from weakref import WeakValueDictionary

from filelock import FileLock

from granum.core.url import Url

_locks: WeakValueDictionary[str, FileLock] = WeakValueDictionary()
_guard = threading.Lock()
_remote = threading.RLock()


def fsync_directory(path: Path) -> None:
	if os.name == "nt":
		return  # Windows os.replace is atomic; directory fsync is not exposed here.
	fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
	try:
		os.fsync(fd)
	finally:
		os.close(fd)


def durable_mkdir(path: Path, *, exist_ok: bool = True) -> None:
	"""Persist new directory entries as well as the files subsequently written in them."""
	if not path.parent.exists():
		durable_mkdir(path.parent)
	try:
		path.mkdir()
	except FileExistsError:
		if not exist_ok or not path.is_dir():
			raise
	else:
		fsync_directory(path.parent)


def atomic_bytes(path: Path, data: bytes, *, mode: int | None = None) -> None:
	durable_mkdir(path.parent)
	fd, temporary = tempfile.mkstemp(prefix=".granum-write-", dir=path.parent)
	try:
		if mode is not None:
			os.chmod(temporary, mode)
		elif path.exists():
			os.chmod(temporary, path.stat().st_mode & 0o777)
		with os.fdopen(fd, "wb") as handle:
			handle.write(data)
			handle.flush()
			os.fsync(handle.fileno())
		os.replace(temporary, path)
		fsync_directory(path.parent)
	finally:
		if os.path.exists(temporary):
			os.unlink(temporary)


@contextmanager
def locked(url: Url):
	"""Reentrant within a thread and exclusive across local writer processes."""
	if url.scheme != "file":
		with _remote:
			yield
		return
	path = Path(url.path).resolve()
	durable_mkdir(path.parent)
	key = str(path) + ".granum-lock"
	with _guard:
		lock = _locks.get(key)
		if lock is None:
			lock = FileLock(key, timeout=60)
			_locks[key] = lock
	with lock:
		yield


@contextmanager
def workspace_lock():
	from granum.core.config import get_config

	with locked(get_config().project_root / ".granum-workspace"):
		yield
