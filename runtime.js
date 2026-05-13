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

var console = {
  log: function () {
    var joined = Array.prototype.join.call(arguments, ' '); // 将多个参数合并为一个字符串
    call_python('log', joined); // 调用Python中导出的function'log'
  },
};

var document = {
  querySelectorAll: function (s) {
    var handles = call_python('querySelectorAll', s);
    return handles.map(function (h) {
      return new Node(h);
    });
  },
  getElementById: function (id) {
    var handle = call_python('getElementById', id);
    return handle == null ? null : new Node(handle);
  },
};

// 保存DOM node与event listener的对应关系: { DOM node handle: { eventType: [eventHandler] } }
var LISTENERS = {};

// Javascript DOM node
function Node(handle) {
  // 关于Javascript DOM node的所有操作都通过这个handle与Python中的DOM node进行交互
  // 所以Node对象没有任何属性，所有属性均通过调用Python中的函数来获取
  this.handle = handle;
}

Node.prototype.getAttribute = function (attr) {
  return call_python('getAttribute', this.handle, attr);
};

Node.prototype.addEventListener = function (type, listener) {
  if (!LISTENERS[this.handle]) LISTENERS[this.handle] = {};

  var dict = LISTENERS[this.handle];
  if (!dict[type]) dict[type] = []; // 可以对同一个事件类型添加多个listener
  var list = dict[type];
  list.push(listener);
};

// 触发Node对象的某一类型事件
Node.prototype.dispatchEvent = function (evt) {
  var type = evt.type;
  var handle = this.handle;
  var list = (LISTENERS[handle] && LISTENERS[handle][type]) || [];
  for (var i = 0; i < list.length; i++) {
    list[i].call(this, evt);
  }

  /* 事件处理完成后，是否继续执行default后续流程
  只要有一个event handler调用了"preventDefault()"，那么后续流程将不会执行 */
  return evt.do_default;
};

Object.defineProperty(Node.prototype, 'innerHTML', {
  set: function (s) {
    call_python('innerHTML_set', this.handle, s.toString());
  },
});

function Event(type) {
  this.type = type;
  this.do_default = true; // 是否执行默认的后续流程
}

Event.prototype.preventDefault = function () {
  this.do_default = false;
};

/* XHR与handle间的对应关系: handle -> XHR. 用于实现异步xhr请求。
当浏览器利用多线程完成请求时，Python中根据handle触发xhr对象上的onload事件 */
XHR_REQUESTS = {};

// XMLHttpRequest对象
function XMLHttpRequest() {
  this.handle = Object.keys(XHR_REQUESTS).length;
  XHR_REQUESTS[this.handle] = this;
}

XMLHttpRequest.prototype.open = function (method, url, is_async) {
  this.is_async = is_async;
  this.method = method;
  this.url = url;
};

XMLHttpRequest.prototype.send = function (body) {
  this.responseText = call_python('XMLHttpRequest_send', this.method, this.url, body, this.is_async, this.handle);
};

// 保存setTimeout的callback与handle的对应关系, handle -> callback
SET_TIMEOUT_REQUESTS = {};

function setTimeout(callback, time_delta) {
  var handle = Object.keys(SET_TIMEOUT_REQUESTS).length;
  SET_TIMEOUT_REQUESTS[handle] = callback;
  call_python('setTimeout', handle, time_delta);
}

// 由Python调用，执行setTimeout的callback
function __runSetTimeout(handle) {
  var callback = SET_TIMEOUT_REQUESTS[handle];
  callback();

  /* 这里没有从SET_TIMEOUT_REQUESTS中删除callback,可能会导致memory leak */
}

// 由Python调用，异步请求完成后触发xhr对象的'onload'事件
function __runXHROnload(body, handle) {
  var obj = XHR_REQUESTS[handle];
  var evt = new Event('load');
  obj.responseText = body;
  if (obj.onload) {
    obj.onload(evt);
  }
}
