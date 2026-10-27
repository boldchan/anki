document.addEventListener("keydown", e => {
  const b = document.querySelector('[data-key="' + e.key + '"]');
  if (b) { e.preventDefault(); b.click(); }
});