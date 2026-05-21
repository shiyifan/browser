import json
from time import time
from threading import Lock, get_native_id, enumerate


class MeasureTime:
    """通过在代码中插入测试点，统计函数、方法或者某些过程的耗时"""

    def __init__(self):
        self.file = open("browser.trace", "w")

        self.events = []
        self.data = {"traceEvents": self.events}

        ts = time() * 1000000

        event = {
            "name": "process_name",
            "ph": "M",
            "ts": ts,
            "pid": 1,
            "cat": "__metadata",
            "args": {"name": "Browser"},
        }
        self.events.append(event)

        self.lock = Lock()

    def time(self, name, cat="_", args={}):
        self.lock.acquire(blocking=True)

        ts = time() * 1000000
        tid = get_native_id()

        event = {"ph": "B", "cat": cat, "name": name, "ts": ts, "pid": 1, "tid": tid, "args": args}
        self.events.append(event)

        self.lock.release()

    def stop(self, name, cat="_", args={}):
        self.lock.acquire(blocking=True)

        ts = time() * 1000000
        tid = get_native_id()

        event = {
            "ph": "E",
            "cat": cat,
            "name": name,
            "ts": ts,
            "pid": 1,
            "tid": tid,
            "args": args
        }
        self.events.append(event)

        self.lock.release()

    def instant(self, name, cat="_", args={}, tid=None):
        self.lock.acquire(blocking=True)

        ts = time() * 1000000
        if not tid:
            tid = get_native_id()

        event = {
            "ph": "I",
            "name": name,
            "cat": cat,
            "s": "t",
            "pid": 1,
            "tid": tid,
            "ts": ts,
            "args": args,
        }
        self.events.append(event)

        self.lock.release()

    def finish(self):
        self.lock.acquire(blocking=True)

        for thread in enumerate():
            self.events.append(
                {
                    "ph": "M",
                    "name": "thread_name",
                    "pid": 1,
                    "tid": thread.native_id,
                    "args": {"name": thread.name},
                },
            )

        self.file.write(json.dumps(self.data))
        self.file.close()

        self.lock.release()
