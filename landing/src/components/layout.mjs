// @ts-check
import { html, raw } from '../lib/html.mjs';
import { LANGS, LANG_FLAGS, LANG_NAMES, lang, localPath, t } from '../lib/lang.mjs';
import { bob, sprite } from './glyphs.mjs';

/** Paths are written once, in their English form; Uzbek pages get the /uz prefix on the way out. */
export const NAV = [
  { href: '/', en: 'Overview', uz: 'Bosh sahifa' },
  { href: '/recorded-run', en: 'Test run', uz: 'Sinov natijasi' },
  { href: '/evidence', en: 'Strengths and limits', uz: 'Imkoniyat va cheklovlar' },
  { href: '/install', en: 'Get Plumb', uz: 'O‘rnatish' },
  { href: '/contact', en: 'Contact', uz: 'Aloqa' },
];

const chevron = raw('<svg class="chev" viewBox="0 0 12 12" aria-hidden="true"><path d="M2.5 4.5 6 8l3.5-3.5"/></svg>');
const tick = raw('<svg class="tick" viewBox="0 0 12 12" aria-hidden="true"><path d="M2.4 6.3 4.9 8.7 9.6 3.6"/></svg>');

/**
 * The day/night switch. The knob carries a sun that turns into a moon: its rays fold away and
 * a disc the colour of the knob slides over the core, leaving a crescent. The faint mark on
 * the track is the other mode, the one a click leads to.
 */
const themeIcon = raw(
  '<svg class="ts-icon" viewBox="0 0 24 24" aria-hidden="true">' +
    '<g class="ts-rays"><path d="M12 1.8v2.4M12 19.8v2.4M1.8 12h2.4M19.8 12h2.4M4.8 4.8l1.7 1.7M17.5 17.5l1.7 1.7M4.8 19.2l1.7-1.7M17.5 6.5l1.7-1.7"/></g>' +
    '<circle class="ts-core" cx="12" cy="12" r="4.6"/>' +
    '<circle class="ts-cover" cx="15.6" cy="8.6" r="6.3"/>' +
    '</svg>',
);
const sunHint = raw('<svg class="ts-hint ts-hint-day" viewBox="0 0 12 12" aria-hidden="true"><circle cx="6" cy="6" r="2.3"/><path d="M6 .9v1.3M6 9.8v1.3M.9 6h1.3M9.8 6h1.3M2.4 2.4l.9.9M8.7 8.7l.9.9M2.4 9.6l.9-.9M8.7 3.3l.9-.9"/></svg>');
const moonHint = raw('<svg class="ts-hint ts-hint-night" viewBox="0 0 12 12" aria-hidden="true"><path d="M9.9 7.6A4.3 4.3 0 0 1 4.4 2.1a4.3 4.3 0 1 0 5.5 5.5z"/></svg>');

const PAGE_ROOTS = new Set(NAV.map((item) => item.href.slice(1)));

const PRELOADED_FONTS = [
  'atkinson-hyperlegible-next-latin-400-normal.woff2',
  'atkinson-hyperlegible-next-latin-600-normal.woff2',
];

/**
 * @typedef {object} PageContext
 * @property {any} record   facts extracted from saved records
 * @property {any} site     hand-maintained details: public URL, repository, contact
 * @property {{ css: string, js: string }} assets
 * @property {{ day: string, night: string }} themeColor
 */

/** Points links between pages at the language being rendered. Language links are left alone. */
function localise(/** @type {string} */ markup) {
  if (lang() === 'en') return markup;
  return markup.replace(/<a\b([^>]*?)\shref="(\/[^"]*)"/g, (whole, before, href) => {
    if (before.includes('hreflang=')) return whole;
    const cut = href.search(/[#?]/);
    const pathname = cut < 0 ? href : href.slice(0, cut);
    if (!PAGE_ROOTS.has(pathname.slice(1).split('/')[0])) return whole;
    return `<a${before} href="${localPath(pathname)}${cut < 0 ? '' : href.slice(cut)}"`;
  });
}

/**
 * @param {object} options
 * @param {string} options.path language-neutral path, such as "/contact"
 * @param {string} options.title
 * @param {string} options.description
 * @param {import('../lib/html.mjs').Markup} options.body
 * @param {PageContext} options.context
 * @param {boolean} [options.index] false keeps the page out of search results
 */
