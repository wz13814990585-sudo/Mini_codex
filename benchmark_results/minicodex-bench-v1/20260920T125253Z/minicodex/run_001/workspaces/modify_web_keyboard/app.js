const state = document.getElementById('state');

document.addEventListener('keydown', (event) => {
  if (event.key === 'ArrowLeft') {
    state.textContent = 'left';
  }
});
