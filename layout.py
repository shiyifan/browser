from fields import ProtectedField
from font import *
from tags import Text, Element
from commands import *
import const
from utils import parse_transform, dpx, pf_n, text_digest, tree_to_list
import json

# <input>的固定宽度
INPUT_WIDTH_PX = 200


# 对应于DOM tree node, 该类表示用于布局的layout tree中的节点。
# DOM tree中大部分可绘制的节点(block html element或者inline html element)对应于layout tree中的节点。
# layout过程中为DOM节点计算屏幕所在坐标、宽高、以及要绘制内容，并将要绘制的
# 内容保存在"display list"中等待下一步实际的渲染流程.
#
# 子结点左上角的x、y坐标以及宽度继承自父结点，仅包含inline元素和text的子结点的高度由字体决定.
# 父结点的高度是所有子结点的高度之和.
class BlockLayout:
    def __init__(self, node, parent, previous):
        self.node = node  # DOM结点
        self.parent = parent
        self.previous = previous  # previous sibling
        self.children = ProtectedField(self, "children", self.parent)

        # 该layout相对于canvas左上角的绝对坐标
        self.x = ProtectedField(self, "x", self.parent)
        self.y = ProtectedField(self, "y", self.parent)

        self.width = ProtectedField(self, "width", self.parent)
        self.height = ProtectedField(self, "height", self.parent)

        # layout内的子结点相对于layout左上角的相对坐标
        # 所以子结点的绝对坐标等于"self.x + self.cursor_x"
        self.cursor_x = None

        node.layout_object = self

        self.zoom = ProtectedField(self, "zoom", self.parent)

        # 所有的descendants node是否需要重新layout（即是否有dirty的protected field）
        self.has_dirty_descendants = False

    # 根据绘制方式创建layout tree
    def layout(self):
        if not self.layout_needed():
            return

        self.zoom.copy(self.parent.zoom)

        # 根据layout tree中的父结点以及previous计算当前结点的x坐标、y坐标以及宽度width.
        self.x.copy(self.parent.x)  # 子结点的绘制起始点的x坐标继承自父结点的x坐标
        self.width.copy(self.parent.width)

        # 子结点绘制起始点的y坐标继承自父结点的y坐标（如果当前结点是父结点的第一个子结点）,或者上一个兄弟结点的"y坐标 + 兄弟结点的高度"
        if self.previous:
            prev_y = self.previous.y.read(notify=self.y)
            prev_height = self.previous.height.read(notify=self.y)
            self.y.set(prev_y + prev_height)
        else:
            self.y.copy(self.parent.y)

        # 根据layout方式创建当前结点的children
        mode = self.layout_mode()
        if mode == "block":
            # 以"block"方式绘制

            if self.children.dirty:
                # 无论是"block"还是"inline"方式布局, "children"一旦变为dirty, 那么将重建整个children, 重新创建每一个子结点.
                # 这是一种简单的实现。
                #
                # 当前"invalidation"仅实现在"BlockLayout.children"的层面上. children一旦dirty将重新创建. 实际上还可以更细致地优化：
                # 例如：如果"children"中某一个child变为dirty, 则无需重建children, 仅受影响的child即可。这种情况下遍历children时需要
                # 更细致地检查，跳过不受影响的child, 重新计算可能受影响的child的信息。这些实现较为复杂.

                children = []
                previous = None
                for child in self.node.children:
                    next = BlockLayout(child, self, previous)
                    children.append(next)
                    previous = next
                self.children.set(children)
        else:
            # 计算inline元素的绘制信息，并创建LineLayout以及TextLayout作为当前BlockLayout的子节点.
            # 由LineLayout以及TextLayout负责绘制与计算

            if self.children.dirty:
                # 临时保存在"new_line"以及"recurse"过程中添加的LineLayout以及inline layout object
                self.temp_children = []

                self.new_line()
                self.recurse(self.node)
                self.children.set(self.temp_children)
                self.temp_children = None

        for child in self.children.get():
            child.layout()

        # block html element的高度等于所有子结点的高度之和.
        # 在所有子结点计算得到height之后再计算当前结点的高度
        #
        # 当前"BlockLayout.height"不仅依赖于children, 也依赖于children中，每个child的height
        children = self.children.read(notify=self.height)
        new_height = sum([child.height.read(notify=self.height) for child in children])
        self.height.set(new_height)

        self.has_dirty_descendants = False

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
        elif self.node.children or self.node.tag in ["input", "img", "iframe"]:
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
            elif node.tag == "iframe" and "src" in node.attributes:
                self.iframe(node)
            else:
                # 与"<input>"或者"<button>"不同，对于"<a>"这样的DOM结点，没有为其创建专用的Layout,
                # 而采用通用的"TextLayout", 因此"TextLayout"中的"TextLayout.node"值为DOM结点下的"Text"结点
                for child in node.children:
                    self.recurse(child)

    # 对以"inline"方式绘制的DOM节点在layout tree上创建LineLayout与TextLayout节点。
    # 计算每个word的宽度，并根据宽度判断是否超出一行。
    # 这里仅用于创建layout tree结构，而计算baseline、确定行高的流程由LineLayout负责完成
    def word(self, node, word):
        zoom = self.zoom.read(notify=self.children)
        style = node.style.read(notify=self.children)

        node_font = font(style, zoom)
        w = node_font.measureText(word)
        self.add_inline_child(node, w, TextLayout, word)

    # 与"word()"方法相似，将<input>和<button>以与纯文本相似的方式添加至LineLayout中
    def input(self, node):
        zoom = self.zoom.read(notify=self.children)
        w = dpx(INPUT_WIDTH_PX, zoom)  # "<input>"布局时采用固定宽度
        self.add_inline_child(node, w, InputLayout)

    # 将<img>添加至LineLayout中
    def image(self, node):
        aspect_ratio = node.image.width() / node.image.height()
        zoom = self.zoom.read(notify=self.children)

        if "width" in node.attributes:
            # 如果以"<img width=''>"的方式指定了宽度
            w = dpx(int(node.attributes["width"]), zoom)
        elif "height" in node.attributes:
            # 如果以"<img height=''>"的方式指定了高度且没有指定宽度，那么根据宽高比计算宽度
            h = dpx(int(node.attributes["height"]), zoom)
            w = h * aspect_ratio
        else:
            w = dpx(node.image.width(), zoom)  # 默认情况下，"<img>"布局时采用图片原始宽度

        self.add_inline_child(node, w, ImageLayout)

    # 将<iframe>添加至LineLayout中
    def iframe(self, node):
        zoom = self.zoom.read(notify=self.children)
        if "width" in node.attributes:
            w = dpx(int(node.attributes["width"]), zoom)
        else:
            w = const.IFRAME_WIDTH_PX + dpx(2, zoom)
        self.add_inline_child(node, w, IframeLayout, parent_frame=node.frame.parent_frame)

    # 添加inline layout object至LineLayout中
    #
    # "w": 待加入的inline layout object的宽度，已在调用该函数前根据计算得到.
    #      用于计算是否换行以及更新下一个layout object的x坐标
    # "child_class": inline layout class
    def add_inline_child(self, node, w, child_class, word=None, parent_frame=None):
        width = self.width.read(notify=self.children)
        if self.cursor_x + w > width:
            # 根据BlockLayout宽度，已超出一行时，新建一行
            self.new_line()

        line = self.temp_children[-1]
        previous_word = line.children[-1] if line.children else None
        if word:
            # 此时添加的是"TextLayout"
            child = child_class(node, word, line, previous_word)
        else:
            if child_class == IframeLayout:
                child = child_class(node, line, previous_word, parent_frame)
            else:
                child = child_class(node, line, previous_word)
        line.children.append(child)

        # 更新x坐标，作为同一line中下一个inline element的布局x坐标
        zoom = self.zoom.read(notify=self.children)
        style = node.style.read(notify=self.children)
        self.cursor_x += w + font(style, zoom).measureText(" ")

    def new_line(self):
        self.cursor_x = 0
        last_line = self.temp_children[-1] if self.temp_children else None
        new_line = LineLayout(self.node, self, last_line)
        self.temp_children.append(new_line)

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
        style = self.node.style.get()
        bgcolor = style.get("background-color", "transparent")
        if bgcolor != "transparent":
            radius = float(style.get("border-radius", "0px")[:-2])
            cmds.append(DrawRRect(self.self_rect(), radius, bgcolor))

        # 绘制由于"contenteditable"创建的编辑区域内的光标. 目前仅在最后的TextLayout后面添加光标
        if self.node.is_focused and "contenteditable" in self.node.attributes:
            text_nodes = [t for t in tree_to_list(self, []) if isinstance(t, TextLayout)]
            if text_nodes:
                cmds.append(DrawCursor(text_nodes[-1], text_nodes[-1].width.get()))
            else:
                cmds.append(DrawCursor(self, 0))

        return cmds

    def paint_effects(self, cmds):
        """
        绘制css visual effect, 例如opacity等. 注意: 应用在当前layout对象的effect同样也会应用在
        children上

        cmds: 当前layout对象与children的绘制命令
        """

        cmds = paint_visual_effects(self.node, cmds, self.self_rect())
        if isinstance(self.node, Element) and "tabindex" in self.node.attributes:
            # 如果html element有"tabindex"属性，那么该element也可以获得焦点并绘制该焦点.
            zoom = self.zoom.get()
            paint_outline(self.node, cmds, self.self_rect(), zoom)
        return cmds

    def self_rect(self):
        x = self.x.get()
        y = self.y.get()
        w = self.width.get()
        h = self.height.get()

        return Rect(x, y, x + w, y + h)

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
        return isinstance(self.node, Text) or (
            self.node.tag not in ["input", "button", "img", "iframe"]
        )

    def layout_needed(self):
        return (
            self.zoom.dirty
            or self.width.dirty
            or self.height.dirty
            or self.x.dirty
            or self.y.dirty
            or self.children.dirty
            or self.has_dirty_descendants
        )

    def __repr__(self):
        label = None
        if isinstance(self.node, Element):
            label = f"<{self.node.tag}>"
        else:
            label = f"#text{json.dumps(text_digest(self.node.text))}"

        x = pf_n(self.x)
        y = pf_n(self.y)
        width = pf_n(self.width)
        height = pf_n(self.height)

        return f"BlockLayout({label}, ({x}, {y}, w{width}, h{height}))"


