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

/* 由于Dukpy Javascript Runtime无法修改global object, 并且为了支持多个"same origin 'Frame'"下同一js context中
   多个"window"对象的实现，所有的js代码(包括页面的js代码)引用web环境中global变量时（例如console, document, Node以及一些内部变量
   "LISTENERS", "RAF_LISTENERS", "SET_TIMEOUT_REQUESTS"等）需要显式指定"window",
   引用非web环境的global变量（例如Array, Object等）时则无需指定 */

console = {
  log: function () {
    var joined = Array.prototype.join.call(arguments, ' '); // 将多个参数合并为一个字符串
    call_python('log', joined); // 调用Python中导出的function'log'
  },
};

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

window.document = {
  querySelectorAll: function (s) {
    var handles = call_python('querySelectorAll', s, window._id);
    return handles.map(function (h) {
      return new window.Node(h);
    });
  },
  getElementById: function (id) {
    var handle = call_python('getElementById', id, window._id);
    return handle == null ? null : new window.Node(handle);
  },
};

// 保存DOM node与event listener的对应关系: { DOM node handle: { eventType: [eventHandler] } }
window.LISTENERS = {};

// Javascript DOM node
window.Node = function (handle) {
  // 关于Javascript DOM node的所有操作都通过这个handle与Python中的DOM node进行交互
  // 所以Node对象没有任何属性，所有属性均通过调用Python中的函数来获取
  this.handle = handle;
};

window.Node.prototype.getAttribute = function (attr) {
  return call_python('getAttribute', this.handle, attr, window._id);
};

window.Node.prototype.addEventListener = function (type, listener) {
  if (!window.LISTENERS[this.handle]) window.LISTENERS[this.handle] = {};

  var dict = window.LISTENERS[this.handle];
  if (!dict[type]) dict[type] = []; // 可以对同一个事件类型添加多个listener
  var list = dict[type];
  list.push(listener);
};

// 触发Node对象的某一类型事件.
// 主要用于在Python中调用DOM node通过'addEventListener()'注册的listener function.
window.Node.prototype.dispatchEvent = function (evt) {
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

window.Node.prototype.setAttribute = function (attr, value) {
  return call_python('setAttribute', this.handle, attr, value, window._id);
};

Object.defineProperty(window.Node.prototype, 'innerHTML', {
  set: function (s) {
    call_python('innerHTML_set', this.handle, s.toString(), window._id);
  },
});

Object.defineProperty(window.Node.prototype, 'style', {
  set: function (s) {
    call_python('style_set', this.handle, s.toString(), window._id);
  },
});

window.Event = function (type) {
  this.type = type;
  this.do_default = true; // 是否执行默认的后续流程
};

window.Event.prototype.preventDefault = function () {
  this.do_default = false;
};

/* XHR与handle间的对应关系: handle -> XHR. 用于实现异步xhr请求。
当浏览器利用多线程完成请求时，Python中根据handle触发xhr对象上的onload事件 */
window.XHR_REQUESTS = {};

// XMLHttpRequest对象
window.XMLHttpRequest = function () {
  this.handle = Object.keys(window.XHR_REQUESTS).length;
  window.XHR_REQUESTS[this.handle] = this;
};

window.XMLHttpRequest.prototype.open = function (method, url, is_async) {
  this.is_async = is_async;
  this.method = method;
  this.url = url;
};

window.XMLHttpRequest.prototype.send = function (body) {
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

// 保存setTimeout的callback与handle的对应关系, handle -> callback
window.SET_TIMEOUT_REQUESTS = {};

window.setTimeout = function (callback, time_delta) {
  var handle = Object.keys(window.SET_TIMEOUT_REQUESTS).length;
  window.SET_TIMEOUT_REQUESTS[handle] = callback;
  call_python('setTimeout', handle, time_delta, window._id);
};

// 由Python调用，执行setTimeout的callback
window.__runSetTimeout = function (handle) {
  var callback = window.SET_TIMEOUT_REQUESTS[handle];
  callback();

  /* 这里没有从window.SET_TIMEOUT_REQUESTS中删除callback,可能会导致memory leak */
};

// 由Python调用，异步请求完成后触发xhr对象的'onload'事件
window.__runXHROnload = function (body, handle) {
  var obj = window.XHR_REQUESTS[handle];
  var evt = new window.Event('load');
  obj.responseText = body;
  if (obj.onload) {
    obj.onload(evt);
  }
};

/* 保存animation frame的callback */
window.RAF_LISTENERS = [];

window.requestAnimationFrame = function (fn) {
  window.RAF_LISTENERS.push(fn);
  call_python('requestAnimationFrame', window._id);
};

window.__runRAFHandlers = function () {
  var handlers_copy = window.RAF_LISTENERS;
  window.RAF_LISTENERS = [];

  for (var i = 0; i < handlers_copy.length; i++) {
    handlers_copy[i]();
  }
};
