// 浏览器Javascript Runtime所需的变量

console = {
  log: function (x) {
    call_python('log', x);
  },
};