# 对应于DOM根结点的layout object。
# 负责根据viewport大小定义根元素的绘制坐标
class DocumentLayout:
    def __init__(self, node):
        self.node = node
        self.parent = None
        self.children = []

        self.x = ProtectedField(self, "x")
        self.y = ProtectedField(self, "y")
        self.width = ProtectedField(self, "width")
        self.height = ProtectedField(self, "height")

        node.layout_object = self

        self.zoom = ProtectedField(self, "zoom")

        self.has_dirty_descendants = False

    # 对整个HTML文档内容布局
    #
    # 布局时额外添加四周的空白边距
    def layout(self, width, zoom):
        if not self.layout_needed():
            return

        self.width.set(width - 2 * dpx(const.HSTEP, zoom))  # "HSTEP"作为左右的空白边距
        self.x.set(dpx(const.HSTEP, zoom))
        self.y.set(dpx(const.VSTEP, zoom))  # "VSTEP"作为上下的空白边距

        if not self.children:
            child = BlockLayout(self.node, self, None)
            self.children = [child]
        else:
            child = self.children[0]

        self.zoom.set(zoom)
        child.zoom.mark()

        child.layout()
        self.height.copy(child.height)

        self.has_dirty_descendants = False

    def paint(self):
        return []

    def should_paint(self):
        return True

    def layout_needed(self):
        return (
            self.x.dirty
            or self.y.dirty
            or self.width.dirty
            or self.height.dirty
            or self.zoom.dirty
            or self.has_dirty_descendants
        )

    def __repr__(self):
        x = pf_n(self.x)
        y = pf_n(self.y)
        width = pf_n(self.width)
        height = pf_n(self.height)
        return f"DocumentLayout(<{self.node.tag}>, ({x}, {y}, w{width}, h{height}))"


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

        self.x = ProtectedField(self, "x", self.parent)
        self.y = ProtectedField(self, "y", self.parent)
        self.width = ProtectedField(self, "width", self.parent)
        self.height = ProtectedField(self, "height", self.parent)

        self.ascent = ProtectedField(self, "ascent", self.parent)
        self.descent = ProtectedField(self, "descent", self.parent)

        node.layout_object = self

        self.zoom = ProtectedField(self, "zoom", self.parent)

        self.has_dirty_descendants = False

    # 计算baseline位置、确定行高
    def layout(self):
        if not self.layout_needed():
            return

        self.zoom.copy(self.parent.zoom)
        self.width.copy(self.parent.width)
        self.x.copy(self.parent.x)

        if self.previous:
            prev_y = self.previous.y.read(notify=self.y)
            prev_height = self.previous.height.read(notify=self.y)
            self.y.set(prev_y + prev_height)
        else:
            self.y.copy(self.parent.y)

        if not self.children:
            # 如果LineLayout没有TextLayout子节点，那么高度为0
            self.height.set(0)
            return

        # 让每个child inline layout自己计算x绘制坐标、宽度、高度以及字体.
        # 仅当所有子结点完成layout之后，才能计算出当前line的baseline位置、高度等
        for word in self.children:
            word.layout()

        # 行内的所有TextLayout均以计算完成，然后确定baseline的位置以及每个TextLayout的y绘制坐标

        # 计算一行中最大的ascent.
        # LineLayout的ascent依赖于每一个child的ascent.
        child_ascents = [child.ascent for child in self.children]
        max_ascent = max([-asc.read(notify=self.ascent) for asc in child_ascents])
        self.ascent.set(max_ascent)

        # 确定各个子结点的y绘制坐标
        for child in self.children:
            y = self.y.read(notify=child.y)
            asc = self.ascent.read(notify=child.y)
            child_asc = child.ascent.read(notify=child.y)

            # 可以直接以"max_ascent"作为baseline的位置，或者在这个基础上、在最大字符的ascent与descent之外再
            # 添加一些leading（空白区域），ascent上面添加一半leading, descent下面添加一半leading,
            # 这样，lineheight = (ascent + descent) + ascent_leading + descent_leading
            # 这里在最大ascent上面与最大descent下面各添加25%的leading
            baseline = y + asc

            if isinstance(child, TextLayout):
                child.y.set(baseline - (-child_asc / 1.25))
            else:
                # 对于"InputLayout, ImageLayout"等其他inline layout object
                child.y.set(baseline - -child_asc)

        child_descents = [child.descent for child in self.children]
        max_descent = max([desc.read(notify=self.descent) for desc in child_descents])
        self.descent.set(max_descent)

        max_asc = self.ascent.read(notify=self.height)
        max_desc = self.descent.read(notify=self.height)
        self.height.set(max_asc + max_desc)

        self.has_dirty_descendants = False

    def paint(self):
        # 由TextLayout负责绘制字符
        return []

    def should_paint(self):
        return True

    def paint_effects(self, cmds):
        outline_rect = Rect.MakeEmpty()  # 所有需要绘制outline的TextLayout的矩形区域的并集
        outline_node = None

        for child in self.children:
            # "InputLayout.node"为DOM结点，而"TextLayout.node"为DOM结点下的"Text",
            # 因此这里需要区分一下
            is_inputlayout = isinstance(child, InputLayout)

            # 实际获取焦点的DOM结点
            effect_node = child.node if is_inputlayout else child.node.parent

            if (
                isinstance(self.node, Element)
                and self.node.tag in const.BLOCK_ELEMENTS
                and effect_node == self.node
            ):
                # 对于以"inline"(根据"layout_mode()")方式绘制的Block HTML Element(且这个Element可以通过
                # "tabindex"属性获取焦点), 如果Text作为直接子结点，那么点击这个Text后会重复绘制outline: 一次绘制Text
                # 的outline(在TextLayout的并集区域上),另一次绘制Element的outline.
                #
                # 例如下面两种情况：
                #
                # 下面左侧的DOM结构中, 只有"<a>"下面的"Text"渲染了outline，但是渲染右侧的结构时，
                # <div>以及"Text"将绘制各自的outline.
                #
                #    <div>
                #     |                  click!        <div> (focused)     click!
                #     +><a>(focused)       |             |                   |
                #        |                 |             +>ThisIsAnchor <----+
                #        +>ThisIsAnchor <--+
                #
                #                            |
                #                            |  both can generate same layout tree
                #                            v
                #
                #                 BlockLayout (node: div)
                #                    |
                #                    +->LineLayout  (node: div)
                #                         |
                #                         +->TextLayout  (node: Text)
                #
                # 点击之后，左侧的"<a>"以及右侧的"<div>"分别获取了焦点。
                # 对于右侧的结构，<div>的LineLayout绘制时，由于根据"TextLayout"获取的"effect_node"变量为<div>,
                # 因此<div>下的所有TextLayout都将绘制outline, LineLayout绘制结束后，div开始绘制effect("BlockLayout.paint_effects()"),
                # 这时又绘制了一次outline.
                #
                # 在右侧的情况下，当判断出Text是parent element的直接子结点(effect_node == self.node), 而且parent是Block HTML Element时,
                # 将outline的绘制委托至parent(由"BlockLayout.paint_effects()"负责绘制)

                return cmds

            effect_style = effect_node.style.get()
            outline_str = effect_style.get("outline")
            if parse_outline(outline_str):
                outline_rect.join(child.self_rect())
                outline_node = effect_node

        # 同一时刻仅能有一个DOM结点获取焦点，所以上面的"for"循环时，"outline_node"变量只能被相同的DOM结点赋值一次或者多次.
        # （当"child"是TextLayout时，同样成立。注意：是以layout object对应的DOM结点的样式来绘制焦点的）
        if outline_node:
            zoom = self.zoom.get()
            paint_outline(outline_node, cmds, outline_rect, zoom)

        return cmds

    def layout_needed(self):
        return (
            self.x.dirty
            or self.y.dirty
            or self.width.dirty
            or self.height.dirty
            or self.ascent.dirty
            or self.descent.dirty
            or self.zoom.dirty
            or self.has_dirty_descendants
        )

    def __repr__(self):
        label = None
        if isinstance(self.node, Element):
            label = f"<{self.node.tag}>"
        else:
            label = f"#text{json.dumps(text_digest(self.node.text))}"

        x = pf_n(self.x)
        y = pf_n(self.y)
        width = pf_n(self.width)
        height = pf_n(self.height)

        return f"LineLayout({label}, ({x}, {y}, w{width}, h{height}))"


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
        self.x = ProtectedField(self, "x", self.parent)
        # 由"LineLayout.layout()"在计算最大的ascent后赋值
        self.y = ProtectedField(self, "y", self.parent)
        self.height = ProtectedField(self, "height", self.parent)
        self.width = ProtectedField(self, "width", self.parent)

        self.font = ProtectedField(self, "font", self.parent)
        self.ascent = ProtectedField(self, "ascent", self.parent)
        self.descent = ProtectedField(self, "descent", self.parent)

        self.zoom = ProtectedField(self, "zoom", self.parent)

        self.has_dirty_descendants = False

        # "Text"DOM nodes don't have the layout object reference

    def layout(self):
        if not self.layout_needed():
            return

        self.zoom.copy(self.parent.zoom)

        zoom = self.zoom.read(notify=self.font)
        node_style = self.node.style.read(notify=self.font)

        self.font.set(font(node_style, zoom))

        f = self.font.read(notify=self.width)
        self.width.set(f.measureText(self.word))
        f = self.font.read(notify=self.ascent)
        self.ascent.set(f.getMetrics().fAscent * 1.25)
        f = self.font.read(notify=self.descent)
        self.descent.set(f.getMetrics().fDescent * 1.25)

        if self.previous:
            # 当前layout object的x坐标依赖于相邻的前一个layout object的x坐标、font以及width
            prev_x = self.previous.x.read(notify=self.x)
            prev_font = self.previous.font.read(notify=self.x)
            prev_width = self.previous.width.read(notify=self.x)
            space = prev_font.measureText(" ")
            self.x.set(prev_x + prev_width + space)
        else:
            self.x.copy(self.parent.x)

        f = self.font.read(notify=self.height)
        self.height.set(linespace(f))

        self.has_dirty_descendants = False

    def paint(self):
        node_style = self.node.style.get()
        color = node_style["color"]
        x = self.x.get()
        y = self.y.get()
        font = self.font.get()
        return [DrawText(x, y, self.word, font, color)]

    def should_paint(self):
        return True

    def self_rect(self):
        return Rect(self.x, self.y, self.x + self.width.get(), self.y + self.height)

    def layout_needed(self):
        return (
            self.x.dirty
            or self.y.dirty
            or self.height.dirty
            or self.width.dirty
            or self.font.dirty
            or self.ascent.dirty
            or self.descent.dirty
            or self.zoom.dirty
            or self.has_dirty_descendants
        )

    def __repr__(self):
        x = pf_n(self.x)
        y = pf_n(self.y)
        width = pf_n(self.width)
        height = pf_n(self.height)

        return f"TextLayout({self.word!r}, ({x}, {y}, w{width}, h{height}))"


