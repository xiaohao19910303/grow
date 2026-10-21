/* Keep page-end controls above the actual height of the floating task panels. */
(() => {
  const dock=document.getElementById('floatingPanels');
  const measure=()=>document.documentElement.style.setProperty('--floating-panels-height',dock.getBoundingClientRect().height+'px');
  new ResizeObserver(measure).observe(dock);
  window.addEventListener('resize',measure);
  measure();
})();
