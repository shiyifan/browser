from font import *
from tags import Text, Element
from commands import *
import const
from utils import parse_transform, dpx

# <input>的固定宽度
INPUT_WIDTH_PX = 200


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

        node.layout_object = self

    # 根据绘制方式创建layout tree
    def layout(self):
        self.zoom = self.parent.zoom

        # 根据layout tree中的父结点以及previous计算当前结点的x坐标、y坐标以及宽度width.
        self.x = self.parent.x  # 子结点的绘制起始点的x坐标继承自父结点的x坐标
        self.width = self.parent.width
        # 子结点绘制起始点的y坐标继承自父结点的y坐标（如果当前结点是父结点的第一个子结点）,或者上一个兄弟结点的"y坐标 + 兄弟结点的高度"
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

        # block html element的高度等于所有子结点的高度之和.
        # 在所有子结点计算得到height之后再计算当前结点的高度
        self.height = sum([child.height for child in self.children])

    # 根据当前DOM结点以及所包含子结点的类型，确定当前节点的绘制方式
    #
    # 目前DOM树中仅有两种节点类型：Text与Element，Text表示纯文本节点，Element表示除纯文本外其他的HTML tag结点
    # Text节点无子节点，Element的子结点既可以是Text,也可以是Element
    def layout_mode(self):
        if isinstance(self.node, Text):
            # DOM tree中，Text结点作为纯文本结点，在layout tree上创建结点的绘制信息(TextLayout, LineLayout)
            return "inline"
        elif any(
            [
                isinstance(child, Element) and child.tag in const.BLOCK_ELEMENTS
                for child in self.node.children
            ]
        ):
            # DOM tree中，如果Element结点的子结点中，至少有一个是block Html Element，
            # 那么在layout tree中，该结点作为非叶子结点，不计算绘制信息,仅将子结点添加至"children"数组中
            return "block"
        elif self.node.children or self.node.tag in ["input", "img"]:
            # 在DOM tree中，该结点的子结点中只有inline Html Element,那么将该结点视为纯文本结点，
            # 在layout tree中，所有子结点的文本绘制信息（TextLayout, LineLayout）由当前结点负责创建
            return "inline"
        else:
            return "block"

    # 递归地访问以"inline"方式layout的DOM结点, 根据结点中的Text以及其他结点创建TextLayout或者InputLayout.
    # 由于递归调用，这里的"node"参数可能与"self.node"不同
    def recurse(self, node):
        if isinstance(node, Text):
            # FIXME: 下面仅简单地通过"text.split()"分词, 但无法正确对CJK字符分词.
            for word in node.text.split():
                self.word(node, word)
        else:
            if node.tag == "br":
                self.new_line()
            elif node.tag == "input" or node.tag == "button":
                # 注意，这里创建的"InputLayout"对象中的"InputLayout.node"属性
                # 是"<input>"或者"<button>"结点,而不是结点下的"Text"结点.
                self.input(node)
            elif node.tag == "img":
                self.image(node)
            else:
                # 与"<input>"或者"<button>"不同，对于"<a>"这样的DOM结点，没有为其创建专用的Layout,
                # 而采用"TextLayout", 因此"TextLayout"中的"TextLayout.node"值为DOM结点下的"Text"结点
                for child in node.children:
                    self.recurse(child)

    # 对以"inline"方式绘制的DOM节点在layout tree上创建LineLayout与TextLayout节点。
    # 计算每个word的宽度，并根据宽度判断是否超出一行。
    # 这里仅用于创建layout tree结构，而计算baseline、确定行高的流程由LineLayout负责完成
    def word(self, node, word):
        node_font = font(node.style, self.zoom)
        w = node_font.measureText(word)
        self.add_inline_child(node, w, TextLayout, word)

    # 与"word()"方法相似，将<input>和<button>以与纯文本相似的方式添加至LineLayout中
    def input(self, node):
        w = dpx(INPUT_WIDTH_PX, self.zoom)  # "<input>"布局时采用固定宽度
        self.add_inline_child(node, w, InputLayout)

    # 将<img>添加至LineLayout中
    def image(self, node):
        if "width" in node.attributes:
            # 如果以"<img width=''>"的方式指定了宽度
            w = dpx(int(node.attributes["width"]), self.zoom)
        else:
            w = dpx(node.image.width(), self.zoom)  # 默认情况下，"<img>"布局时采用图片原始宽度

        self.add_inline_child(node, w, ImageLayout)

    # 添加inline layout object至LineLayout中
    def add_inline_child(self, node, w, child_class, word=None):
        if self.cursor_x + w > self.width:
            # 根据BlockLayout宽度，已超出一行时，新建一行
            self.new_line()

        line = self.children[-1]
        previous_word = line.children[-1] if line.children else None
        if word:
            # 此时添加的是"TextLayout"
            child = child_class(node, word, line, previous_word)
        else:
            child = child_class(node, line, previous_word)
        line.children.append(child)

        # 更新x坐标，作为同一line中下一个inline element的布局x坐标
        self.cursor_x += w + font(node.style, self.zoom).measureText(" ")

    def new_line(self):
        self.cursor_x = 0
        last_line = self.children[-1] if self.children else None
        new_line = LineLayout(self.node, self, last_line)
        self.children.append(new_line)

    def paint(self):
        """根据已计算的坐标, 创建当前layout对象的绘制命令. 注意:不创建layout的children的绘制命令"""

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
            radius = float(self.node.style.get("border-radius", "0px")[:-2])
            cmds.append(DrawRRect(self.self_rect(), radius, bgcolor))

        return cmds

    def paint_effects(self, cmds):
        """
        绘制css visual effect, 例如opacity等. 注意: 应用在当前layout对象的effect同样也会应用在
        children上

        cmds: 当前layout对象与children的绘制命令
        """

        cmds = paint_visual_effects(self.node, cmds, self.self_rect())
        if "tabindex" in self.node.attributes:
            # 如果html element有"tabindex"属性，那么该element也可以获得焦点并绘制该焦点.
            paint_outline(self.node, cmds, self.self_rect(), self.zoom)
        return cmds

    def self_rect(self):
        return Rect(self.x, self.y, self.x + self.width, self.y + self.height)

    # 避免由<button>创建的BlockLayout重复绘制
    #
    # 在这种情况下:
    #
    #    <body>
    #       hello
    #       <p></p>
    #       <button>Click</button>
    #    </body>
    #
    # 在layout tree中，由于"<p>"这个block html element作为<body>的子结点之一，
    # <p>, "hello"以及"<button>"都将作为BlockLayout结点。对于<button>的BlockLayout而言，
    # layout tree中的结构如下：
    #
    #   ...
    #     BlockLayout (self.node == <button>)
    #         LineLayout
    #             InputLayout (self.node == <button>)
    #   ...
    #
    # 调用"paint_tree()"绘制时，由于BlockLayout与InputLayout都将绘制<button>的背景色，因此为避免重复绘制，BlockLayout
    # 不再绘制背景色，由InputLayout绘制
    def should_paint(self):
        return isinstance(self.node, Text) or (self.node.tag not in ["input", "button", "img"])


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

        node.layout_object = self

    # 对整个HTML文档内容布局
    #
    # 布局时额外添加四周的空白边距
    def layout(self, zoom):
        self.zoom = zoom
        self.width = const.WIDTH - 2 * dpx(const.HSTEP, self.zoom)  # "HSTEP"作为左右的空白边距
        self.x = dpx(const.HSTEP, self.zoom)
        self.y = dpx(const.VSTEP, self.zoom)  # "VSTEP"作为上下的空白边距

        child = BlockLayout(self.node, self, None)
        self.children.append(child)
        child.layout()
        self.height = child.height

    def paint(self):
        return []

    def should_paint(self):
        return True


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

        node.layout_object = self

    # 计算baseline位置、确定行高
    def layout(self):
        self.zoom = self.parent.zoom

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

        # 让每个TextLayout自己计算x绘制坐标、宽度、高度以及字体.
        # 仅当所有子结点完成layout之后，才能计算出当前line的baseline位置、高度等
        for word in self.children:
            word.layout()

        # 行内的所有TextLayout均以计算完成，然后确定baseline的位置以及每个TextLayout的y绘制坐标

        # 计算一行中最大的ascent
        max_ascent = max([-child.ascent for child in self.children])

        # 可以直接以"max_ascent"作为baseline的位置，或者在这个基础上、在最大字符的ascent与descent之外再
        # 添加一些leading（空白区域），ascent上面添加一半leading, descent下面添加一半leading,
        # 这样，lineheight = (ascent + descent) + ascent_leading + descent_leading
        # 这里在最大ascent上面与最大descent下面各添加25%的leading
        baseline = self.y + max_ascent

        # 确定各个子结点的y绘制坐标
        for child in self.children:
            if isinstance(child, TextLayout):
                child.y = baseline - (-child.ascent / 1.25)
            else:
                # 对于"InputLayout, ImageLayout"等其他inline layout object
                child.y = baseline - -child.ascent

        max_descent = max([child.descent for child in self.children])
        self.height = max_ascent + max_descent

    def paint(self):
        # 由TextLayout负责绘制字符
        return []

    def should_paint(self):
        return True

    def paint_effects(self, cmds):
        outline_rect = Rect.MakeEmpty()
        outline_node = None

        for child in self.children:
            # "InputLayout.node"为DOM结点，而"TextLayout.node"为DOM结点下的"Text",
            # 因此这里需要区分一下
            is_inputlayout = isinstance(child, InputLayout)

            # layout object对应的DOM结点
            effect_node = child.node if is_inputlayout else child.node.parent

            outline_str = effect_node.style.get("outline")
            if parse_outline(outline_str):
                outline_rect.join(child.self_rect())
                outline_node = effect_node

        # 同一时刻仅能有一个DOM结点获取焦点，所以上面的"for"循环时，"outline_node"变量只能被相同的DOM结点赋值一次或者多次.
        # （当"child"是TextLayout时，同样成立。注意：是以layout object对应的DOM结点的样式来绘制焦点的）
        if outline_node:
            paint_outline(outline_node, cmds, outline_rect, self.zoom)

        return cmds


