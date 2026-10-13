"""Exclusive maintenance, versioned backups and recoverable data replacement."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid

from .database_versions import ROOT, database_versions


def check_profile(profile):
    if profile not in ("bbg", "ccb"):
        raise ValueError("请选择 BBG 或 CCB")


def write_json(path, doc):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(doc, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _remove(path, root):
    path, root = Path(path), Path(root).resolve()
    if not path.resolve().is_relative_to(root) or path.resolve() == root or path.is_symlink():
        raise ValueError("维护路径超出数据目录")
    if path.exists():
        shutil.rmtree(path)


def _files(directory):
    result = {}
    for file in sorted(directory.rglob("*")):
        if file.is_symlink():
            raise ValueError("数据目录中存在符号链接，拒绝备份")
        if file.is_file():
            result[file.relative_to(directory).as_posix()] = hashlib.sha256(file.read_bytes()).hexdigest()
    return result


@contextmanager
def data_lock(root=ROOT):
    """OS lock is released on normal exit or process termination."""
    path = Path(root) / "data/.database.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("a+b")
    if path.stat().st_size == 0:
        stream.write(b"0")
        stream.flush()
    stream.seek(0)
    locked = False
    try:
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError as exc:
            raise ValueError("复盘工具或另一采集程序正在运行，请先关闭后重试") from exc
        yield
    finally:
        if locked:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)
        stream.close()


def governors_document(root):
    path = Path(root) / "data/mods/governor_promotions.json"
    if not path.exists():
        return {"schema": 1, "mods": {}}
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc.get("mods"), dict):
        raise ValueError("现有总督数据损坏，拒绝覆盖")
    return doc


def create_backup(profile, root=ROOT, reason="capture"):
    check_profile(profile)
    root = Path(root)
    document = governors_document(root)
    directory = root / "data/backups" / profile
    identity = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    pending = directory / (".pending-" + identity)
    destination = directory / identity
    source = root / "data/gamedb" / profile
    pending.mkdir(parents=True)
    try:
        if source.exists():
            _files(source)
            shutil.copytree(source, pending / "profile")
        write_json(pending / "governors.json", {"present": profile in document["mods"],
                                               "section": document["mods"].get(profile)})
        write_json(pending / "backup.json", {
            "format": 1, "profile": profile, "id": identity, "reason": reason,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "versions": database_versions(profile, root), "profilePresent": source.exists(),
            "files": _files(pending)})
        os.replace(pending, destination)
        return destination
    except BaseException:
        _remove(pending, root / "data")
        raise


def backup_path(profile, identity, root=ROOT):
    check_profile(profile)
    parent = (Path(root) / "data/backups" / profile).resolve()
    path = parent / identity
    if path.resolve().parent != parent or path.is_symlink() or identity.startswith("."):
        raise ValueError("无效的备份编号")
    return path


def validate_backup(path, profile):
    doc = json.loads((path / "backup.json").read_text(encoding="utf-8"))
    if doc.get("format") != 1 or doc.get("profile") != profile or doc.get("id") != path.name:
        raise ValueError("备份规则集或编号不一致")
    files = _files(path)
    files.pop("backup.json", None)
    if files != doc.get("files"):
        raise ValueError("备份完整性校验失败，无法回档")
    if bool(doc.get("profilePresent")) != (path / "profile").is_dir():
        raise ValueError("备份数据库目录缺失")
    governor = json.loads((path / "governors.json").read_text(encoding="utf-8"))
    if governor.get("present") and not isinstance(governor.get("section"), dict):
        raise ValueError("备份总督数据损坏")
    return doc


def list_backups(profile, root=ROOT):
    check_profile(profile)
    result = []
    directory = Path(root) / "data/backups" / profile
    for path in sorted(directory.glob("*"), reverse=True):
        if not path.is_dir() or path.name.startswith("."):
            continue
        try:
            doc = json.loads((path / "backup.json").read_text(encoding="utf-8"))
            if doc.get("profile") == profile:
                result.append(doc)
        except (OSError, ValueError):
            continue
    return result


def recover(root=ROOT):
    root = Path(root)
    transaction = root / "data/.database-transaction"
    journal = transaction / "journal.json"
    if not journal.exists():
        if transaction.exists():
            _remove(transaction, root / "data")
        return False
    doc = json.loads(journal.read_text(encoding="utf-8"))
    profile = doc["profile"]
    check_profile(profile)
    if doc.get("committed"):
        _remove(transaction, root / "data")
        return False
    backup = backup_path(profile, doc["backup"], root)
    manifest = validate_backup(backup, profile)
    destination = root / "data/gamedb" / profile
    # Recovery can be retried if interrupted again.
    if manifest["profilePresent"]:
        restored = transaction / "recovered-profile"
        _remove(restored, root / "data")
        shutil.copytree(backup / "profile", restored)
        _remove(destination, root / "data")
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(restored, destination)
    else:
        _remove(destination, root / "data")
    governor_path = root / "data/mods/governor_promotions.json"
    if doc["governorsPresent"]:
        temporary = governor_path.with_suffix(".recovery")
        shutil.copyfile(transaction / "old-governors.json", temporary)
        os.replace(temporary, governor_path)
    else:
        governor_path.unlink(missing_ok=True)
    _remove(transaction, root / "data")
    return True


def replace_data(profile, staged, governor, backup, root=ROOT, *, present=True):
    """Caller holds data_lock; backup precedes any modification of active data."""
    check_profile(profile)
    root = Path(root)
    transaction = root / "data/.database-transaction"
    if transaction.exists():
        raise ValueError("存在未恢复的维护事务")
    validate_backup(backup, profile)
    transaction.mkdir()
    old_governor = root / "data/mods/governor_promotions.json"
    journal = {"profile": profile, "backup": backup.name,
               "governorsPresent": old_governor.exists(), "committed": False}
    try:
        if present:
            shutil.copytree(staged, transaction / "new-profile")
        document = governors_document(root)
        if governor["present"]:
            document["mods"][profile] = governor["section"]
        else:
            document["mods"].pop(profile, None)
        write_json(transaction / "new-governors.json", document)
        if old_governor.exists():
            shutil.copyfile(old_governor, transaction / "old-governors.json")
        write_json(transaction / "journal.json", journal)
        destination = root / "data/gamedb" / profile
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            os.replace(destination, transaction / "old-profile")
        if present:
            os.replace(transaction / "new-profile", destination)
        old_governor.parent.mkdir(parents=True, exist_ok=True)
        os.replace(transaction / "new-governors.json", old_governor)
        journal["committed"] = True
        write_json(transaction / "journal.json", journal)
    except BaseException:
        recover(root)
        raise
    _remove(transaction, root / "data")


def restore(profile, identity, root=ROOT):
    path = backup_path(profile, identity, root)
    doc = validate_backup(path, profile)
    before = create_backup(profile, root, "before-restore")
    governor = json.loads((path / "governors.json").read_text(encoding="utf-8"))
    replace_data(profile, path / "profile", governor, before, root, present=doc["profilePresent"])
    return doc


def delete_backup(profile, identity, root=ROOT):
    path = backup_path(profile, identity, root)
    validate_backup(path, profile)
    _remove(path, Path(root) / "data/backups" / profile)
