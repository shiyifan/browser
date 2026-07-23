var a = window.document.querySelectorAll('button')[0];
a.addEventListener('click', function () {
  console.log('b clicked');
});

window.setTimeout(function () {
  console.log('b timeout');
}, 1000);
