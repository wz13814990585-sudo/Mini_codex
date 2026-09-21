const button = document.getElementById('increment');
const count = document.getElementById('count');

button.addEventListener('click', () => {
  count.textContent = String(Number(count.textContent) + 1);
});
