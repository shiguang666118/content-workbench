"""进程级排他锁；关闭文件即释放，阻塞行为与 flock 一致。"""
from __future__ import annotations

import errno
import os
import time

if os.name == "nt":
    import msvcrt
else:
    import fcntl


def lock_exclusive(fd: int, *, blocking: bool = True) -> None:
    if os.name != "nt":
        fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        return
    # locking 从当前位置开始；所有调用者固定锁住第一个字节（允许超过 EOF）。
    position = os.lseek(fd, 0, os.SEEK_CUR)
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        while True:
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                return
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                if not blocking:
                    raise BlockingIOError(exc.errno, exc.strerror) from exc
                # LK_LOCK 自带重试次数上限；显式循环保持 flock 的无限等待语义。
                time.sleep(0.05)
    finally:
        os.lseek(fd, position, os.SEEK_SET)
