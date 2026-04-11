var x = 3;

console.log('hello js!', 'hello second');

var nodes = document.querySelectorAll('form');
var action = nodes[0].getAttribute('action');
var input = document.querySelectorAll('input')[0];
var type = input.getAttribute('type')
console.log(action, type);
