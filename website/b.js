var a = document.querySelectorAll('button')[0];
a.addEventListener('click', function () {
  console.log('b clicked');
});

setTimeout(function () {
  console.log('b timeout');
}, 1000);

window.b = 'This is b';

window.addEventListener('message', function (e) {
  console.log('message received! ', e.data);
});
