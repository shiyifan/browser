from utils import text_digest, log


class ProtectedField:
    """表示layout object中会触发relayout的属性"""

    def __init__(self, which, name):
        self.value = None
        self.dirty = True
        self.which = which
        self.name = name

        self.invalidations = set()  # 所有依赖于当前属性的属性

        self.inited = None  # 是否已被第一次赋值, 仅作调试

    # 该值需要更新，不能继续重用
    def mark(self):
        if self.dirty:
            return
        self.dirty = True

    def get(self):
        assert not self.dirty
        return self.value

    def set(self, value):
        if self.inited is None:
            self.inited = False
        elif self.inited == False:
            self.inited = True

        updated = value != self.value

        old = self.value
        new = value

        self.value = value
        self.dirty = False

        # 仅在属性值更新时通知dependencies更新
        if updated:

            if self.inited:
                log.w(f"Changed, old: {self}, new: {new}")

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
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                value = round(value, 2)

        dirty = "dirty!" if self.dirty else ""

        msg = ""
        which_cls = self.which.__class__.__name__
        match which_cls:
            case "Element":
                msg = f"<{self.which.tag}>"
            case "Text":
                msg = f"<#text {text_digest(self.which.text)}>"

            case "BlockLayout" | "LineLayout" | "IframeLayout" | "InputLayout" | "ImageLayout":
                node = self.which.node
                node_cls = node.__class__.__name__
                if node_cls == "Element":
                    msg = f"<{node.tag}>"
                elif node_cls == "Text":
                    msg = f"<#text {text_digest(node)}>"

            case "TextLayout":
                msg = f"<{self.which.word!r}>"

        return f"PField({msg}, {which_cls}.{self.name}: {value!r}, {dirty})"
