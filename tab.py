from html_parser import HTMLParser
import const
import urllib.parse
from layout import DocumentLayout
from tags import Element, Text
from css_parser import CSSParser
from jscontext import JSContext

# 浏览器默认样式，user agent style
DEFAULT_STYLE_SHEET = CSSParser(open("browser.css").read()).parse()


# 浏览器标签页
# 负责url请求、DOM解析、layout tree解析
class Tab:
    def __init__(self, tab_height):
        self.scroll = 0  # 当前已向上滑动的距离
        self.loaded = False

        # tab页的高度，即"canvas高度" - "canvas顶部chrome所占据的高度"
        self.tab_height = tab_height

        self.url = None
        self.history = []  # 保存访问过的url，并且当前tab页显示的网页url位于数组末尾

        self.nodes = None  # HTML解析后的DOM Tree
        self.rules = None  # css解析后的rules

        self.focus = None  # 点击后，获取到焦点的'<input>'DOM对象

    def load(self, url, payload=None):
        self.history.append(url)
        self.url = url

        body = url.request(payload)
        self.nodes = HTMLParser(body).parse()  # 将HTML代码解析为DOM tree

        # HTML代码中，所有"<script src=''>"的标签
        #
        # 注意：该浏览器不实现类似于"<script>...js code...</script>"的内嵌功能，因为
        # 解析时区分HTML与js中的"<"以及">"符号较为复杂
        scripts = [
            node.attributes["src"]
            for node in tree_to_list(self.nodes, [])
            if isinstance(node, Element)
            and node.tag == "script"
            and "src" in node.attributes
        ]
        self.js = JSContext()
        for script in scripts:
            script_url = url.resolve(script)
            try:
                body = script_url.request()
                self.js.run(body)
            except:
                continue

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
        self.rules = rules
        self.render()

        self.loaded = True

    def render(self):
        """根据DOM Tree构建layout tree,然后收集layout tree上每个结点的绘制command"""

        style(
            self.nodes, sorted(self.rules, key=cascade_priority)
        )  # 将css rules全部赋值至DOM结点的"style"属性上
        self.document = DocumentLayout(self.nodes)
        self.document.layout()  # 构建layout tree
        self.display_list = []
        paint_tree(
            self.document, self.display_list
        )  # 收集layout tree上每个layout object生成的绘制command

    def draw(self, canvas, offset):
        """根据已生成的绘制command,在canvas上绘制tab内容，由Browser调用"""

        # 根据计算后页面元素的坐标、样式开始绘制
        for cmd in self.display_list:
            # 不绘制位于窗口可见区域之外的内容
            if cmd.rect.top > self.scroll + self.tab_height:
                continue
            if cmd.rect.bottom < self.scroll:
                continue

            cmd.execute(self.scroll - offset, canvas)

    def scrollup(self):
        if self.scroll <= 0:
            return

        self.scroll -= const.SCROLL_STEP

    def scrolldown(self):
        # 已显示最后一行内容后，不再继续向下滚动
        max_y = max(self.document.height + 2 * const.VSTEP - self.tab_height, 0)
        self.scroll = min(self.scroll + const.SCROLL_STEP, max_y)

    def keypress(self, char):
        if self.focus:
            self.focus.attributes["value"] += char
            self.render()

    def click(self, x, y):
        # 如果未找到被点击的layout object, 返回前是否需要重绘
        focus_lost = False

        # 判断点击位置之前先重置焦点
        if self.focus:
            self.focus.is_focused = False
            self.focus = None
            focus_lost = True

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
            if focus_lost:
                self.render()
            return
        elt = objs[-1].node  # 获取最上层被点击的layout object对应的DOM node

        # 根据最上层的object,依次向上查找第一个"<a>"
        while elt:
            if isinstance(elt, Text):
                pass
            elif elt.tag == "a" and "href" in elt.attributes:
                # 找到最上层的"<a>"，加载"href"指向的链接
                url = self.url.resolve(elt.attributes["href"])
                return self.load(url)
            elif elt.tag == "input":
                self.focus = elt
                elt.attributes["value"] = ""
                elt.is_focused = True
                return self.render()
            elif elt.tag == "button":
                # 被点击的是"<button>"，准备提交表单
                while elt:
                    # 寻找上层的"<form>"
                    if elt.tag == "form" and "action" in elt.attributes:
                        return self.submit_form(elt)
                    elt = elt.parent
            elt = elt.parent
        self.render()

    def reconfigure(self):
        if self.loaded:
            if not self.nodes:
                return
            self.document = DocumentLayout(self.nodes)
            self.document.layout()
            self.display_list = []
            paint_tree(self.document, self.display_list)

    def go_back(self):
        """返回至上一个访问的url"""

        if len(self.history) > 1:
            self.history.pop()
            back = self.history.pop()
            self.load(back)

    def submit_form(self, elt):
        inputs = [
            node
            for node in tree_to_list(elt, [])
            if isinstance(node, Element)
            and node.tag == "input"
            and "name" in node.attributes
        ]

        # encode the "name-value" pairs
        # 采用url的"%"编码方式

        body = ""
        for input in inputs:
            name = urllib.parse.quote(input.attributes["name"])
            value = urllib.parse.quote(input.attributes.get("value", ""))
            body += f"&{name}={value}"
        body = body[1:]
        url = self.url.resolve(elt.attributes["action"])
        self.load(url, body)


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
    if layout_object.should_paint():
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
