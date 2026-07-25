var button = window.document.getElementById('button');
button.addEventListener('click', function () {
  console.log('parent: ', window.parent.b)
});

window.setTimeout(function () {
  console.log('c timeout');
}, 2000);
