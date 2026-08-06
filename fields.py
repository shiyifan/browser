class ProtectedField:
    """表示layout object中会触发relayout的属性"""

    def __init__(self):
        self.value = None
        self.dirty = True

        self.invalidations = set()  # 所有依赖于当前属性的属性

    # 该值需要更新，不能继续重用
    def mark(self):
        if self.dirty:
            return
        self.dirty = True

    def get(self):
        assert not self.dirty
        return self.value

    def set(self, value):
        self.value = value
        self.dirty = False

        self.notify()

    def notify(self):
        for field in self.invalidations:
            field.mark()

    def read(self, notify):
        self.invalidations.add(notify)
        return self.get()

    def copy(self, field):
        self.set(field.read(notify=self))
