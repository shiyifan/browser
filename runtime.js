// 浏览器Javascript Runtime所需的变量

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
};

// 保存DOM node与event listener的对应关系: { DOM node handle: { eventType: eventHandler } }
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
Node.prototype.dispatchEvent = function (type) {
  var handle = this.handle;
  var list = (LISTENERS[handle] && LISTENERS[handle][type]) || [];
  for (var i = 0; i < list.length; i++) {
    list[i].call(this);
  }
};

Object.defineProperty(Node.prototype, 'innerHTML', {
  set: function (s) {
    call_python('innerHTML_set', this.handle, s.toString());
  },
});
