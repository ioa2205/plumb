// Theme switch, language menu, copy buttons, the message form and the request list that
// plays itself. The site is complete without this file: the theme follows the device, the
// language menu opens as a plain disclosure, every command can be selected by hand, the
// request lists are simply there, and the form posts as an ordinary form.
(function () {
  'use strict';
  var root = document.documentElement;
  var KEY = 'plumb-theme';
  var dark = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
  var calm = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)').matches : true;

  // Marks the page as scripted before it is drawn, so a list that is going to play itself
  // starts out empty instead of flashing its rows first.
  if (!calm && 'IntersectionObserver' in window) root.classList.add('can-play');

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

    // Recorded request lists arrive row by row the first time they scroll into view, and
    // again on request.
    var tapes = document.querySelectorAll('[data-tape]');
    if (tapes.length && root.classList.contains('can-play')) {
      var play = function (tape) {
        tape.classList.remove('is-played');
        void tape.offsetWidth;
        tape.classList.add('is-played');
      };
      var watcher = new IntersectionObserver(
        function (entries) {
          entries.forEach(function (entry) {
            if (!entry.isIntersecting) return;
            watcher.unobserve(entry.target);
            play(entry.target);
          });
        },
        { rootMargin: '0px 0px -18% 0px', threshold: 0.05 }
      );
      tapes.forEach(function (tape) {
        watcher.observe(tape);
        var again = tape.querySelector('[data-tape-replay]');
        if (!again) return;
        again.hidden = false;
        again.addEventListener('click', function () {
          play(tape);
        });
      });
    }

    // Things that happen once, when they come into view: a red-pencil ring draws itself
    // (data-draw), a label is stamped on (data-reveal), and the three website requests are
    // sent one after another (data-lanes, which also draws its own ring).
    var once = function (selector, threshold, act) {
      var nodes = document.querySelectorAll(selector);
      if (!nodes.length || !root.classList.contains('can-play')) return;
      var watch = new IntersectionObserver(
        function (entries) {
          entries.forEach(function (entry) {
            if (!entry.isIntersecting) return;
            watch.unobserve(entry.target);
            act(entry.target);
          });
        },
        { rootMargin: '0px 0px -10% 0px', threshold: threshold }
      );
      nodes.forEach(function (node) {
        watch.observe(node);
      });
    };
    once('[data-draw]', 0.5, function (ring) {
      if (!ring.closest('[data-lanes]')) ring.classList.add('is-drawn');
    });
    once('[data-reveal]', 0.6, function (node) {
      node.classList.add('is-in');
    });
    // The parts list is tall on a phone, so it starts as soon as a little of it shows.
    once('[data-parts]', 0.12, function (node) {
      node.classList.add('is-in');
    });
    once('[data-lanes]', 0.45, function (box) {
      var send = function () {
        box.classList.add('is-in');
        box.querySelectorAll('[data-draw]').forEach(function (ring) {
          ring.classList.add('is-drawn');
        });
      };
      send();
      var again = box.querySelector('[data-lanes-replay]');
      if (!again) return;
      // Offered once the three requests have come back, not while they are on their way.
      setTimeout(function () {
        again.hidden = false;
      }, 5600);
      again.addEventListener('click', function () {
        box.classList.add('is-cut');
        box.classList.remove('is-in');
        box.querySelectorAll('[data-draw]').forEach(function (ring) {
          ring.classList.remove('is-drawn');
        });
        void box.offsetWidth;
        box.classList.remove('is-cut');
        send();
      });
    });

    // A plumb line in the margin of wide screens. Its bob hangs at the reader's place on the
    // page; moving the page sets it swinging, and it settles back to true when the page stops.
    var plumb = document.querySelector('[data-plumb]');
    if (plumb && root.classList.contains('can-play')) {
      var tilt = 0;
      var spin = 0;
      var lastY = window.scrollY;
      var lastAt = 0;
      var moving = false;
      var hang = function () {
        var room = document.documentElement.scrollHeight - window.innerHeight;
        var part = room > 0 ? Math.min(1, Math.max(0, window.scrollY / room)) : 0;
        var length = 96 + part * Math.max(0, window.innerHeight - 190);
        plumb.style.setProperty('--len', length.toFixed(1) + 'px');
        return length;
      };
      var swing = function (now) {
        var dt = lastAt ? Math.min(0.05, (now - lastAt) / 1000) : 1 / 60;
        lastAt = now;
        var y = window.scrollY;
        var speed = (y - lastY) / dt;
        lastY = y;
        // The bob never strays more than about 34 px sideways, however long the string.
        var limit = (Math.atan(34 / hang()) * 180) / Math.PI;
        var pull = Math.max(-limit, Math.min(limit, -speed * 0.006));
        spin += (64 * (pull - tilt) - 6.5 * spin) * dt;
        tilt += spin * dt;
        plumb.style.setProperty('--tilt', tilt.toFixed(3) + 'deg');
        if (speed === 0 && Math.abs(tilt) < 0.01 && Math.abs(spin) < 0.02) {
          moving = false;
          lastAt = 0;
          plumb.style.setProperty('--tilt', '0deg');
          return;
        }
        requestAnimationFrame(swing);
      };
      hang();
      window.addEventListener(
        'scroll',
        function () {
          if (moving) return;
          moving = true;
          requestAnimationFrame(swing);
        },
        { passive: true }
      );
      window.addEventListener('resize', hang);
    }

    // The walk-through on the front page: four chapters that play in order, a caption per
    // beat. It starts when it scrolls into view, waits while it is out of view, and stops at
    // the end. A chapter title jumps to that chapter.
    (function () {
    var film = document.querySelector('[data-film]');
    if (film && root.classList.contains('can-play')) {
      var chapters = Array.prototype.map.call(film.querySelectorAll('[data-chapter]'), function (node) {
        return {
          node: node,
          go: node.querySelector('[data-film-go]'),
          text: node.querySelector('.chapter-text'),
          captions: node.querySelectorAll('.captions > li'),
          stage: node.querySelector('.stage'),
          parts: node.querySelectorAll('.stage [data-from], .stage [data-to]'),
        };
      });
      var rail = film.querySelector('.film-rail');
      var toggleFilm = film.querySelector('[data-film-toggle]');
      var replay = film.querySelector('[data-film-replay]');
      var BEAT = 3600;
      var at = { chapter: -1, beat: 0, elapsed: 0 };
      var playing = false;
      var held = false; // paused by the reader, not by scrolling away
      var ended = false;
      var seen = false;
      var last = 0;

      var draw = function (chapter, beat) {
        chapter.stage.setAttribute('data-beat', String(beat + 1));
        chapter.parts.forEach(function (part) {
          var from = Number(part.getAttribute('data-from') || 1);
          var to = Number(part.getAttribute('data-to') || 99);
          part.classList.toggle('on', beat + 1 >= from && beat + 1 <= to);
          part.classList.toggle('was', beat + 1 > to);
        });
        chapter.captions.forEach(function (caption, index) {
          caption.classList.toggle('is-on', index === beat);
        });
      };

      var show = function (index, beat) {
        var chapter = chapters[index];
        if (index !== at.chapter) {
          chapters.forEach(function (other, position) {
            other.node.classList.toggle('is-active', position === index);
            if (position === index) other.go.setAttribute('aria-current', 'step');
            else other.go.removeAttribute('aria-current');
          });
          // A chapter always opens from its empty state, without animating backwards.
          chapter.stage.classList.add('is-cut');
          draw(chapter, -1);
          void chapter.stage.offsetWidth;
          chapter.stage.classList.remove('is-cut');
        }
        at = { chapter: index, beat: beat, elapsed: 0 };
        draw(chapter, beat);
        mark();
      };

      // Where the bob hangs: beside the current chapter, sliding towards the next one.
      var mark = function () {
        var chapter = chapters[at.chapter];
        if (!chapter) return;
        var part = Math.min(1, (at.beat + Math.min(1, at.elapsed / BEAT)) / chapter.captions.length);
        if (ended) part = 1;
        chapters.forEach(function (other, position) {
          other.go.style.setProperty('--p', String(position < at.chapter ? 1 : position === at.chapter ? part : 0));
        });
        if (!rail || !rail.offsetParent) return;
        var middle = function (entry) {
          return entry.go.parentElement.offsetTop + entry.go.parentElement.offsetHeight / 2 - 10;
        };
        var from = middle(chapter);
        var next = chapters[at.chapter + 1];
        var to = next ? middle(next) : chapter.text.offsetTop + chapter.text.offsetHeight - 26;
        rail.style.setProperty('--y', Math.round((from + (to - from) * part) * 10) / 10 + 'px');
      };

      var label = function () {
        toggleFilm.textContent = toggleFilm.getAttribute(playing ? 'data-pause' : 'data-play');
        toggleFilm.hidden = ended;
      };

      var frame = function (now) {
        if (!playing) return;
        at.elapsed += Math.min(120, now - last);
        last = now;
        if (at.elapsed >= BEAT) {
          var chapter = chapters[at.chapter];
          if (at.beat + 1 < chapter.captions.length) show(at.chapter, at.beat + 1);
          else if (at.chapter + 1 < chapters.length) show(at.chapter + 1, 0);
          else {
            ended = true;
            playing = false;
            mark();
            label();
            return;
          }
        }
        mark();
        requestAnimationFrame(frame);
      };

      var run = function () {
        if (playing || ended || held) return;
        playing = true;
        last = performance.now();
        label();
        requestAnimationFrame(frame);
      };
      var rest = function () {
        playing = false;
        label();
      };
      var start = function (index) {
        ended = false;
        held = false;
        show(index, 0);
        run();
      };

      chapters.forEach(function (chapter, index) {
        chapter.go.disabled = false;
        chapter.go.addEventListener('click', function () {
          start(index);
        });
      });
      toggleFilm.addEventListener('click', function () {
        held = playing;
        if (playing) rest();
        else run();
      });
      replay.addEventListener('click', function () {
        start(0);
      });
      film.querySelector('[data-film-controls]').hidden = false;
      show(0, 0);
      label();

      var inView = false;
      new IntersectionObserver(
        function (entries) {
          inView = entries[entries.length - 1].isIntersecting;
          if (inView) {
            if (!seen) {
              seen = true;
              start(0);
            } else run();
          } else if (playing) rest();
        },
        { threshold: 0.35 }
      ).observe(film);
      document.addEventListener('visibilitychange', function () {
        if (document.hidden) {
          if (playing) rest();
        } else if (inView) run();
      });
      window.addEventListener('resize', mark);
    }
    })();

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
