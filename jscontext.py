import dukpy
import json
from threading import Timer, Thread
from css_parser import CSSParser
from utils import tree_to_list, log
from html_parser import HTMLParser
from task import Task

RUNTIME_JS = open("runtime.js").read()
REBIND_JS = open("rebind.js").read()

# 触发Javascript中的event handler
# 新建一个包含handle的Javascript DOM Node对象，然后在这个对象上触发事件
# 注意，javascript中的event handler中的"this"指向的是一个临时新建的Node对象，而非实际被点击的Python中DOM Tree中的Node对象
EVENT_DISPATCH_JS = "new Node(dukpy.handle).dispatchEvent(new Event(dukpy.type))"

SETTIMEOUT_JS = "__runSetTimeout(dukpy.handle)"
XHR_ONLOAD_JS = "__runXHROnload(dukpy.out, dukpy.handle)"

POST_MESSAGE_DISPATCH_JS = "window.dispatchEvent(new MessageEvent(dukpy.data))"

TIMEOUT_TIMERS = []


# Javascript运行时.
# 为了支持"<iframe>"以及引入"Frame"之后，js context与frame的关系如下：
# 不管是否same-origin, 每个Frame拥有自己的全局对象window，不会发生命名冲突。
# same-origin的多个Frame共享一个js context，虽然拥有各自的window，但是可以通过
# 非same-origin的多个Frame采用各自的js context.
#
#                               Tab
#
#     (www.a.com)        (www.a.com)       (www.b.com)
#       Frame 0             Frame 1           Frame 2
#          |                   |                 |
#    +-----+-------------------+-------+   +-----+------+
#    |     |                   |       |   |     |      |
#    |     v      interact     v       |   |     v      |
#    |  window 0  <------>  window 1   |   |  window 2  |
#    |                                 |   |            |
#    +---------------------------------+   +------------+
#                 js context                 js context
class JSContext:
    """Javascript运行时"""

    def __init__(self, tab, url_origin):
        self.tab = tab
        self.url_origin = url_origin

        # 创建一个Javascript runtime,网页上的所有js代码都将在这个runtime中执行,
        # 这样可以保证网页中不同"<script>"中context的连续性
        self.interp = dukpy.JSInterpreter()

        self.tab.browser.measure.time("RUNTIME_JS")
        self.interp.evaljs(RUNTIME_JS)  # 创建全局对象的Window类型
        self.tab.browser.measure.stop("RUNTIME_JS")

        self.interp.export_function("log", log.js)
        self.interp.export_function("querySelectorAll", self.querySelectorAll)
        self.interp.export_function("getElementById", self.getElementById)
        self.interp.export_function("getAttribute", self.getAttribute)
        self.interp.export_function("innerHTML_set", self.innerHTML_set)
        self.interp.export_function("setTimeout", self.setTimeout)
        self.interp.export_function("XMLHttpRequest_send", self.XMLHttpRequest_send)
        self.interp.export_function("requestAnimationFrame", self.requestAnimationFrame)
        self.interp.export_function("style_set", self.style_set)
        self.interp.export_function("setAttribute", self.setAttribute)
        self.interp.export_function("parent", self.parent)
        self.interp.export_function("postMessage", self.postMessage)

        # python的DOM node与Javascript DOM node间的映射
        #
        # 由于Python的对象无法直接转换为Javascript的Object,所以采用下面的方法：
        # 用一个唯一的整数(handle)表示Python的DOM node,这个整数可在Python与Javascript中传递,
        # 当Javascript读取python DOM node时，返回这个整数，当Javascript修改某个DOM node时，也需要提供这个整数
        # 这个方式有点像file descriptor.
        # 另外，目前这个映射存在内存泄漏的问题：当Javascript中通过"innerHTML"删除一个DOM节点后，
        # 这里仍然保存这个Python DOM node。解决这个问题可能需要Python与Javascript虚拟机间的协同垃圾回收.
        #
        # 当网页的Javascript中调用"document.[querySelectorAll() | getElementById()]"时才会在这个map中
        # 保存新的映射。
        self.node_to_handle = {}  # python DOM node -> handle
        self.handle_to_node = {}  # handle -> python DOM node

        # 该js context是否已被废弃。
        #
        # 在tab页加载新的url前后，task queue不变但会创建新的js context.
        # 因此加载新url后，queue中可能存在一些待执行的旧task(由旧url页面添加的task), 这些task不应再被旧的js context执行
        self.discarded = False

    def add_window(self, frame):
        # 创建全局对象window
        self.interp.evaljs(f"WINDOWS[{frame.window_id}] = new Window({frame.window_id})")

    def parent(self, window_id):
        # 根据Frame对象的创建过程（在"Frame.load()"函数中创建, Frame.parent_frame不一定是same-origin的parent frame，
        # 而仅是在Frame实现结构上的parent），这里得到的parent frame与window_id表示
        # 的frame可能是same-origin，也可能不是
        parent_frame = self.tab.window_id_to_frame[window_id].parent_frame
        if not parent_frame:
            return None
        return parent_frame.window_id

    def postMessage(self, target_window_id, message, origin):
        task = Task(self.tab.post_message, message, target_window_id)
        self.tab.task_runner.schedule_task(task)

    def dispatch_post_message(self, message, window_id):
        self.interp.evaljs(self.wrap(POST_MESSAGE_DISPATCH_JS, window_id), data=message)

    def throw_if_cross_origin(self, frame):
        if frame.url.origin() != self.url_origin:
            raise Exception("cross origin access disallowed from js context!")

    # 在某个全局对象window的范围内执行javascript, 并重新bind一些全局变量
    # 用来模拟浏览器的js runtime中"window.<global property> === <global property>"的特性.
    #
    # 实际执行的user script("script"参数)将在匿名function中执行以避免在js context的top-level scope中命名冲突
    def wrap(self, script, window_id):
        return f"(function() {{ window = WINDOWS[{window_id}]; {REBIND_JS}; return eval({json.dumps(script)}) }})();"

    def run(self, code, window_id):
        try:
            self.tab.browser.measure.time("run js")
            self.interp.evaljs(self.wrap(code, window_id))
        except dukpy.JSRuntimeError as e:
            log.e(f"@@@ JS crashed! @@@\n{e}")
        except Exception as e:
            log.e(f"@@@ JS Context Error! @@@\n{e}")
        finally:
            self.tab.browser.measure.stop("run js")

    def querySelectorAll(self, selector_text, window_id):
        frame = self.tab.window_id_to_frame[window_id]
        self.throw_if_cross_origin(frame)

        selector = CSSParser(selector_text).selector()
        nodes = [node for node in tree_to_list(frame.nodes, []) if selector.matches(node)]
        return [self.get_handle(node) for node in nodes]

    def getElementById(self, id, window_id):
        frame = self.tab.window_id_to_frame[window_id]
        self.throw_if_cross_origin(frame)

        selected = None
        all_nodes = tree_to_list(frame.nodes, [])
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

    def getAttribute(self, handle, attr, window_id):
        frame = self.tab.window_id_to_frame[window_id]
        self.throw_if_cross_origin(frame)

        elt = self.handle_to_node[handle]
        attr = elt.attributes.get(attr, None)
        return attr if attr else ""

    def dispatch_event(self, type, elt, window_id):
        handle = self.node_to_handle.get(elt, -1)

        self.tab.browser.measure.time("EVENT_DISPATCH_JS")
        do_default = self.interp.evaljs(
            self.wrap(EVENT_DISPATCH_JS, window_id), type=type, handle=handle
        )
        self.tab.browser.measure.stop("EVENT_DISPATCH_JS")

        return not do_default  # 如果返回True，则表示不执行后续default操作，否则执行

    def innerHTML_set(self, handle, s, window_id):
        frame = self.tab.window_id_to_frame[window_id]
        self.throw_if_cross_origin(frame)

        doc = HTMLParser(f"<html><body>{s}</body></html>").parse()
        new_nodes = doc.children[0].children
        elt = self.handle_to_node[handle]
        elt.children = new_nodes
        for node in new_nodes:
            node.parent = elt
        frame.set_needs_render()

    def XMLHttpRequest_send(self, method, url, body, is_async, handle, window_id):
        frame = self.tab.window_id_to_frame[window_id]
        full_url = frame.url.resolve(url)

        if not frame.allowed_request(full_url):
            raise Exception("XHR blocked by CSP")

        if full_url.origin() != frame.url.origin():
            raise Exception("CORS not allowed")

        def run_load():
            headers, response = full_url.request(frame.url, body)
            response = response.decode("utf8", "replace")
            task = Task(self.dispatch_xhr_onload, response, handle, window_id)
            self.tab.task_runner.schedule_task(task)
            return response

        if not is_async:
            return run_load()
        else:
            # 理论上，两个异步的xhr请求时,同时访问cookie可能会有线程安全问题。但目前暂不考虑
            Thread(target=run_load).start()

    def dispatch_settimeout(self, handle, window_id):
        if self.discarded:
            return

        self.tab.browser.measure.time("SETTIMEOUT_JS")
        self.interp.evaljs(self.wrap(SETTIMEOUT_JS, window_id), handle=handle)
        self.tab.browser.measure.stop("SETTIMEOUT_JS")

    def setTimeout(self, handle, time, window_id):
        frame = self.tab.window_id_to_frame[window_id]
        self.throw_if_cross_origin(frame)

        def run_callback():
            task = Task(self.dispatch_settimeout, handle, window_id)
            self.tab.task_runner.schedule_task(task)
            TIMEOUT_TIMERS.remove(t)

        # 在time ms后执行run_callback. run_callback执行在其他线程中.
        # 因此，当浏览器在某些timer的callback实际执行之前被关闭时，主进程会等待直到
        # callback执行结束后才终止。
        t = Timer(time / 1000, run_callback)
        TIMEOUT_TIMERS.append(t)
        t.start()

    def dispatch_xhr_onload(self, out, handle, window_id):
        if self.discarded:
            return

        self.tab.browser.measure.time("XHR_ONLOAD_JS")
        self.interp.evaljs(self.wrap(XHR_ONLOAD_JS, window_id), out=out, handle=handle)
        self.tab.browser.measure.stop("XHR_ONLOAD_JS")

    def dispatch_RAF(self, window_id):
        self.interp.evaljs(self.wrap("window.__runRAFHandlers()", window_id))

    def requestAnimationFrame(self, window_id):

        # mainloop中已经实现了以固定频率schedule render task。这里如果
        # 再次schedule,那么动画的渲染频率将比固定频率还快.如果取消这次schedule,
        # 那么动画将以固定频率渲染
        #
        # task = Task(self.tab.render)
        # self.tab.task_runner.schedule_task(task)

        frame = self.tab.window_id_to_frame[window_id]
        self.throw_if_cross_origin(frame)
        frame.set_needs_render()

    def style_set(self, handle, s, window_id):
        frame = self.tab.window_id_to_frame[window_id]
        self.throw_if_cross_origin(frame)

        node = self.handle_to_node[handle]
        node.attributes["style"] = s
        frame.set_needs_render()

    def setAttribute(self, handle, attr, value, window_id):
        frame = self.tab.window_id_to_frame[window_id]
        self.throw_if_cross_origin(frame)

        elt = self.handle_to_node[handle]
        elt.attributes[attr] = value
        frame.set_needs_render()

    def destroy(self):
        for t in TIMEOUT_TIMERS:
            t.cancel()
