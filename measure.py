import json
from time import time
from threading import Lock, get_ident, enumerate


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
            "ts": str(ts),
            "pid": 1,
            "cat": "__metadata",
            "args": {"name": "Browser"},
        }
        self.events.append(event)

        self.lock = Lock()

    def time(self, name):
        self.lock.acquire(blocking=True)

        ts = time() * 1000000
        tid = get_ident()

        event = {
            "ph": "B",
            "cat": "_",
            "name": name,
            "ts": str(ts),
            "pid": 1,
            "tid": str(tid),
        }
        self.events.append(event)

        self.lock.release()

    def stop(self, name):
        self.lock.acquire(blocking=True)

        ts = time() * 1000000
        tid = get_ident()

        event = {
            "ph": "E",
            "cat": "_",
            "name": name,
            "ts": str(ts),
            "pid": 1,
            "tid": str(tid),
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
                    "tid": str(thread.ident),
                    "args": {"name": thread.name},
                }
            )

        self.file.write(json.dumps(self.data))
        self.file.close()

        self.lock.release()
