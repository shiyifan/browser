import dukpy
from threading import Timer, Thread
from css_parser import CSSParser
from utils import tree_to_list, log
from html_parser import HTMLParser
from task import Task

RUNTIME_JS = open("runtime.js").read()

# 触发Javascript中的event handler
# 新建一个包含handle的Javascript DOM Node对象，然后在这个对象上触发事件
# 注意，javascript中的event handler中的"this"指向的是一个临时新建的Node对象，而非实际被点击的Python中DOM Tree中的Node对象
EVENT_DISPATCH_JS = "new Node(dukpy.handle).dispatchEvent(new Event(dukpy.type))"

SETTIMEOUT_JS = "__runSetTimeout(dukpy.handle)"
XHR_ONLOAD_JS = "__runXHROnload(dukpy.out, dukpy.handle)"


class JSContext:
    """Javascript运行时"""

    def __init__(self, tab):
        self.tab = tab

        # 创建一个Javascript runtime,网页上的所有js代码都将在这个runtime中执行,
        # 这样可以保证网页中不同"<script>"中context的连续性
        self.interp = dukpy.JSInterpreter()
        self.interp.evaljs(RUNTIME_JS)  # 准备runtime环境

        self.interp.export_function("log", log.js)
        self.interp.export_function("querySelectorAll", self.querySelectorAll)
        self.interp.export_function("getElementById", self.getElementById)
        self.interp.export_function("getAttribute", self.getAttribute)
        self.interp.export_function("innerHTML_set", self.innerHTML_set)
        self.interp.export_function("setTimeout", self.setTimeout)
        self.interp.export_function("XMLHttpRequest_send", self.XMLHttpRequest_send)

        # python的DOM node与Javascript DOM node间的映射
        #
        # 由于Python的对象无法直接转换为Javascript的Object,所以采用下面的方法：
        # 用一个唯一的整数(handle)表示Python的DOM node,这个整数可在Python与Javascript中传递,
        # 当Javascript读取python DOM node时，返回这个整数，当Javascript修改某个DOM node时，也需要提供这个整数
        # 这个方式有点像file descriptor
        # 另外，目前这个映射存在内存泄漏的问题：当Javascript中通过"innerHTML"删除一个DOM节点后，
        # 这里仍然保存这个Python DOM node。解决这个问题可能需要Python与Javascript虚拟机间的协同
        self.node_to_handle = {}  # python DOM node -> handle
        self.handle_to_node = {}  # handle -> python DOM node

        # 该js context是否已被废弃。
        #
        # 在tab页加载新的url前后，task queue不变但会创建新的js context.
        # 因此加载新url后，queue中可能存在一些待执行的旧task(由旧url页面添加的task), 这些task不应再被旧的js context执行
        self.discarded = False

    def run(self, code):
        try:
            return self.interp.evaljs(code)
        except dukpy.JSRuntimeError as e:
            log.e(f"@@@ JS crashed! @@@\n{e}")

    def querySelectorAll(self, selector_text):
        selector = CSSParser(selector_text).selector()
        nodes = [
            node for node in tree_to_list(self.tab.nodes, []) if selector.matches(node)
        ]
        return [self.get_handle(node) for node in nodes]

    def getElementById(self, id):
        selected = None
        all_nodes = tree_to_list(self.tab.nodes, [])
        for node in all_nodes:
            if not hasattr(node, "attributes"):
                continue

            attr = node.attributes
            if attr.get("id") == id:
                return self.get_handle(node)

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

    def dispatch_event(self, type, elt):
        handle = self.node_to_handle.get(elt, -1)
        do_default = self.interp.evaljs(EVENT_DISPATCH_JS, type=type, handle=handle)
        return not do_default  # 如果返回True，则表示不执行后续default操作，否则执行

    def innerHTML_set(self, handle, s):
        doc = HTMLParser(f"<html><body>{s}</body></html>").parse()
        new_nodes = doc.children[0].children
        elt = self.handle_to_node[handle]
        elt.children = new_nodes
        for node in new_nodes:
            node.parent = elt
        self.tab.set_needs_render()

    def XMLHttpRequest_send(self, method, url, body, is_async, handle):
        full_url = self.tab.url.resolve(url)

        if not self.tab.allowed_request(full_url):
            raise Exception("XHR blocked by CSP")

        if full_url.origin() != self.tab.url.origin():
            raise Exception("CORS not allowed")

        def run_load():
            headers, response = full_url.request(self.tab.url, body)
            task = Task(self.dispatch_xhr_onload, response, handle)
            self.tab.task_runner.schedule_task(task)
            return response

        if not is_async:
            return run_load()
        else:
            # 理论上，两个异步的xhr请求时,同时访问cookie可能会有线程安全问题。但不前暂不考虑
            Thread(target=run_load).start()

    def dispatch_settimeout(self, handle):
        if self.discarded:
            return
        self.interp.evaljs(SETTIMEOUT_JS, handle=handle)

    def setTimeout(self, handle, time):
        def run_callback():
            task = Task(self.dispatch_settimeout, handle)
            self.tab.task_runner.schedule_task(task)

        # 在time ms后执行run_callback. run_callback执行在其他线程中.
        # 因此，当浏览器在某些timer的callback实际执行之前被关闭时，主进程会等待直到
        # callback执行结束后才终止。
        Timer(time / 1000, run_callback).start()

    def dispatch_xhr_onload(self, out, handle):
        if self.discarded:
            return
        self.interp.evaljs(XHR_ONLOAD_JS, out=out, handle=handle)
