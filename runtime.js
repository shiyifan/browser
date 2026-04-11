// 浏览器Javascript Runtime所需的变量

console = {
  log: function (x) {
    call_python('log', x); // 调用Python中导出的function'log'
  },
};

document = {
  querySelectorAll: function (s) {
    return call_python('querySelectorAll', s);
  },
};
