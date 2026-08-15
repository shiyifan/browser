from fields import ProtectedField
import const


# HTML代码中位于标签内外的纯文本
class Text:
    def __init__(self, text, parent):
        self.text = text
        self.children = []  # 文本结点没有子结点，这里仅为了与"Element"统一
        self.parent = parent
        self.animations = {}  # 保存结点的animations、transitions

        # 是否获取到焦点.纯文本DOM结点无法获取焦点,该值始终为"False"
        self.is_focused = False

        # 在layout tree中对应的layout object, 但对于"Text"node而言,由于无法获取
        # 焦点，因此这个值始终为"None"
        self.layout_object = None

        self.style = None

    def __repr__(self):
        return f"#text({repr(self.text)})"


# HTML代码中的标签
class Element:
    def __init__(self, tag, attributes, parent):
        self.tag = tag
        self.children = []
        self.attributes = attributes  # HTML标签中声明的属性，例如<input tyle="text">中的"type"属性
        self.parent = parent
        self.is_focused = False  # 是否获取到焦点
        self.animations = {}  # 保存结点的animations、transitions

        # 在layout tree中对应的layout object, 不过有的DOM node在layout tree中没有对应的layout object,
        # 例如在"inline"layout方式的BlockLayout中的DOM node. 不过"<input>"与"<button>"会单独创建"InputLayout",
        # 所以这两者有对应的layout object.
        self.layout_object = None

        # style是一个map, key是css属性名称，value是ProtectedField:
        # { <css property name>: ProtectedField }
        self.style = None

    def __repr__(self):
        return "<" + self.tag + ">"
