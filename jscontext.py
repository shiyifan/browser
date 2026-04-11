import dukpy
from css_parser import CSSParser
from utils import tree_to_list, print_err

RUNTIME_JS = open("runtime.js").read()


class JSContext:
    """Javascript运行时"""

    def __init__(self, tab):
        self.tab = tab

        # 创建一个Javascript runtime,网页上的所有js代码都将在这个runtime中执行,
        # 这样可以保证网页中不同"<script>"中context的连续性
        self.interp = dukpy.JSInterpreter()
        self.interp.evaljs(RUNTIME_JS)  # 准备runtime环境

        self.interp.export_function("log", print)
        self.interp.export_function("querySelectorAll", self.querySelectorAll)

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
        return nodes
