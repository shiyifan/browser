var button = document.getElementById('button');

var count = 0;

button.addEventListener('click', function (e) {
  button.innerHTML = count++
});
