import tkinter.font

from tags import Text, Element
import const

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

        # 该layout相对于canvas左上角的绝对坐标
        self.x = None
        self.y = None

        self.width = None
        self.height = None

        # layout内的子结点相对于layout左上角的相对坐标
        # 所以子结点的绝对坐标等于"self.x + self.cursor_x"
        self.cursor_x = None
        self.cursor_y = None

        self.display_list = []

        # 字体的默认值
        self.weight = None
        self.style = None
        self.size = None

        # 作为buffer,临时保存一行字符，用于计算该行baseline的位置
        # line中的字符仅计算了x轴的绘制坐标，需要根据baseline的位置计算每个字符的y轴坐标
        self.line = []

    # 根据绘制方式创建layout tree
    def layout(self):
        # 根据layout tree中的父结点以及previous计算当前结点的x坐标、y坐标以及宽度width
        self.x = self.parent.x
        self.width = self.parent.width
        if self.previous:
            self.y = self.previous.y + self.previous.height
        else:
            self.y = self.parent.y

        mode = self.layout_mode()
        if mode == "block":
            previous = None
            for child in self.node.children:
                next = BlockLayout(child, self, previous)
                self.children.append(next)
                previous = next

            for child in self.children:
                child.layout()

            # block html element的高度等于所有子结点的高度之和
            # 在所有子结点计算得到height之后再计算当前结点的高度
            self.height = sum([child.height for child in self.children])
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
            self.height = self.cursor_y  # inline html element的高度等于文本的高度

    # 根据当前DOM结点以及所包含子结点的类型，确定当前节点的绘制方式
    #
    # 目前DOM树中仅有两种节点类型：Text与Element，Text表示纯文本节点，Element表示除纯文本外其他的HTML tag结点
    # Text节点无子节点，Element的子结点既可以是Text,也可以是Element
    def layout_mode(self):
        if isinstance(self.node, Text):
            # DOM tree中，Text结点作为叶子结点，所以计算该结点的display list
            return "inline"
        elif any(
            [
                isinstance(child, Element) and child.tag in const.BLOCK_ELEMENTS
                for child in self.node.children
            ]
        ):
            # DOM tree中，如果Element结点的子结点中，至少有一个是block Html Element，
            # 那么在layout tree中，该结点作为非叶子结点，不计算display list,仅将子结点添加至"children"数组中
            return "block"
        elif self.node.children:
            # 在layout tree中，该结点的子结点中只有inline Html Element,那么将该结点视为叶子结点，
            # 并计算结点的display list
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

        if self.cursor_x + w > self.width:
            # 根据BlockLayout宽度，字符已占满一行，计算该行的baseline位置并更新word的y轴绘制坐标
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

        for rel_x, word, font in self.line:
            x = self.x + rel_x
            y = self.y + baseline - font.metrics("ascent")
            self.display_list.append((x, y, word, font))

        max_descent = max([metric["descent"] for metric in metrics])
        self.cursor_y = baseline + max_descent * 1.25

        self.cursor_x = 0
        self.line = []

    def paint(self):
        return self.display_list


class DocumentLayout:
    def __init__(self, node):
        self.node = node
        self.parent = None
        self.children = []

        self.x = None
        self.y = None
        self.width = None
        self.height = None

    def layout(self):
        self.width = const.WIDTH - 2 * const.HSTEP
        self.x = const.HSTEP
        self.y = const.VSTEP

        child = BlockLayout(self.node, self, None)
        self.children.append(child)
        child.layout()
        self.height = child.height

    def paint(self):
        return []


# 从"FONTS"缓存中获取字体
def get_font(size, weight, style):
    key = (size, weight, style)

    if key not in FONTS:
        font = tkinter.font.Font(family="Times", size=size, weight=weight, slant=style)
        label = tkinter.Label(font=font)
        FONTS[key] = (font, label)

    return FONTS[key][0]
