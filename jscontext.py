import dukpy

RUNTIME_JS = open("runtime.js").read()

class JSContext:
    """Javascript运行时"""

    def __init__(self):
        # 创建一个Javascript runtime,网页上的所有js代码都将在这个runtime中执行,
        # 这样可以保证网页中不同"<script>"中context的连续性
        self.interp = dukpy.JSInterpreter()
        self.interp.evaljs(RUNTIME_JS) # 准备runtime环境

        self.interp.export_function("log", print)

    def run(self, code):
        return self.interp.evaljs(code)

