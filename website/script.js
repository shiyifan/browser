var a = document.querySelectorAll('a')[0];

a.addEventListener('click', function (e) {
  console.log('href clicked!');
  e.preventDefault()
});