# 表示LineLayout中的每一个word
class TextLayout:
    def __init__(self, node, word, parent, previous):
        # 与LineLayout中保存的node不同，这个是HTML DOM中的"Text"结点,例如：
        #
        #    DOM Tree                        Layout Tree
        #
        #
        #                                    BlockLayout (node: <body>)
        #    <body> layout mode:               |
        #     |        inline                  |
        #     |                                +-->LineLayout (node: <body>)
        #     +-><a>             ------->             |
        #         |                                   |
        #         +>Text                              +->TextLayout (node: Text)
        #
        self.node = node

        self.word = word
        self.parent = parent
        self.previous = previous  # 上一个word
        self.children = []

        # 绘制所需的绝对坐标
        self.x = None
        self.y = None  # 由"LineLayout.layout()"在计算最大的ascent后赋值
        self.height = None
        self.width = None

        # "Text"DOM nodes don't have the layout object reference

    def layout(self):
        self.zoom = self.parent.zoom

        weight = self.node.style["font-weight"]
        style = self.node.style["font-style"]
        if style == "normal":
            style = "roman"
        size = dpx(float(self.node.style["font-size"][:-2]) * 0.75, self.zoom)
        self.font = get_font(size, weight, style)

        self.ascent = self.font.getMetrics().fAscent * 1.25
        self.descent = self.font.getMetrics().fDescent * 1.25

        self.width = self.font.measureText(self.word)
        if self.previous:
            space = self.previous.font.measureText(" ")
            self.x = self.previous.x + self.previous.width + space
        else:
            self.x = self.parent.x
        self.height = linespace(self.font)

    def paint(self):
        color = self.node.style["color"]
        return [DrawText(self.x, self.y, self.word, self.font, color)]

    def should_paint(self):
        return True

    def self_rect(self):
        return Rect(self.x, self.y, self.x + self.width, self.y + self.height)


