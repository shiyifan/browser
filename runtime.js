// 浏览器Javascript Runtime所需的变量

console = {
  log: function () {
    var joined = Array.prototype.join.call(arguments, ' '); // 将多个参数合并为一个字符串
    call_python('log', joined); // 调用Python中导出的function'log'
  },
};

document = {
  querySelectorAll: function (s) {
    var handles = call_python('querySelectorAll', s);
    return handles.map(function (h) {
      return new Node(h);
    });
  },
};

// Javascript DOM node
function Node(handle) {
  this.handle = handle;
}
Node.prototype.getAttribute = function (attr) {
  return call_python('getAttribute', this.handle, attr);
};
