# HTML代码中位于标签内外的纯文本
class Text:
    def __init__(self, text, parent):
        self.text = text
        self.children = []
        self.parent = parent

        # 是否获取到焦点.纯文本DOM结点无法获取焦点,该值始终为"False"
        self.is_focused = False

    def __repr__(self):
        return repr(self.text)


# HTML代码中的标签
class Element:
    def __init__(self, tag, attributes, parent):
        self.tag = tag
        self.children = []
        self.attributes = attributes
        self.parent = parent
        self.is_focused = False  # 是否获取到焦点

    def __repr__(self):
        return "<" + self.tag + ">"
