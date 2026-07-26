// console.log('hello script')

// var div = document.querySelectorAll('div')[0];

// var total_frames = 120;
// var current_frame = 0;

// function animate() {
//   current_frame++;

//   if (current_frame > total_frames) return false;

//   opacity = 0 + (current_frame / total_frames) * (1 - 0);
//   div.style = 'opacity: ' + opacity;
//   return true;
// }

// function run_animation_frame() {
//   if (animate()) {
//     requestAnimationFrame(run_animation_frame);
//   }
// }

// var beneath = document.getElementById('beneath');
// var top = document.getElementById('top');

// beneath.addEventListener('click', function () {
//   console.log('beneath clicked');
// });

// top.addEventListener('click', function () {
//   console.log('top clicked');
// });

var parent = window.document.getElementById('parent');
parent.addEventListener('click', function () {
  console.log('parent: ', window.parent.b);
  window.parent.postMessage('hello from script!', '*');
});

// requestAnimationFrame(run_animation_frame);

// var div = document.getElementById('fade');

// var button = document.getElementById('click');

// var op = 1;
// button.addEventListener('click', function () {
//   if (op === 1) {
//     op = 0.1;
//     div.style = 'opacity: 0.1';
//   } else {
//     op = 1;
//     div.style = 'opacity: 1';
//   }
// });