# <input>, <button>以及<img>等inline html element的layout object的父类, 包含一些通用的属性以及布局流程
class EmbedLayout:
    def __init__(self, node, parent, previous, frame=None):
        self.node = node  # DOM node
        self.parent = parent  # layout tree中，当前layout object的parent
        self.previous = previous
        self.frame = frame
        self.children = []

        # 绘制所需的绝对坐标
        self.x = ProtectedField(self, "x", self.parent)
        self.y = ProtectedField(self, "y", self.parent)
        self.height = ProtectedField(self, "height", self.parent)
        self.width = ProtectedField(self, "width", self.parent)

        node.layout_object = self

        self.zoom = ProtectedField(self, "zoom", self.parent)

        # 对于某些inline layout object, 可能需要font确定高度，所以在基类中创建这三个属性，由子类决定是否赋值与调用
        self.font = ProtectedField(self, "font", self.parent)
        self.ascent = ProtectedField(self, "ascent", self.parent)
        self.descent = ProtectedField(self, "descent", self.parent)

        self.has_dirty_descendants = False

    # 根据前一个inline element计算当前layout object的x坐标
    def layout(self):
        self.zoom.copy(self.parent.zoom)

        node_style = self.node.style.read(notify=self.font)
        zoom = self.zoom.read(notify=self.font)

        self.font.set(font(node_style, zoom))

        if self.previous:
            # 使用相邻的前一个layout object的font计算两者间距
            prev_x = self.previous.x.read(notify=self.x)
            prev_font = self.previous.font.read(notify=self.x)
            prev_width = self.previous.width.read(notify=self.x)

            space = prev_font.measureText(" ")
            self.x = prev_x + prev_width + space
        else:
            self.x.copy(self.parent.x)

        # 计算"self.width"时，不同的inline element有不同的计算方法,所以将这个计算委托至子类中完成

    def should_paint(self):
        return True

    def self_rect(self):
        x = self.x.get()
        y = self.y.get()
        w = self.width.get()
        h = self.height.get()

        return Rect(x, y, x + w, y + h)

    def layout_needed(self):
        return (
            self.x.dirty
            or self.y.dirty
            or self.height.dirty
            or self.width.dirty
            or self.zoom.dirty
            or self.font.dirty
            or self.ascent.dirty
            or self.descent.dirty
            or self.has_dirty_descendants
        )


