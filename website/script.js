console.log('before innerHTML');

var div = document.querySelectorAll('div')[0];

var button = document.querySelectorAll('button')[0];
button.addEventListener('click', function () {
  div.innerHTML = '<span>Hello InnerHTML</span>';
});

console.log('after innerHTML');
