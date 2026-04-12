var x = 3;

console.log('hello js!', 'hello second');

var input = document.querySelectorAll('input')[0];

input.addEventListener('keydown', function () {
  console.log('input event!');
});

input.addEventListener('click', function () {
  console.log('input clicked!');
});