# <input>或者<button>对应的layout object
class InputLayout(EmbedLayout):
    def __init__(self, node, parent, previous):
        super().__init__(node, parent, previous)  # "self.node"表示"<input>"或者"<button>"的DOM结点

    def layout(self):
        if not self.layout_needed():
            return

        super().layout()

        zoom = self.zoom.read(notify=self.width)
        self.width.set(dpx(INPUT_WIDTH_PX, zoom))

        font = self.font.read(notify=self.height)
        self.height.set(linespace(font))

        height = self.height.read(notify=self.ascent)
        self.ascent.set(-height)
        self.descent.set(0)

        self.has_dirty_descendants = False

    def paint(self):
        cmds = []

        # 绘制背景色
        node_style = self.node.style.get()
        bgcolor = node_style.get("background-color", "transparent")
        if bgcolor != "transparent":
            radius = float(node_style.get("border-radius", "0px")[:-2])
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
        color = node_style["color"]
        cmds.append(DrawText(self.x.get(), self.y.get(), text, self.font.get(), color))

        # 如果当前"<input>"已获取焦点，则绘制光标
        if self.node.is_focused and self.node.tag == "input":
            font = self.font.get()
            cmds.append(DrawCursor(self, font.measureText(text)))

        return cmds

    def paint_effects(self, cmds):
        cmds = paint_visual_effects(self.node, cmds, self.self_rect())
        paint_outline(self.node, cmds, self.self_rect(), self.zoom.get())
        return cmds

    def __repr__(self):
        x = pf_n(self.x)
        y = pf_n(self.y)
        width = pf_n(self.width)
        height = pf_n(self.height)

        return f"InputLayout(<{self.node.tag}>, ({x}, {y}, w{width}, h{height}))"


