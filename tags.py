# HTML代码中位于标签内外的纯文本
class Text:
    def __init__(self, text, parent):
        self.text = text
        self.children = []
        self.parent = parent

    def __repr__(self):
        return repr(self.text)


# HTML代码中的标签
class Element:
    def __init__(self, tag, attributes, parent):
        self.tag = tag
        self.children = []
        self.attributes = attributes
        self.parent = parent

    def __repr__(self):
        return "<" + self.tag + ">"
