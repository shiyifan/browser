from font import *
from tags import Text, Element
from commands import DrawText, DrawRect
import const
from rect import Rect


# 对应于DOM tree node, 该类表示用于布局的layout tree中的节点。
# DOM tree中大部分可绘制的节点(block html element或者inline html element)对应于layout tree中的节点。
# layout过程中为DOM节点计算屏幕所在坐标、宽高、以及要绘制内容，并将要绘制的
# 内容保存在"display list"中等待下一步实际的渲染流程
#
# 子结点左上角的x、y坐标以及宽度继承自父结点，仅包含inline元素和text的子结点的高度由字体决定
# 父结点的高度是所有子结点的高度之和
class BlockLayout:
    def __init__(self, node, parent, previous):
        self.node = node  # DOM结点
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
            # 以"block"方式绘制

            previous = None
            for child in self.node.children:
                next = BlockLayout(child, self, previous)
                self.children.append(next)
                previous = next
        else:
            # 计算inline元素的绘制信息，并创建LineLayout以及TextLayout作为当前BlockLayout的子节点.
            # 由LineLayout以及TextLayout负责绘制与计算

            self.new_line()
            self.recurse(self.node)

        for child in self.children:
            child.layout()
        # block html element的高度等于所有子结点的高度之和
        # 在所有子结点计算得到height之后再计算当前结点的高度
        self.height = sum([child.height for child in self.children])

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

    def recurse(self, node):
        if isinstance(node, Text):
            for word in node.text.split():
                self.word(node, word)
        else:
            if node.tag == "br":
                self.new_line()
            for child in node.children:
                self.recurse(child)

    # 对以"inline"方式绘制的DOM节点在layout tree上创建LineLayout与TextLayout节点。
    # 计算每个word的宽度，并根据宽度判断是否超出一行。
    # 这里仅用于创建layout tree结构，计算baseline、确定行高的流程由LineLayout负责完成
    def word(self, node, word):
        weight = node.style["font-weight"]
        style = node.style["font-style"]
        color = node.style["color"]
        if style == "normal":
            style = "roman"

        # 将字体大小的"px"单位转换为"pt"单位
        size = int(float(node.style["font-size"][:-2]) * 0.75)

        font = get_font(size, weight, style)
        w = font.measure(word)

        if self.cursor_x + w > self.width:
            # 根据BlockLayout宽度，已超出一行时，新建一行
            self.new_line()
        self.cursor_x += w + font.measure(" ")

        # 将未超出一行的word添加至当前行中
        line = self.children[-1]
        previous_word = line.children[-1] if line.children else None
        text = TextLayout(node, word, line, previous_word)
        line.children.append(text)

    def new_line(self):
        self.cursor_x = 0
        last_line = self.children[-1] if self.children else None
        new_line = LineLayout(self.node, self, last_line)
        self.children.append(new_line)

    def paint(self):
        cmds = []

        # 绘制当前layout对象的背景色
        # 创建layout tree时，如果某个Block Element下仅有inline element,那么
        # 由block element对应的block layout负责绘制inline element的text,
        # 而且这个block layout的children为空。这样，如果inline element有背景色，
        # 则无法由block layout绘制出来
        #
        # 目前背景色仅能由DOM节点本身对应的layout tree节点绘制
        bgcolor = self.node.style.get("background-color", "transparent")
        if bgcolor != "transparent":
            rect = DrawRect(self.self_rect(), bgcolor)
            cmds.append(rect)

        return cmds

    def self_rect(self):
        return Rect(self.x, self.y, self.x + self.width, self.y + self.height)


# 对应于DOM根结点的layout object。
# 负责根据viewport大小定义根元素的绘制坐标
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


# 表示以"inline"方式绘制的BlockLayout中的每一行text
# 如下所示
#
# BlockLayout(inline)
#      |
#      +------> LineLayout
#      |            |
#      |            +------> TextLayout
#      |            |
#      |            +------> TextLayout
#      |            |
#      |            +------> TextLayout
#      |
#      +------> LineLayout
#                   |
#                   +------> TextLayout
#                   |
#                   +------> TextLayout
class LineLayout:
    def __init__(self, node, parent, previous):
        # 与layout tree中父节点的node相同，即以"inline"方式绘制的DOM节点
        self.node = node

        self.parent = parent
        self.previous = previous  # 上一行
        self.children = []

    # 计算baseline位置、确定行高
    def layout(self):
        self.width = self.parent.width
        self.x = self.parent.x

        if self.previous:
            self.y = self.previous.y + self.previous.height
        else:
            self.y = self.parent.y

        if not self.children:
            # 如果LineLayout没有TextLayout子节点，那么高度为0
            self.height = 0
            return

        # 让每个TextLayout自己计算x绘制坐标、宽度、高度以及字体
        for word in self.children:
            word.layout()

        # 行内的所有TextLayout均以计算完成，然后确定baseline的位置以及每个TextLayout的y绘制坐标

        # 计算一行中最大的ascent
        max_ascent = max([word.font.metrics("ascent") for word in self.children])

        # 可以直接以"max_ascent"作为baseline的位置，或者在这个基础上、在最大字符的ascent与descent之外再
        # 添加一些leading（空白区域），ascent上面添加一半leading, descent下面添加一半leading,
        # 这样，lineheight = (ascent + descent) + ascent_leading + descent_leading
        # 这里在最大ascent上面与最大descent下面各添加25%的leading
        baseline = self.y + max_ascent * 1.25

        # 确定y绘制坐标
        for word in self.children:
            word.y = baseline - word.font.metrics("ascent")

        max_descent = max([word.font.metrics("descent") for word in self.children])
        self.height = 1.25 * (max_ascent + max_descent)

    def paint(self):
        # 由TextLayout负责绘制字符
        return []


# 表示LineLayout中的每一个word
class TextLayout:
    def __init__(self, node, word, parent, previous):
        self.node = node  # 与所在的LineLayout的node相同
        self.word = word
        self.parent = parent
        self.previous = previous  # 上一个word
        self.children = []

    def layout(self):
        weight = self.node.style["font-weight"]
        style = self.node.style["font-style"]
        if style == "normal":
            style = "roman"
        size = int(float(self.node.style["font-size"][:-2]) * 0.75)
        self.font = get_font(size, weight, style)

        self.width = self.font.measure(self.word)
        if self.previous:
            space = self.previous.font.measure(" ")
            self.x = self.previous.x + self.previous.width + space
        else:
            self.x = self.parent.x
        self.height = self.font.metrics("linespace")

    def paint(self):
        color = self.node.style["color"]
        return [DrawText(self.x, self.y, self.word, self.font, color)]
