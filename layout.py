import tkinter.font

from tags import Text, Element
from const import *

# 字体缓存
FONTS = {}


# 对应于DOM tree,创建一个用于布局的layout tree。并且DOM tree中每个
# 可绘制的结点对应于layout tree中的结点
# Layout Tree上的结点，对应于每个DOM结点
class BlockLayout:
    def __init__(self, node, parent, previous):
        self.node = node
        self.parent = parent
        self.previous = previous  # previous sibling
        self.children = []

        self.display_list = []

        self.cursor_x = HSTEP
        self.cursor_y = VSTEP

        # 字体的默认值
        self.weight = "normal"
        self.style = "roman"
        self.size = 20

        # 作为buffer,临时保存一行字符，用于计算该行baseline的位置
        # line中的字符仅计算了x轴的绘制坐标，需要根据baseline的位置计算每个字符的y轴坐标
        self.line = []

        # self.recurse(nodes)

        # self.flush()

    def layout(self):
        mode = self.layout_mode()

        if mode == "block":
            previous = None
            for child in self.node.children:
                next = BlockLayout(child, self, previous)
                self.children.append(next)
                previous = next
        else:
            # 计算inline元素的绘制信息，并将信息保存至"display list"中
            self.cursor_x = 0
            self.cursor_y = 0
            self.weight = "normal"
            self.style = "roman"
            self.size = 20
            self.line = []
            self.recurse(self.node)
            self.flush()

        for child in self.children:
            child.layout()

    # 根据当前结点在DOM中对应的结点,创建该结点Layout Tree的子结点
    # def layout_intermediate(self):

    # 根据当前DOM结点以及子结点的类型，确定绘制方式
    def layout_mode(self):
        if isinstance(self.node, Text):
            # 当前DOM结点是纯文本,以inline方式绘制
            return "inline"
        elif any(
            [
                isinstance(child, Element) and child.tag in BLOCK_ELEMENTS
                for child in self.node.children
            ]
        ):
            # 如果DOM结点node的子结点中，至少存在一个是block html element而且是"Element"类型，
            # 那么以block方式绘制该元素
            return "block"
        elif self.node.children:
            # 子结点中没有block html element,则以inline方式绘制
            return "inline"
        else:
            return "block"

    def recurse(self, tree):
        if isinstance(tree, Text):
            for word in tree.text.split():
                self.word(word)
        else:
            self.open_tag(tree.tag)
            for child in tree.children:
                self.recurse(child)
            self.close_tag(tree.tag)

    def open_tag(self, tag):
        if tag == "i":
            self.style = "italic"
        elif tag == "b":
            self.weight = "bold"
        elif tag == "small":
            self.size -= 4
        elif tag == "big":
            self.size += 4
        elif tag == "br":
            self.flush()
        elif tag == "p":
            self.flush()

    def close_tag(self, tag):
        if tag == "i":
            self.style = "roman"
        elif tag == "b":
            self.weight = "normal"
        elif tag == "small":
            self.size += 4
        elif tag == "big":
            self.size -= 4

    def word(self, word):
        font = get_font(self.size, self.weight, self.style)
        w = font.measure(word)

        if self.cursor_x + w > WIDTH - HSTEP:
            # 根据canvas宽度，字符已占满一行，计算该行的baseline位置并更新word的y轴绘制坐标
            self.flush()
        self.line.append((self.cursor_x, word, font))
        self.cursor_x += w + font.measure(" ")

    # 计算一行字符的baseline位置
    def flush(self):
        if not self.line:
            return

        # 根据每个字符的font,计算一行中最大的ascent
        metrics = [font.metrics() for x, word, font in self.line]
        max_ascent = max([metric["ascent"] for metric in metrics])

        # 可以直接以"max_ascent"作为baseline的位置，或者在这个基础上、在最大字符的ascent与descent之外再
        # 添加一些leading（空白区域），ascent上面添加一半leading, descent下面添加一半leading,
        # 这样，lineheight = (ascent + descent) + ascent_leading + descent_leading
        # 这里选择额外添加总共25%的leading,其中ascent上面与descent下面各占一半leading
        baseline = (
            self.cursor_y + 1.25 * max_ascent
        )  # 根据上一行的"cursor_y"坐标计算baseline坐标

        for x, word, font in self.line:
            y = baseline - font.metrics("ascent")
            self.display_list.append((x, y, word, font))

        max_descent = max([metric["descent"] for metric in metrics])
        self.cursor_y = baseline + max_descent * 1.25

        self.cursor_x = HSTEP
        self.line = []


class DocumentLayout:
    def __init__(self, node):
        self.node = node
        self.parent = None
        self.children = []

    def layout(self):
        child = BlockLayout(self.node, self, None)
        self.children.append(child)
        child.layout()
        self.display_list = child.display_list


# 从"FONTS"缓存中获取字体
def get_font(size, weight, style):
    key = (size, weight, style)

    if key not in FONTS:
        font = tkinter.font.Font(family="Times", size=size, weight=weight, slant=style)
        label = tkinter.Label(font=font)
        FONTS[key] = (font, label)

    return FONTS[key][0]
