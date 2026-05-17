import json
from time import time


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

    def time(self, name):
        ts = time() * 1000000

        event = {
            "ph": "B",
            "cat": "_",
            "name": name,
            "ts": str(ts),
            "pid": 1,
            "tid": 1,
        }
        self.events.append(event)

    def stop(self, name):
        ts = time() * 1000000

        event = {
            "ph": "E",
            "cat": "_",
            "name": name,
            "ts": str(ts),
            "pid": 1,
            "tid": 1,
        }
        self.events.append(event)

    def finish(self):
        self.file.write(json.dumps(self.data))
        self.file.close()
