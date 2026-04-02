from html_parser import HTMLParser
import const
from layout import DocumentLayout
from tags import Element, Text
from css_parser import CSSParser

# 浏览器默认样式，user agent style
DEFAULT_STYLE_SHEET = CSSParser(open("browser.css").read()).parse()


# 浏览器标签页
# 负责url请求、DOM解析、layout tree解析
class Tab:
    def __init__(self):
        self.scroll = 0  # 当前已向上滑动的距离
        self.loaded = False

        self.url = None

    def load(self, url):
        self.url = url

        body = url.request()
        self.nodes = HTMLParser(body).parse()  # 将HTML代码解析为DOM tree

        rules = DEFAULT_STYLE_SHEET.copy()  # 解析user agent stylesheet
        # HTML代码中，所有的"<link rel=stylesheet>"标签中的css url
        links = [
            node.attributes["href"]
            for node in tree_to_list(self.nodes, [])
            if isinstance(node, Element)
            and node.tag == "link"
            and node.attributes.get("rel") == "stylesheet"
            and "href" in node.attributes
        ]
        for link in links:
            style_url = url.resolve(link)
            try:
                body = style_url.request()
            except:
                continue
            rules.extend(CSSParser(body).parse())  # 获取author stylesheet

        style(self.nodes, sorted(rules, key=cascade_priority))

        self.document = DocumentLayout(self.nodes)
        self.document.layout()
        self.display_list = []
        paint_tree(self.document, self.display_list)

        self.loaded = True

    # 在canvas上绘制tab内容，由Browser调用
    def draw(self, canvas):
        # 根据计算后页面元素的坐标、样式开始绘制
        for cmd in self.display_list:
            # 不绘制位于窗口可见区域之外的内容
            if cmd.top > self.scroll + const.HEIGHT:
                continue
            if cmd.bottom < self.scroll:
                continue

            cmd.execute(self.scroll, canvas)

    def scrollup(self):
        if self.scroll <= 0:
            return

        self.scroll -= const.SCROLL_STEP

    def scrolldown(self):
        # 已显示最后一行内容后，不再继续向下滚动
        max_y = max(self.document.height + 2 * const.VSTEP - const.HEIGHT, 0)
        self.scroll = min(self.scroll + const.SCROLL_STEP, max_y)

    def click(self, x, y):
        y += self.scroll  # 使纵坐标y为相对于网页绘制内容的坐标

        # 根据绘制区域与点击坐标，在"layout tree"中找到所有被点击的layout object
        #
        # 可能会找到多个被点击的layout object,这些object位于tree中的不同层级
        # 在实际情况下，也可能出现相同层级的HTML元素被同时点击（例如"margin"为负值时），此时browser还需要
        # 根据"stacking context"机制判断最上层的被点击元素
        objs = [
            obj
            for obj in tree_to_list(self.document, [])
            if obj.x <= x < obj.x + obj.width and obj.y <= y < obj.y + obj.height
        ]
        if not objs:
            return
        elt = objs[-1].node  # 获取最上层被点击的layout object

        # 根据最上层的object,依次向上查找第一个"<a>"
        while elt:
            if isinstance(elt, Text):
                pass
            elif elt.tag == "a" and "href" in elt.attributes:
                # 找到最上层的"<a>"，加载"href"指向的链接
                url = self.url.resolve(elt.attributes["href"])
                return self.load(url)
            elt = elt.parent

    def reconfigure(self):
        if self.loaded:
            if not self.nodes:
                return
            self.document = DocumentLayout(self.nodes)
            self.document.layout()
            self.display_list = []
            paint_tree(self.document, self.display_list)


# 根据DOM结点上"style"属性、css文件的代码创建CSS对象并赋值为"style"属性
def style(node, rules):
    node.style = {}  # CSS解析后的对象

    # 先解析当前节点的inherited property的值
    for property, default_value in const.INHERITED_PROPERTIES.items():
        if node.parent:
            node.style[property] = node.parent.style[property]
        else:
            node.style[property] = default_value

    # 解析css代码中与当前节点匹配的rule并应用至当前节点
    for selector, body in rules:
        if not selector.matches(node):
            continue
        for property, value in body.items():
            node.style[property] = value

    # 解析DOM中"style"属性的样式
    if isinstance(node, Element) and "style" in node.attributes:
        pairs = CSSParser(node.attributes["style"]).body()
        for property, value in pairs.items():
            node.style[property] = value

    # 如果DOM节点的"font-size"值为百分比数值，则根据父结点的值或者默认值计算具体"px"单位的数值
    if node.style["font-size"].endswith("%"):
        if node.parent:
            parent_font_size = node.parent.style["font-size"]
        else:
            parent_font_size = const.INHERITED_PROPERTIES["font-size"]
        node_pct = float(node.style["font-size"][:-1]) / 100
        parent_px = float(parent_font_size[:-2])
        node.style["font-size"] = str(node_pct * parent_px) + "px"

    # 解析并创建子结点的CSS对象
    for child in node.children:
        style(child, rules)


def paint_tree(layout_object, display_list):
    display_list.extend(layout_object.paint())
    for child in layout_object.children:
        paint_tree(child, display_list)


# 树状结构转为扁平的list结构
def tree_to_list(tree, list):
    list.append(tree)
    for child in tree.children:
        tree_to_list(child, list)
    return list


def cascade_priority(rule):
    selector, rule = rule
    return selector.priority