# "<img>"对应的layout object
class ImageLayout(EmbedLayout):
    def __init__(self, node, parent, previous):
        super().__init__(node, parent, previous)

    def layout(self):
        if not self.layout_needed():
            return

        super().layout()

        width_attr = self.node.attributes.get("width")
        height_attr = self.node.attributes.get("height")
        image_width = self.node.image.width()
        image_height = self.node.image.height()

        aspect_ratio = image_width / image_height  # 图片原始的宽高比
        zoom = self.zoom.read(notify=self.width)

        width = None
        if width_attr and height_attr:
            # 如果同时设置了"width"与"height"HTML属性, 那么就采用设置的大小渲染
            width = dpx(int(width_attr), zoom)
            self.img_height = dpx(int(height_attr), zoom)
        elif width_attr:
            # 当仅设置"width"或者"height"时，用原始的宽高比计算另一个
            width = dpx(int(width_attr), zoom)
            self.img_height = width / aspect_ratio
        elif height_attr:
            self.img_height = dpx(int(height_attr), zoom)
            width = self.img_height * aspect_ratio
        else:
            # 图片原始宽度, 采用该原始宽度作为layout object的宽度
            width = dpx(image_width, zoom)
            self.img_height = dpx(image_height, zoom)  # 图片原始高度

        self.width.set(width)
        # 图片的高度可能会基于"<img>"的"font"
        font = self.font.read(notify=self.height)
        self.height.set(max(self.img_height, linespace(font)))

        height = self.height.read(notify=self.ascent)
        self.ascent.set(-height)
        self.descent.set(0)

        self.has_dirty_descendants = False

    def paint(self):
        cmds = []

        rect = Rect.MakeLTRB(
            self.x,
            # 对于第二个参数，如果图片高于font lineheight, 那么图片的顶部与font的ascent对齐，图片
            # 的上下边界充满整个line. 如果图片低于font lineheight, 那么图片的底部与font的descent对齐，
            # 图片的上面与font ascent之间会留出一小块空白区域
            self.y + self.height - self.img_height,
            self.x + self.width.get(),
            self.y + self.height,
        )
        quality = self.node.style.get().get("image-rendering", "auto")
        cmds.append(DrawImage(self.node.image, rect, quality))
        return cmds

    def __repr__(self):
        x = pf_n(self.x)
        y = pf_n(self.y)
        width = pf_n(self.width)
        height = pf_n(self.height)

        return f"ImageLayout(<{self.node.tag}>, ({x}, {y}, w{width}, h{height}))"


