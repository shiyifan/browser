console.log('before innerHTML');

var input = document.querySelectorAll('input')[0];

var span = document.querySelectorAll('span')[0];

input.addEventListener('keydown', function () {
  var v = this.getAttribute('value');
  if (v && v.length > 10) {
    span.innerHTML = 'Too Long!';
  } else {
    span.innerHTML = '';
  }
});

console.log('after innerHTML');
