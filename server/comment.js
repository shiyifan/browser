var strong = document.querySelectorAll('strong')[0];

function lengthCheck() {
  var value = this.getAttribute('value');
  console.log("value length: ", value.length);
  if (value.length > 10) {
    strong.innerHTML = 'Too long!';
  } else {
    strong.innerHTML = '';
  }
}

var input = document.querySelectorAll('input')[0];
input.addEventListener('keydown', lengthCheck);