# <input>, <button>以及<img>等inline html element的layout object的父类, 包含一些通用的属性以及布局流程
class EmbedLayout:
    def __init__(self, node, parent, previous, frame=None):
        self.node = node
        self.parent = parent
        self.previous = previous
        self.frame = frame
        self.children = []

        # 绘制所需的绝对坐标
        self.x = None
        self.y = None
        self.height = None
        self.width = None

        node.layout_object = self

    # 根据前一个inline element计算当前layout object的x坐标
    def layout(self):
        self.zoom = self.parent.zoom
        self.font = font(self.node.style, self.zoom)

        if self.previous:
            # 使用相邻的前一个layout object的font计算两者间距
            space = self.previous.font.measureText(" ")

            self.x = self.previous.x + self.previous.width + space
        else:
            self.x = self.parent.x

        # 计算"self.width"时，不同的inline element有不同的计算方法,所以将这个计算委托至子类中完成

    def should_paint(self):
        return True

    def self_rect(self):
        return Rect(self.x, self.y, self.x + self.width, self.y + self.height)


# <input>或者<button>对应的layout object
class InputLayout(EmbedLayout):
    def __init__(self, node, parent, previous):
        super().__init__(node, parent, previous)  # "self.node"表示"<input>"或者"<button>"的DOM结点

    def layout(self):
        super().layout()

        self.width = dpx(INPUT_WIDTH_PX, self.zoom)
        self.height = linespace(self.font)
        self.ascent = -self.height
        self.descent = 0

    def paint(self):
        cmds = []

        # 绘制背景色
        bgcolor = self.node.style.get("background-color", "transparent")
        if bgcolor != "transparent":
            radius = float(self.node.style.get("border-radius", "0px")[:-2])
            cmds.append(DrawRRect(self.self_rect(), radius, bgcolor))

        # 绘制文字
        if self.node.tag == "input":
            # <input>标签中，在矩形绘制区域内,绘制HTML的"value"属性值
            text = self.node.attributes.get("value", "")
        elif self.node.tag == "button":
            if len(self.node.children) == 1 and isinstance(self.node.children[0], Text):
                text = self.node.children[0].text
            else:
                # 如果<button>内包含非纯文本内容则不绘制
                print("Ignoring HTML contents inside the button")
                text = ""
        color = self.node.style["color"]
        cmds.append(DrawText(self.x, self.y, text, self.font, color))

        # 如果当前"<input>"已获取焦点，则绘制光标
        if self.node.is_focused and self.node.tag == "input":
            cx = self.x + self.font.measureText(text)
            cmds.append(DrawLine(cx, self.y, cx, self.y + self.height, "black", 1))

        return cmds

    def paint_effects(self, cmds):
        cmds = paint_visual_effects(self.node, cmds, self.self_rect())
        paint_outline(self.node, cmds, self.self_rect(), self.zoom)
        return cmds