export function page({ path, title, description, body, context, index = true }) {
  const { site, assets, themeColor } = context;
  const fullTitle = path === '/' ? title : `${title} · Plumb`;
  // The 404 page answers for every unknown address, so it has no address of its own.
  const own = path === '/404' ? '/' : path;
  const absolute = (/** @type {import('../lib/lang.mjs').Lang} */ language) =>
    `${site.url}${localPath(own, language) === '/' ? '' : localPath(own, language)}`;
  const current = (/** @type {string} */ href) => (href === '/' ? path === '/' : path === href || path.startsWith(`${href}/`));

  const head = site.url && index
    ? html`<meta property="og:url" content="${absolute(lang())}"><link rel="canonical" href="${absolute(lang())}">
${LANGS.map((language) => html`<link rel="alternate" hreflang="${language}" href="${absolute(language)}">`)}
<link rel="alternate" hreflang="x-default" href="${absolute('en')}">`
    : '';

  const document = html`<!doctype html>
<html lang="${lang()}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${fullTitle}</title>
<meta name="description" content="${description}">
${index ? '' : html`<meta name="robots" content="noindex">`}
<meta name="theme-color" content="${themeColor.day}" media="(prefers-color-scheme: light)" data-theme-color="day">
<meta name="theme-color" content="${themeColor.night}" media="(prefers-color-scheme: dark)" data-theme-color="night">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Plumb">
<meta property="og:locale" content="${t('en_GB', 'uz_UZ')}">
<meta property="og:title" content="${fullTitle}">
<meta property="og:description" content="${description}">
${head}
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
${PRELOADED_FONTS.map(
  (font) => html`<link rel="preload" href="/fonts/${font}" as="font" type="font/woff2" crossorigin>`,
)}
<link rel="stylesheet" href="${assets.css}">
<script src="${assets.js}"></script>
</head>
<body>
${sprite}
<a class="skip" href="#main">${t('Skip to content', 'Asosiy matnga o‘tish')}</a>
<header class="top">
  <div class="wrap top-row">
    <a class="wordmark" href="/" aria-label="${t('Plumb, overview', 'Plumb, bosh sahifa')}">${bob}plumb</a>
    <nav class="nav" aria-label="${t('Primary', 'Asosiy menyu')}">
      ${NAV.map(
        (item) =>
          html`<a href="${item.href}"${current(item.href) ? html` aria-current="page"` : ''}>${t(item.en, item.uz)}</a>`,
      )}
    </nav>
    <div class="tools">
      <details class="lang" data-lang-menu>
        <summary title="${t('Language', 'Til')}: ${LANG_NAMES[lang()]}"><img class="flag-icon" src="${LANG_FLAGS[lang()]}" alt="" width="22" height="22"><span class="sr-only">${t('Language', 'Til')}: ${LANG_NAMES[lang()]}</span>${chevron}</summary>
        <div class="lang-menu">
          ${LANGS.map(
            (language) =>
              html`<a hreflang="${language}" lang="${language}" href="${localPath(own, language)}"${language === lang() ? html` aria-current="true"` : ''}><img class="flag-icon" src="${LANG_FLAGS[language]}" alt="" width="22" height="22"><span>${LANG_NAMES[language]}</span>${language === lang() ? tick : ''}</a>`,
          )}
        </div>
      </details>
      <button class="theme-switch" type="button" role="switch" aria-checked="false" data-theme-switch data-to-day="${t('Switch to day mode', 'Kunduzgi rejimga o‘tish')}" data-to-night="${t('Switch to night mode', 'Tungi rejimga o‘tish')}" hidden><span class="sr-only">${t('Night mode', 'Tungi rejim')}</span><span class="ts-track" aria-hidden="true">${sunHint}${moonHint}<span class="ts-knob">${themeIcon}</span></span></button>
    </div>
  </div>
</header>
<main id="main">
${body}
</main>
<footer class="foot">
  <div class="wrap foot-grid">
    <div>
      <a class="wordmark" href="/" aria-label="${t('Plumb, overview', 'Plumb, bosh sahifa')}">${bob}plumb</a>
      <p class="small">${t(
        'Looks through a web app’s code for places where people can see data that is not theirs. Runs on your own computer. A working prototype.',
        'Veb-ilova kodidan foydalanuvchiga begona ma’lumot ochilib qoladigan joylarni qidiradi. O‘z kompyuteringizda ishlaydi. Ishlaydigan prototip.',
      )}</p>
      ${site.author ? html`<p class="small">${t(html`Built by ${site.author}.`, html`Muallif: ${site.author}.`)} <a href="/contact">${t('Write to me', 'Menga yozing')}</a></p>` : ''}
    </div>
    <nav class="foot-nav" aria-label="${t('Footer', 'Sahifa osti menyusi')}">
      ${NAV.map((item) => html`<a href="${item.href}">${t(item.en, item.uz)}</a>`)}
      <a href="/install/agent">${t('Install with an AI agent', 'SI agent orqali o‘rnatish')}</a>
    </nav>
    <p class="small colophon">${t(
      html`Set in Atkinson Hyperlegible Next and Mono from the Braille Institute, under the <a href="/fonts/Atkinson-Next-OFL.txt">SIL Open Font License</a>. The typeface keeps <span class="fact">l</span>, <span class="fact">1</span> and <span class="fact">I</span> apart, which matters when the text is evidence. This site sets no cookies and loads nothing from other servers.`,
      html`Matn Braille Institute’ning Atkinson Hyperlegible Next va Mono shriftlarida terilgan (<a href="/fonts/Atkinson-Next-OFL.txt">SIL Open Font License</a>). Bu shriftda <span class="fact">l</span>, <span class="fact">1</span> va <span class="fact">I</span> bir-biri bilan adashmaydi: matn dalil bo‘lib xizmat qilganda bu muhim. Sayt cookie saqlamaydi va boshqa serverlardan hech narsa yuklamaydi.`,
    )}</p>
  </div>
</footer>
</body>
</html>
`;
  return raw(localise(document.toString()));
}

/**
 * A section with its statement on the left and its content on the right.
 * @param {object} options
 * @param {string} options.id
 * @param {unknown} options.heading
 * @param {unknown} [options.intro]
 * @param {unknown} options.body
 */
export function band({ id, heading, intro, body }) {
  return html`<section class="band" aria-labelledby="${id}-h">
  <div class="wrap split">
    <div class="split-head">
      <h2 id="${id}-h">${heading}</h2>
      ${intro ? html`<div class="split-intro">${intro}</div>` : ''}
    </div>
    <div class="split-body" id="${id}">${body}</div>
  </div>
</section>`;
}
