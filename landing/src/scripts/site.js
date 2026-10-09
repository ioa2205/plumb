// Theme switch, language menu, copy buttons and the message form. The site is complete
// without this file: the theme follows the device, the language menu opens as a plain
// disclosure, every command can be selected by hand, and the form posts as an ordinary form.
(function () {
  'use strict';
  var root = document.documentElement;
  var KEY = 'plumb-theme';
  var dark = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;

  // With nothing stored the page follows the device. A stored "day" or "night" overrides it.
  function stored() {
    try {
      var value = localStorage.getItem(KEY);
      return value === 'day' || value === 'night' ? value : null;
    } catch (error) {
      return null;
    }
  }

  function device() {
    return dark && dark.matches ? 'night' : 'day';
  }

  function apply(choice) {
    if (choice) root.setAttribute('data-theme', choice);
    else root.removeAttribute('data-theme');
  }

  // Applied before first paint, so a chosen theme never flashes the other one.
  var choice = stored();
  apply(choice);

  document.addEventListener('DOMContentLoaded', function () {
    var toggle = document.querySelector('[data-theme-switch]');
    if (toggle) {
      var colours = document.querySelectorAll('meta[data-theme-color]');
      var defaults = {};
      colours.forEach(function (meta) {
        defaults[meta.getAttribute('data-theme-color')] = meta.getAttribute('content');
      });
      var show = function () {
        var mode = choice || device();
        toggle.setAttribute('aria-checked', String(mode === 'night'));
        toggle.title = toggle.getAttribute(mode === 'night' ? 'data-to-day' : 'data-to-night');
        // The browser's own chrome follows a chosen theme, not only the device setting.
        colours.forEach(function (meta) {
          meta.setAttribute('content', defaults[choice || meta.getAttribute('data-theme-color')]);
        });
      };
      toggle.hidden = false;
      show();
      toggle.addEventListener('click', function () {
        var next = (choice || device()) === 'night' ? 'day' : 'night';
        // Choosing what the device already shows hands control back to the device.
        choice = next === device() ? null : next;
        apply(choice);
        try {
          if (choice) localStorage.setItem(KEY, choice);
          else localStorage.removeItem(KEY);
        } catch (error) {
          /* The choice still holds for this page. */
        }
        show();
      });
      if (dark && dark.addEventListener) dark.addEventListener('change', show);
    }

    // The language menu is a <details> element; close it the way people expect a menu to close.
    var menu = document.querySelector('[data-lang-menu]');
    if (menu) {
      var summary = menu.querySelector('summary');
      var close = function (refocus) {
        if (!menu.open) return;
        menu.open = false;
        if (refocus) summary.focus();
      };
      document.addEventListener('click', function (event) {
        if (!menu.contains(event.target)) close(false);
      });
      menu.addEventListener('keydown', function (event) {
        if (event.key === 'Escape') close(true);
      });
      menu.addEventListener('focusout', function (event) {
        if (event.relatedTarget && !menu.contains(event.relatedTarget)) close(false);
      });
      // Both languages have the same sections, so the reader keeps their place.
      menu.querySelectorAll('a[hreflang]').forEach(function (link) {
        link.addEventListener('click', function () {
          if (location.hash && link.getAttribute('aria-current') !== 'true') link.hash = location.hash;
        });
      });
    }

    // On narrow screens the navigation scrolls sideways; keep the current page in view.
    var here = document.querySelector('.nav [aria-current="page"]');
    if (here && here.parentElement.scrollWidth > here.parentElement.clientWidth) {
      here.parentElement.scrollLeft = here.offsetLeft - here.parentElement.offsetLeft - 16;
    }

    var form = document.querySelector('[data-message-form]');
    if (form && window.fetch) {
      var status = form.querySelector('[data-form-status]');
      var submit = form.querySelector('button[type="submit"]');
      var say = function (key, kind) {
        status.textContent = form.getAttribute('data-' + key);
        status.setAttribute('data-kind', kind || '');
      };
      var reasons = { invalid: 'invalid', rate_limited: 'limited', not_configured: 'unavailable' };
      form.addEventListener('submit', function (event) {
        event.preventDefault();
        var fields = {};
        new FormData(form).forEach(function (value, name) {
          fields[name] = String(value);
        });
        submit.disabled = true;
        say('sending');
        fetch(form.getAttribute('action'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(fields),
        })
          .then(function (response) {
            return response.json();
          })
          .then(function (result) {
            if (result.ok) {
              say(result.preview ? 'preview' : 'sent', 'ok');
              form.reset();
            } else {
              say(reasons[result.error] || 'failed', 'bad');
            }
          })
          .catch(function () {
            say('failed', 'bad');
          })
          .then(function () {
            submit.disabled = false;
          });
      });
    }

    if (!navigator.clipboard) return;
    document.querySelectorAll('[data-copy]').forEach(function (button) {
      var source = document.getElementById(button.getAttribute('data-copy'));
      if (!source) return;
      var label = button.textContent;
      button.hidden = false;
      button.addEventListener('click', function () {
        navigator.clipboard.writeText(source.textContent).then(function () {
          button.textContent = button.getAttribute('data-done') || label;
          setTimeout(function () {
            button.textContent = label;
          }, 1600);
        });
      });
    });
  });
})();
