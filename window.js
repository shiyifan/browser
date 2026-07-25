// 全局对象window的类型：Window
function Window(id) {
  this._id = id;
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

Window.prototype.addEventListener = function (type, listener) {};

Window.prototype.dispatchEvent = function (evt) {};
