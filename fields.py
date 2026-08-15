from utils import text_digest, log


class ProtectedField:
    """表示layout object中会触发relayout的属性"""

    def __init__(self, which, name, parent=None, dependencies=None):
        """ "dependencies": 表示当前field所依赖的其他protected field"""

        self.value = None
        self.which = which
        self.name = name

        # 该属性值是否已过期并需要更新.
        #
        # 注意：这仅表示当前属性值是否过期，而不代表其他object的属性值. 例如当表示layout object的"children"类型的属性时，
        # 如果"dirty = True"，则仅表示"children"该属性需要更新，需要重新根据DOM node创建layout子结点，不表示"'children'
        # 中某个子结点需要更新". 而layout类中的"has_dirty_descendants"负责表示"子结点需要更新"
        self.dirty = True

        self.invalidations = set()  # 所有依赖于当前field的protected field

        self.already_inited = None  # 是否已被第一次赋值, 仅作调试

        # 如果当前对象作为layout object的protected属性, 那么表示layout object在layout tree中的parent.
        # 如果不是的话，那么该属性值为None
        self.parent = parent

        self.frozen_dependencies = dependencies is not None
        if dependencies is not None:
            for dependency in dependencies:
                dependency.invalidations.add(self)

    # 该值需要更新，不能继续重用. 此时先不notify dependencies
    def mark(self):
        if self.dirty:
            return
        self.dirty = True

        self.set_ancestor_dirty_flags()

    # 在layout tree中,将当前属性所在的layout object的所有ancestor layout object均置为“某一子结点需要重新'layout'”的状态
    def set_ancestor_dirty_flags(self):
        parent = self.parent
        while parent and not parent.has_dirty_descendants:
            parent.has_dirty_descendants = True
            parent = parent.parent

    def get(self):
        assert not self.dirty
        return self.value

    def set(self, value):
        if self.already_inited is None:
            # 第一次赋值
            self.already_inited = False
        elif self.already_inited == False:
            # 第二次赋值。在此之后便可以打印"Changed"日志了
            self.already_inited = True

        updated = value != self.value

        self.value = value
        self.dirty = False

        # 仅在属性值更新时通知dependencies更新
        if updated:

            if self.already_inited:
                log.w(f"Changed: {self}")

            self.notify()

    def notify(self):
        for field in self.invalidations:
            field.mark()

    # 获取值并添加依赖于当前值的其他protected field.
    #
    # "notify": 依赖于当前field的其他protected field
    def read(self, notify):
        if notify:
            if notify.frozen_dependencies:
                # 如果"notify"在创建时已显式传入了dependencies,那么不再将notify添加为当前的invalidation.
                assert notify in self.invalidations
            else:
                self.invalidations.add(notify)
        return self.get()

    # 将另一个protected field赋值给当前field, 并将当前field添加为另一个field的依赖
    def copy(self, field):
        self.set(field.read(notify=self))

    def set_dependencies(self, dependencies):
        for dep in dependencies:
            dep.invalidations.add(self)
        self.frozen_dependencies = True

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
