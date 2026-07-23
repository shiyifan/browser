var button = window.document.getElementById('button');
button.addEventListener('click', function () {
  console.log('c clicked');
});

window.setTimeout(function () {
  console.log('c timeout');
}, 2000);
