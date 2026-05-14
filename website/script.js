console.log('Hello');

var b = document.querySelectorAll('button')[0];

b.addEventListener('click', function () {
  var xhr = new XMLHttpRequest();
  xhr.open('GET', 'https://localhost:8000/test', true);
  xhr.onload = function () {
    console.log('request finished: ', this.responseText);
  };

  xhr.send();
});

var anim = document.getElementById('anim');
var count = 0;

function cb() {
  anim.innerHTML = 'count: ' + count++;
  if (count < 100) {
    requestAnimationFrame(cb);
  }
}

requestAnimationFrame(cb);
