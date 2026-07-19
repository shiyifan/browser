from tags import Text, Element
from utils import is_focusable, absolute_bounds_for_obj
from skia import Rect


# a11y(accessibility) tree结构中的结点
class AccessibilityNode:
    def __init__(self, node, parent=None):
        self.node = node
        self.children = []
        self.text = ""
        self.parent = parent

        self.bounds = self.compute_bounds()

        if isinstance(node, Text):
            if is_focusable(node.parent):
                self.role = "focusable text"
            else:
                self.role = "StaticText"
        else:
            if "role" in node.attributes:
                self.role = node.attributes["role"]
                return

            match node.tag:
                case "a":
                    self.role = "link"
                    return
                case "input":
                    self.role = "textbox"
                    return
                case "button":
                    self.role = "button"
                    return
                case "img":
                    self.role = "image"
                    return
                case "html":
                    self.role = "document"
                    return
                case "iframe":
                    self.role = "iframe"
                    return

            if is_focusable(node):
                self.role = "focusable"
            else:
                self.role = "none"

    # 构建当前DOM结点"self.node"的Accessibility Tree
    def build(self):
        for child_node in self.node.children:
            self.build_internal(child_node)

        match self.role:
            case "StaticText":
                self.text = repr(self.node.text)
            case "focusable text":
                self.text = f"Focusable text: {self.node.text}"
            case "focusable":
                self.text = "Focusable element"
            case "textbox":
                if "value" in self.node.attributes:
                    value = self.node.attributes["value"]
                elif (
                    self.node.tag != "input"
                    and self.node.children
                    and isinstance(self.node.children[0], Text)
                ):
                    value = self.node.children[0].text
                else:
                    value = ""
                self.text = f"Input box: {value}"
            case "button":
                self.text = "Button"
            case "image":
                if "alt" in self.node.attributes:
                    self.text = f"Image: {self.node.attributes['alt']}"
                else:
                    self.text = "Image"
            case "link":
                self.text = "Link"
            case "alert":
                self.text = "Alert"
            case "document":
                self.text = "Document"

        if self.node.is_focused:
            self.text = f"{self.text} is focused"

        # if self.role == "StaticText":
        #     self.text = repr(self.node.text)
        # elif self.role == "focusable text":
        #     self.text = f"Focusable text: {self.node.text}"
        # elif self.role == "focusable":

    # 根据DOM结点下的DOM Tree结构构建a11y tree. 对于非a11y的DOM结点将不创建对应的a11y tree node.
    # 如下图所示：
    #
    #        DOM Tree                                    Accessibility Tree
    #
    #    html (role=document)                              document
    #     |                                                  |
    #     +->div 1                                           +->textbox  2
    #     |   |                                              |
    #     |   +-->input  (role=textbox) 2                    +->button   3
    #     |   |                                              |
    #     |   +-->button (role=button)  3     ------>        |
    #     |                                                  +->focusable(div tabindex=1)  4
    #     |                                                        |
    #     +->div [tabindex=1]  4                                   +->link      5
    #         |                                                    |
    #         +-->a     (role=link)      5                         +->textbox   6
    #         |
    #         +-->input (role=textbox)   6
    #
    def build_internal(self, child_node):
        if (
            isinstance(child_node, Element)
            and child_node.tag == "iframe"
            and child_node.frame
            and child_node.frame.loaded
        ):
            # 如果遇到"<iframe>", 那么直接对'<iframe>'内的DOM tree的root node创建
            # a11y node, 将每个'<iframe>'的a11y tree合并至root frame的tree中.
            child = FrameAccessibilityNode(child_node, self)
        else:
            child = AccessibilityNode(child_node, self)

        if child.role != "none":
            self.children.append(child)
            child.build()
        else:
            # child不是a11y的结点,不创建这个node而继续检查这个child下一级的children,
            # 下一级的children中如果有a11y的结点则添加至当前a11y node的children中，而非child的children中
            for grandchild_node in child_node.children:
                self.build_internal(grandchild_node)

    def compute_bounds(self):
        if self.node.layout_object:
            return [absolute_bounds_for_obj(self.node.layout_object)]

        # 对于DOM Tree中的"Text"node以及位于"inline"layout方式的BlockLayout中的inline html element(除了<input>与<button>外),
        # 它们在layout tree中没有对应的结点，因此需要根据这些结点的父结点计算a11y node的矩形区域.

        if isinstance(self.node, Text):
            # "Text" DOM node无法获取焦点，因此不计算其矩形区域
            return []

        bounds = []

        # 寻找这个inline DOM node的parent,直到这个parent在layout tree中有对应的layout object
        inline = self.node.parent
        while not inline.layout_object:
            inline = inline.parent

        # 根据"BlockLayout.layout_mode()"的实现, 找到的这个parent一定是"inline"layout的.
        # 因此该layout object的chilren将是"LineLayout"
        for line in inline.layout_object.children:
            line_bounds = Rect.MakeEmpty()
            for child in line.children:
                if child.node.parent == self.node:
                    line_bounds.join(Rect.MakeXYWH(child.x, child.y, child.width, child.height))
            bounds.append(line_bounds)

        return bounds

    def hit_test(self, x, y):
        node = None
        if self.contains_point(x, y):
            node = self
        for child in self.children:
            res = child.hit_test(x, y)  # 递归进入子结点, 进一步判断点击位置位于更具体的哪个子结点中
            if res:
                node = res
        return node

    def contains_point(self, x, y):
        for bound in self.bounds:
            if bound.contains(x, y):
                return True
        return False

    def absolute_bounds(self):
        abs_bounds = []
        for bound in self.bounds:
            abs_bound = bound.makeOffset(0.0, 0.0)
            if isinstance(self, FrameAccessibilityNode):
                obj = self.parent
            else:
                obj = self

            while obj:
                obj.map_to_parent(abs_bound)
                obj = obj.parent
            abs_bounds.append(abs_bound)
        return abs_bound

    def map_to_parent(self, rect):
        # "大部分的a11y node不需要转换矩形区域坐标"
        pass

    def __repr__(self):
        return f"role={self.role}, text={self.text}"


# 表示"<iframe>"的a11y node
class FrameAccessibilityNode(AccessibilityNode):
    # node: <iframe> DOM node
    def __init__(self, node, parent=None):
        super().__init__(node, parent)
        self.scroll = self.node.frame.scroll
        self.zoom = self.node.layout_object.zoom

    def hit_test(self, x, y):
        bounds = self.bounds[0]
        if not bounds.contains(x, y):
            return

        new_x = x - bounds.left() - dpx(1, self.zoom)
        new_y = y - bounds.top() - dpx(1, self.zoom) + self.scroll
        node = self

        for child in self.children:
            res = child.hit_test(new_x, new_y)
            if res:
                node = res

        return node

    def map_to_parent(self, rect):
        bounds = self.bounds[0]
        rect.offset(bounds.left(), bounds.top() - self.scroll)
        rect.intersect(bounds)