# "<img>"对应的layout object
class ImageLayout(EmbedLayout):
    def __init__(self, node, parent, previous):
        super().__init__(node, parent, previous)

    def layout(self):
        super().layout()

        width_attr = self.node.attributes.get("width")
        height_attr = self.node.attributes.get("height")
        image_width = self.node.image.width()
        image_height = self.node.image.height()

        if width_attr and height_attr:
            # 如果同时设置了"width"与"height"HTML属性, 那么就采用设置的大小渲染
            self.width = dpx(int(width_attr), self.zoom)
            self.img_height = dpx(int(height_attr), self.zoom)
        else:
            # 图片原始宽度, 采用该原始宽度作为layout object的宽度
            self.width = dpx(image_width, self.zoom)
            self.img_height = dpx(image_height, self.zoom)  # 图片原始高度

        # 图片的高度可能会基于"<img>"的"font"
        self.height = max(self.img_height, linespace(self.font))

        self.ascent = -self.height
        self.descent = 0

    def paint(self):
        cmds = []

        rect = Rect.MakeLTRB(
            self.x,
            # 对于第二个参数，如果图片高于font lineheight, 那么图片的顶部与font的ascent对齐，图片
            # 的上下边界充满整个line. 如果图片低于font lineheight, 那么图片的底部与font的descent对齐，
            # 图片的上面与font ascent之间会留出一小块空白区域
            self.y + self.height - self.img_height,
            self.x + self.width,
            self.y + self.height,
        )
        quality = self.node.style.get("image-rendering", "auto")
        cmds.append(DrawImage(self.node.image, rect, quality))
        return cmds


def paint_visual_effects(node, cmds, rect):
    opacity = float(node.style.get("opacity", "1.0"))
    blend_mode = node.style.get("mix-blend-mode")
    translation = parse_transform(node.style.get("transform", ""))

    # 如果"overflow"为"clip"，则根据"border-radius"裁剪当前layout对象的绘制区域
    if node.style.get("overflow", "visible") == "clip":
        if not blend_mode:
            blend_mode = "source-over"
        border_radius = float(node.style.get("border-radius", "0px")[:-2])

        # 这里实例化Blend时，"node"的参数设置为"None",详情参见"Tab.run_animation_frame()"函数中"composited_updates"
        # 变量的相关注释
        cmds.append(Blend(1, "destination-in", None, [DrawRRect(rect, border_radius, "white")]))

    blend_op = Blend(opacity, blend_mode, node, cmds)
    node.blend_op = blend_op
    return [Transform(translation, rect, node, [blend_op])]


# 解析css"outline"的语法, 仅支持"1px solid red"这样的语法结构
def parse_outline(outline_str):
    if not outline_str:
        return None

    values = outline_str.split(" ")
    if len(values) != 3:
        return None
    if values[1] != "solid":
        return None

    # 返回"thickness"以及"color"
    return int(values[0][:-2]), values[2]


def paint_outline(node, cmds, rect, zoom):
    outline = parse_outline(node.style.get("outline"))
    if not outline:
        return

    thickness, color = outline
    cmds.append(DrawOutline(rect, color, dpx(thickness, zoom)))


def font(style, zoom):
    weight = style["font-weight"]
    variant = style["font-style"]
    if variant == "normal":
        variant = "roman"
    size = float(style["font-size"][:-2]) * 0.75
    font_size = dpx(size, zoom)
    return get_font(font_size, weight, variant)