#'<iframe>'对应的layout object
class IframeLayout(EmbedLayout):
    def __init__(self, node, parent, previous, parent_frame):
        # "self.node"表示"<iframe>" DOM node
        super().__init__(node, parent, previous, parent_frame)

    def layout(self):
        if not self.layout_needed():
            return

        super().layout()

        width_attr = self.node.attributes.get("width")
        height_attr = self.node.attributes.get("height")

        zoom = self.zoom.read(notify=self.width)
        width = None
        if width_attr:
            width = dpx(int(width_attr) + 2, zoom)
        else:
            width = dpx(const.IFRAME_WIDTH_PX + 2, zoom)
        self.width.set(width)

        zoom = self.zoom.read(notify=self.height)
        height = None
        if height_attr:
            height = dpx(int(height_attr) + 2, zoom)
        else:
            height = dpx(int(const.IFRAME_HEIGHT_PX) + 2, zoom)
        self.height.set(height)

        height = self.height.read(notify=self.ascent)
        self.ascent.set(-height)
        self.descent.set(0)

        # 将计算得到的width与height赋值给对应的"Frame"对象, 使得<iframe>内部可以正确地layout
        f = self.node.frame
        f_height = self.height.get() - dpx(2, zoom)
        f_width = self.width.get() - dpx(2, zoom)
        if f_width != f.frame_width:
            f.frame_height = f_height
            f.frame_width = f_width
            f.document.width.mark()
            f.document.height.mark()

        self.has_dirty_descendants = False

    def paint(self):
        return []

    def paint_effects(self, cmds):
        rect = self.self_rect()
        zoom = self.zoom.get()

        # 在这里实现iframe的滚动.
        #
        # 不管是root frame的滚动还是其他frame的滚动，均通过"canvas.translate()"实现.
        #
        # root frame的滚动是通过browser和tab共同实现的（因为threaded scroll）, 为了方便起见，其他的frame的滚动仅由tab实现.
        # 绘制滚动时，通过"Transform"先将canvas在y轴上translate一定距离(即frame的已滚动距离"frame.scroll"),
        # 然后再绘制iframe的内容。(由于后面通过"Blend(destination-in)以及Blend(source-over)去除了iframe的可视区域外
        # 的内容, 所以不会出现iframe的内容与parent frame重叠的现象")
        # 不过这样实现时，需要注意"tab.run_animation_frame()"中的"composited_updates"变量. 因为滚动仅需要重新"paint", 所以
        # "browser.draw()"依然采用旧的"composited_layers".
        #
        # 简单起见, 目前在iframe滚动时, 在"frame.scrolldown()"中设置"scroll_changed_in_frame = True"让
        # browser重新composite. (比较完美的实现方式类似于"animation"的绘制机制，browser无需再次composite. 当前的"animation"
        # 绘制流程比较单一，缺乏灵活性，无法通过简单地修改使其同样适用于frame scroll)
        diff = dpx(1, zoom)
        x = self.x.get()
        y = self.y.get()
        width = self.width.get()
        height = self.height.get()

        offset = (x + diff, y + diff - self.node.frame.scroll)
        cmds = [Transform(offset, rect, self.node, cmds)]

        inner_rect = Rect.MakeLTRB(
            x + diff,
            y + diff,
            x + width - diff,
            y + height - diff,
        )
        internal_cmds = cmds
        internal_cmds.append(
            Blend(1.0, "destination-in", None, [DrawRRect(inner_rect, 0, "white")])
        )
        cmds = [Blend(1.0, "source-over", self.node, internal_cmds)]

        paint_outline(self.node, cmds, rect, zoom)
        cmds = paint_visual_effects(self.node, cmds, rect)

        return cmds

    def __repr__(self):
        x = pf_n(self.x)
        y = pf_n(self.y)
        width = pf_n(self.width)
        height = pf_n(self.height)

        return f"IframeLayout(<{self.node.tag}>, {self.node.url}, ({x}, {y}, w{width}, h{height}))"


def paint_visual_effects(node, cmds, rect):
    node_style = node.style.get()

    opacity = float(node_style.get("opacity", "1.0"))
    blend_mode = node_style.get("mix-blend-mode")
    translation = parse_transform(node_style.get("transform", ""))

    # 如果"overflow"为"clip"，则根据"border-radius"裁剪当前layout对象的绘制区域
    if node_style.get("overflow", "visible") == "clip":
        if not blend_mode:
            blend_mode = "source-over"
        border_radius = float(node_style.get("border-radius", "0px")[:-2])

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
    outline = parse_outline(node.style.get().get("outline"))
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
