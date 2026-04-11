import dukpy
from css_parser import CSSParser
from utils import tree_to_list, print_err, print_js

RUNTIME_JS = open("runtime.js").read()


class JSContext:
    """Javascript运行时"""

    def __init__(self, tab):
        self.tab = tab

        # 创建一个Javascript runtime,网页上的所有js代码都将在这个runtime中执行,
        # 这样可以保证网页中不同"<script>"中context的连续性
        self.interp = dukpy.JSInterpreter()
        self.interp.evaljs(RUNTIME_JS)  # 准备runtime环境

        self.interp.export_function("log", print_js)
        self.interp.export_function("querySelectorAll", self.querySelectorAll)
        self.interp.export_function("getAttribute", self.getAttribute)

        # python的DOM node与Javascript DOM node间的映射
        #
        # 由于Python的对象无法直接转换为Javascript的Object,所以采用下面的方法：
        # 用一个唯一的整数(handle)表示Python的DOM node,当Javascript读取python DOM node时，
        # 返回这个整数，当Javascript修改某个DOM node时，也需要提供这个整数
        # 这个方式有点像file descriptor
        self.node_to_handle = {}
        self.handle_to_node = {}

    def run(self, code):
        try:
            return self.interp.evaljs(code)
        except dukpy.JSRuntimeError as e:
            print_err(f"@@@ JS crashed! @@@\n{e}")

    def querySelectorAll(self, selector_text):
        selector = CSSParser(selector_text).selector()
        nodes = [
            node for node in tree_to_list(self.tab.nodes, []) if selector.matches(node)
        ]
        return [self.get_handle(node) for node in nodes]

    def get_handle(self, elt):
        if elt not in self.node_to_handle:
            handle = len(self.node_to_handle)
            self.node_to_handle[elt] = handle
            self.handle_to_node[handle] = elt
        else:
            handle = self.node_to_handle[elt]
        return handle

    def getAttribute(self, handle, attr):
        elt = self.handle_to_node[handle]
        attr = elt.attributes.get(attr, None)
        return attr if attr else ""
