var div = document.querySelectorAll('div')[0];

var total_frames = 120;
var current_frame = 0;

function animate() {
  current_frame++;

  if (current_frame > total_frames) return false;

  opacity = 0 + (current_frame / total_frames) * (1 - 0);
  div.style = 'opacity: ' + opacity;
  return true;
}

function run_animation_frame() {
  if (animate()) {
    requestAnimationFrame(run_animation_frame);
  }
}

// requestAnimationFrame(run_animation_frame);

var div = document.getElementById('fade');

var button = document.getElementById('click');

button.addEventListener('click', function () {
  div.style = 'opacity: 0.1';
});
