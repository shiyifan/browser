// 浏览器Javascript Runtime所需的变量
// 定义一些全局变量和函数，例如console、document、Node、Event等

/*
由于Javascript和Python之间无法传递对象，因此互操作时尽量采用简单类型数值作为handle，例如整数。
并且可能会在Python与Javascript中分别创建handle与对象的映射：

对于同一个handle:
Python: 
  map = { handle -> Python对象 }
Javascript: 
  var map = { handle -> Javascript对象 }
这样Python对象就与Javascript对象建立了对应关系
*/

console = {
  log: function () {
    var joined = Array.prototype.join.call(arguments, ' '); // 将多个参数合并为一个字符串
    call_python('log', joined); // 调用Python中导出的function'log'
  },
};

/* 保存window_id与window对象之间的映射。 { window_id: window对象 }.
same-origin的Frame在同一个js context中创建属于各自的window对象，并以"window_id"区分. */
WINDOWS = {};

/* 
全局对象window的类型：Window.

浏览器环境中，可全局访问的method、variables（requestAnimationFrame, setTimeout, document）等都是全局对象window的
属性(访问这些变量时如果当前scope中没有则会继续在上一层scope中查找，直到top-level scope仍然没有时，在全局对象window的属性中
继续查找, 因此默认情况下"<global prop> === window.<global prop>")。且绝大部分都是window的own property
(即定义在window对象中而非window的prototype中).

Dukpy不支持自定义全局对象，这里尽可能地模仿实际的浏览器javascript runtime, 自定义Window类型并且，
window大部分的属性均为own property. 
且通过'rebind.js'重新绑定这些全局属性（支持同一js context中定义多个window对象的情况, for same-origin iframe）
使得在user script中可以通过"<global prop>"或者"window.<global prop>"两个方式访问全局属性.
*/
function Window(id) {
  this._id = id; // 内部property, user script中不可以调用

  /* 保存在当前window对象注册的event与event handler间的映射。
    { event type: [event handlers] } */
  this.WINDOW_LISTENERS = {};

  /* 保存注册在DOM node上的event与event handler间的映射.
    { node handle: { event type: [event handlers] } } */
  this.LISTENERS = {};

  /* XHR与handle间的对应关系: { xhr handle: XHR object }. 用于实现异步xhr请求。
  当浏览器利用多线程完成请求时，Python中根据handle触发xhr对象上的onload事件 */
  this.XHR_REQUESTS = {};

  // 保存setTimeout的callback与handle的对应关系, { timeout handle: timeout callback }
  this.SET_TIMEOUT_REQUESTS = {};

  /* 保存animation frame的callback */
  this.RAF_LISTENERS = [];

  /* 下面的属性还需要通过"rebind.js"绑定为全局属性 */
  this.document = new Document();
  this.Event = Event;
  this.MessageEvent = MessageEvent;
  this.Node = Node;
  this.Document = Document;
  this.XMLHttpRequest = XMLHttpRequest;
  this.setTimeout = setTimeout;
  this.__runSetTimeout = __runSetTimeout;
  this.__runXHROnload = __runXHROnload;
  this.requestAnimationFrame = requestAnimationFrame;
  this.__runRAFHandlers = __runRAFHandlers;

  var window = this;

  /* 表示一般的由DOM node触发的event */
  function Event(type) {
    this.type = type;
    this.do_default = true; // 是否执行默认的后续流程
  }

  Event.prototype.preventDefault = function () {
    this.do_default = false;
  };

  /* window对象之间"postMessage"触发的event */
  function MessageEvent(data) {
    this.type = 'message'; // event type
    this.data = data;
  }

  /* DOM node的类型. */
  function Node(handle) {
    this.handle = handle;
  }

  Node.prototype.getAttribute = function (attr) {
    return call_python('getAttribute', this.handle, attr, window._id);
  };

  Node.prototype.setAttribute = function (attr, value) {
    return call_python('setAttribute', this.handle, attr, value, window._id);
  };

  Node.prototype.addEventListener = function (type, listener) {
    if (!window.LISTENERS[this.handle]) window.LISTENERS[this.handle] = {};

    listeners = window.LISTENERS[this.handle];
    if (!listeners[type]) listeners[type] = [];

    listeners[type].push(listener);
  };

  Node.prototype.dispatchEvent = function (evt) {
    var type = evt.type;
    var handle = this.handle;
    var list = (window.LISTENERS[handle] && window.LISTENERS[handle][type]) || [];

    for (var i = 0; i < list.length; i++) {
      list[i].call(this, evt);
    }

    /* 事件处理完成后，是否继续执行default后续流程
      只要有一个event handler调用了"preventDefault()"，那么后续流程将不会执行 */
    return evt.do_default;
  };

  Object.defineProperties(Node.prototype, {
    innerHTML: {
      set: function (s) {
        call_python('innerHTML_set', this.handle, s.toString(), window._id);
      },
    },
    style: {
      set: function (s) {
        call_python('style_set', this.handle, s.toString(), window._id);
      },
    },
  });

  /* "document"的类型 */
  function Document() {}

  Document.prototype.querySelectorAll = function (s) {
    var handlers = call_python('querySelectorAll', s, window._id);
    return handlers.map(function (h) {
      return new Node(h);
    });
  };

  Document.prototype.getElementById = function (id) {
    var handle = call_python('getElementById', id, window._id);
    return handle == null ? null : new Node(handle);
  };

  /* XMLHttpRequest对象

  由于该类由user script调用并创建xhr对象，因此无法像"Node"一样在参数中添加"window id"这样的内部变量。
  这里直接访问当前global scope中的"window"对象 */
  function XMLHttpRequest() {
    this.handle = Object.keys(window.XHR_REQUESTS).length;
    window.XHR_REQUESTS[this.handle] = this;
  }

  XMLHttpRequest.prototype.open = function (method, url, is_async) {
    this.is_async = is_async;
    this.method = method;
    this.url = url;
  };

  XMLHttpRequest.prototype.send = function (body) {
    /* prettier-ignore */
    this.responseText = call_python(
      'XMLHttpRequest_send',
      this.method,
      this.url,
      body,
      this.is_async,
      this.handle,
      window._id
    );
  };

  function setTimeout(callback, time_delta) {
    var handle = Object.keys(window.SET_TIMEOUT_REQUESTS).length;
    window.SET_TIMEOUT_REQUESTS[handle] = callback;
    call_python('setTimeout', handle, time_delta, window._id);
  }

  function __runSetTimeout(handle) {
    var callback = window.SET_TIMEOUT_REQUESTS[handle];
    callback();

    /* 这里没有从window.SET_TIMEOUT_REQUESTS中删除callback,可能会导致memory leak */
  }

  function __runXHROnload(body, handle) {
    var obj = window.XHR_REQUESTS[handle];
    var evt = new Event('load');
    obj.responseText = body;
    if (obj.onload) {
      obj.onload(evt);
    }
  }

  function requestAnimationFrame(fn) {
    window.RAF_LISTENERS.push(fn);
    call_python('requestAnimationFrame', window._id);
  }

  function __runRAFHandlers() {
    var handlers_copy = window.RAF_LISTENERS;
    window.RAF_LISTENERS = [];

    for (var i = 0; i < handlers_copy.length; i++) {
      handlers_copy[i]();
    }
  }
}

Object.defineProperty(Window.prototype, 'parent', {
  configurable: true,
  get: function () {
    var parent_id = call_python('parent', this._id);
    if (parent_id != null) {
      var parent = WINDOWS[parent_id];

      /* 即使"parent != null", 这里获取的parent也不一定是same-origin的parent window
      (另见"Frame.window_id"的注释), 所以，js context中访问DOM的方法需要调用"JSContext.throw_if_cross_origin"
      检查是否same-origin */

      if (parent == null) {
        parent = new Window(parent_id);
      }
      return parent;
    }
  },
});

Window.prototype.addEventListener = function (type, listener) {
  if (!this.WINDOW_LISTENERS[type]) this.WINDOW_LISTENERS[type] = [];
  this.WINDOW_LISTENERS[type].push(listener);
};

Window.prototype.dispatchEvent = function (evt) {
  handlers = this.WINDOW_LISTENERS[evt.type] || [];

  for (var i = 0; i < handlers.length; i++) {
    handlers[i].call(this, evt);
  }
};

Window.prototype.postMessage = function (message, origin) {
  call_python('postMessage', this._id, message, origin);
};
