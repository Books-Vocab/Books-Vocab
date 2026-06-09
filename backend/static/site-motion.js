/* Books & Vocab public site — progressive-enhancement motion layer.
   No framework, no CDN. Everything degrades cleanly:
   - prefers-reduced-motion OR no IntersectionObserver → reveals show instantly.
   - no JS at all → CSS leaves .reveal visible (the reduced-motion @media also
     forces it), so content is never hidden behind JS.
   Consumes design tokens via the CSS classes it toggles (.is-in / .site-nav--scrolled). */
(function () {
  var reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  var els = Array.prototype.slice.call(document.querySelectorAll('.reveal'));

  if (reduce || !('IntersectionObserver' in window)) {
    els.forEach(function (e) { e.classList.add('is-in'); });
  } else {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-in');
          io.unobserve(entry.target);
        }
      });
    }, { threshold: 0.12, rootMargin: '0px 0px -8% 0px' });
    els.forEach(function (e) { io.observe(e); });
  }

  var nav = document.querySelector('.site-nav');
  if (nav) {
    var onScroll = function () {
      nav.classList.toggle('site-nav--scrolled', window.scrollY > 4);
    };
    onScroll();
    addEventListener('scroll', onScroll, { passive: true });
  }
})();
