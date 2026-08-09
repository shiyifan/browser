class ProtectedField:
    """表示layout object中会触发relayout的属性"""

    def __init__(self, which):
        self.value = None
        self.dirty = True
        self.which = which

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

    # 获取值并添加依赖于当前值的其他protected field.
    #
    # "notify": 依赖于当前field的其他protected field
    def read(self, notify):
        if notify:
            self.invalidations.add(notify)
        return self.get()

    # 将另一个protected field赋值给当前field, 并将当前field添加为另一个field的依赖
    def copy(self, field):
        self.set(field.read(notify=self))

    def __repr__(self):
        if isinstance(self.value, list):
            value = f"[...]({len(self.value)})"
        else:
            value = self.value
        return f"ProtectedField(value={value}, dirty={self.dirty}, which={self.which})"
