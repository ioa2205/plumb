// @ts-check
// The front page tells the whole story to someone who has never seen the product: what goes
// wrong, how Plumb finds it in the code, that it can also try a website or answer a plain
// question, why everything stays on the reader's computer, and how far the claims go. It
// shows more than it says. The detail lives on the pages it links to.
//
// The page is drawn like a marked-up technical drawing: ink for what is shown, blue pencil
// for what is not settled, and one red-pencil ring per section on the thing that is wrong.
// Every picture says which saved record it was drawn from.
import { film } from '../components/film.mjs';
import { glyph, ringed } from '../components/glyphs.mjs';
import { page } from '../components/layout.mjs';
import { fact, reportShot } from '../components/parts.mjs';
import { day, gb, longDay, seconds } from '../lib/format.mjs';
import { holds } from '../lib/holds.mjs';
import { html } from '../lib/html.mjs';
import { t } from '../lib/lang.mjs';
import { externalLimits } from '../lib/website-limits.mjs';

export const path = '/';

/**
 * The headline, word by word. Each word hangs from its top like a plumb bob and, with motion
 * allowed, drops in and swings to rest (site.css). The one phrase out of true settles a little
 * crooked and is ringed in red pencil. Without motion every word is simply at rest.
 * @param {(string | { odd: string, after?: string })[]} parts
 */
const hung = (parts) =>
  html`${parts.map((part, index) => html`${index ? ' ' : ''}${typeof part === 'string'
    ? html`<span class="w">${part}</span>`
    : html`<span class="w is-odd">${ringed(part.odd)}${part.after ?? ''}</span>`}`)}`;

/** @param {import('../components/layout.mjs').PageContext} context */
export function render(context) {
  const { record } = context;
  const { run, model, journey, chat, download } = record;
  const [receipt, invoice] = run.findings;
  const memory = `${Math.round(run.machine.total_memory_bytes / 1e9)} GB`;
  const count = (/** @type {string} */ conclusion) => run.findings.filter((/** @type {any} */ finding) => finding.conclusion === conclusion).length;

  holds(receipt.conclusion === 'supported' && invoice.conclusion === 'rejected', 'receipt supported, invoice rejected');
  holds(run.target_code_executed === false, 'app code executed: no');
  holds(run.proposal.status === 'refused', 'the fix proposal was refused');
  holds(run.machine.cpu.includes('i5-1135G7'), 'the recorded test ran on the laptop named on this site');
  // The website test: Plumb's own practice website, two synthetic customers, one label.
  holds(journey.mode === 'owned_fixture' && download.owned_website_completed === true, 'the website test ran on Plumb’s own practice website');
  holds(journey.owner_status === 200 && journey.other_status === 200 && journey.identical && journey.signed_out_status >= 400, 'both customers received the same label; signed out was refused');
  holds(journey.comparison === 'candidate' && journey.finding.conclusion === 'candidate' && journey.supported === 0, 'the website test left a lead, not a confirmed finding');
  holds(journey.requests <= journey.max_requests, 'the website test kept to its request limit');
  // The plain question: answered on this laptop, labelled general, and nothing changed.
  holds(/Nothing was run or approved/.test(chat.message) && /this is not a finding/.test(chat.basis), 'a plain question changes nothing and is not a finding');
  holds(download.model_planning_qualified === false, 'the AI model is not yet trusted to plan website steps');

  const hero = html`<section class="hero" aria-labelledby="hero-h">
  <div class="wrap">
    <h1 class="headline" id="hero-h">${t(
      hung(['Plumb', 'finds', 'where', 'your', 'app', 'shows', 'people', 'data', 'that', { odd: 'isn’t theirs', after: '.' }]),
      hung(['Plumb', 'ilovangizda', 'birovning', 'ma’lumoti', { odd: 'boshqasiga' }, 'ochilib', 'qoladigan', 'joylarni', 'topadi.']),
    )}</h1>
    <div class="hero-say">
      <p class="lede">${t(
        'It reads your app’s code on your own computer and points to the exact line. Nothing is uploaded.',
        'U ilovangiz kodini o‘z kompyuteringizda o‘qiydi va aynan qaysi qatorda xato borligini ko‘rsatadi. Hech narsa tashqariga yuborilmaydi.',
      )}</p>
      <p class="actions">
        <a class="btn btn-ink" href="/install">${t('Get Plumb', 'Plumbni o‘rnatish')}</a>
        <a class="btn" href="/how-it-works">${t('How it works', 'Qanday ishlaydi')}</a>
      </p>
    </div>
    <figure class="plate plate-film">
      <figcaption class="plate-cap"><span>${t('Read on a laptop', 'Noutbukda o‘qilgan')}</span><span>${t(`Recorded ${day(run.started_at)}`, `${day(run.started_at)} kuni yozib olingan`)}</span></figcaption>
      ${film(record)}
    </figure>
  </div>
</section>`;

  // Three people ask the practice website for the same parcel label, one after another. What
  // came back is the recorded status; the red pencil rings the answer that should have been no.
  const lane = (/** @type {{ kind: string, token: string, who: unknown, role: unknown, status: number, got: unknown, verdict: unknown }} */ entry) => html`<li class="lane ${entry.kind}">
          <p class="lane-who"><i class="token${entry.kind === 'is-owner' ? ' is-owner' : ''}" aria-hidden="true">${entry.token}</i><span><b>${entry.who}</b>${entry.role ? html` <span class="lane-role">${entry.role}</span>` : ''}</span></p>
          <p class="lane-track" aria-hidden="true"><span class="pkt">${t('label', 'yorliq')}</span><svg class="lane-site" viewBox="0 0 24 24"><rect x="2.5" y="4" width="19" height="16" rx="2.5"/><path d="M2.5 8.6h19M5.6 6.3h.01M8.2 6.3h.01"/></svg></p>
          <p class="lane-got">${entry.kind === 'is-gap' ? ringed(html`${fact(entry.status)} · ${entry.got}`) : html`${fact(entry.status)} · ${entry.got}`}</p>
          <p class="lane-verdict">${entry.kind === 'is-gap' ? glyph('ring') : glyph('dot')}<span>${entry.verdict}</span></p>
        </li>`;
  const website = html`<section class="band" aria-labelledby="site-h">
  <div class="wrap">
    <h2 class="say" id="site-h">${t(
      'Tests ask whether the app works. Plumb asks whether it refuses.',
      'Oddiy testlar ilova ishlashini tekshiradi. Plumb esa u rad eta olishini tekshiradi.',
    )}</h2>
    <figure class="plate plate-site">
      <figcaption class="plate-cap"><span>${t('No code needed: a website, two test accounts', 'Kod shart emas: sayt va ikki test hisobi')}</span><span lang="en">${journey.site} · ${day(journey.recorded_at)}</span></figcaption>
      <div class="lanes-box" data-lanes>
        <ol class="lanes">
          ${lane({ kind: 'is-owner', token: journey.owner[0], who: journey.owner, role: t('owner', 'egasi'), status: journey.owner_status, got: t('label', 'yorliq'), verdict: t('Allowed, as it should be.', 'Ruxsat berildi, to‘g‘ri.') })}
          ${lane({ kind: 'is-gap', token: journey.other[0], who: journey.other, role: t('another customer', 'boshqa mijoz'), status: journey.other_status, got: t('the same label', 'o‘sha yorliq'), verdict: t('Allowed. It should refuse.', 'Ruxsat berildi. Rad etishi kerak edi.') })}
          ${lane({ kind: 'is-out', token: '·', who: t('Signed out', 'Tizimga kirmagan'), role: '', status: journey.signed_out_status, got: t('refused', 'rad etildi'), verdict: t('Refused, as it should be.', 'Rad etildi, to‘g‘ri.') })}
        </ol>
        <button class="btn lanes-again" type="button" data-lanes-replay hidden>${t('Play again', 'Qayta ko‘rish')}</button>
      </div>
      <ol class="flow">
        <li>${t('You give the site, two accounts and limits.', 'Siz sayt, ikki hisob va cheklovlarni berasiz.')}</li>
        <li><strong>${t('Nothing is sent before you approve the plan.', 'Rejani tasdiqlamaguningizcha hech narsa yuborilmaydi.')}</strong></li>
        <li>${t('It asks for the same thing as both.', 'U ikkala hisobdan bir xil narsani so‘raydi.')}</li>
        <li>${t('It compares what each one got.', 'Har biri nima olganini solishtiradi.')}</li>
      </ol>
    </figure>
    <p class="status">${glyph('half')}<span>${t(
      html`On Plumb’s own practice website: ${fact(journey.findings)} leads, none confirmed. ${externalLimits(download)}`,
      html`Plumbning o‘z sinov saytida: ${fact(journey.findings)} ta iz, birortasi tasdiqlanmagan. ${externalLimits(download)}`,
    )}</span></p>
  </div>
</section>`;

  const firstSentence = chat.answer.slice(0, chat.answer.indexOf('. ') + 1);
  holds(firstSentence.length > 20 && chat.answer.startsWith(firstSentence), 'the quoted answer is the start of the recorded one');
  const asking = html`<section class="band band-sheet" aria-labelledby="ask-h">
  <div class="wrap ask-wrap">
    <h2 class="say" id="ask-h">${t('Or just ask, in plain words.', 'Yoki oddiy so‘zlar bilan so‘rang.')}</h2>
    <figure class="transcript">
      <figcaption class="plate-cap"><span>${t('Recorded exchange', 'Yozib olingan suhbat')}</span><span>${day(chat.recorded_at)}</span></figcaption>
      <div class="exchange">
        <p class="q" lang="en">${chat.prompt}</p>
        <p class="a" lang="en">${firstSentence} <span class="more-cut">…</span></p>
        <p class="basis" lang="en" data-reveal>${chat.basis}</p>
      </div>
      <p class="small transcript-foot">${t(
        html`Answered in ${fact(`${seconds(Number(chat.model_seconds.toFixed(1)))} s`)} on the laptop. Asking cannot start a test.`,
        html`Noutbukda ${fact(`${seconds(Number(chat.model_seconds.toFixed(1)))} s`)} ichida javob berildi. Savol sinovni boshlay olmaydi.`,
      )}</p>
    </figure>
  </div>
</section>`;

  const local = html`<section class="band band-ink" aria-labelledby="local-h">
  <div class="wrap local">
    <div class="local-say">
      <h2 class="say" id="local-h">${t('Your code never leaves your laptop.', 'Kodingiz noutbukingizdan tashqariga chiqmaydi.')}</h2>
      <p class="lede">${t(
        html`Its AI model is one ${gb(model.size)} file on your own computer.`,
        html`Uning SI modeli o‘z kompyuteringizdagi bitta ${gb(model.size)} hajmli fayl.`,
      )}</p>
      <ul class="points">
        <li>${t('Reading code needs no internet once set up.', 'O‘rnatilgach, kodni o‘qishga internet kerak emas.')}</li>
        <li>${t('A website test talks only to the site you approved.', 'Sayt sinovi faqat siz tasdiqlagan saytga murojaat qiladi.')}</li>
        <li>${t(`Has run on an ordinary laptop with ${memory} of memory.`, `${memory} operativ xotirali oddiy noutbukda ishlagan.`)}</li>
      </ul>
    </div>
    <svg class="local-art" data-reveal viewBox="0 0 520 320" role="img" aria-label="${t(
      'A laptop holding your code, the AI model and the report, with a plumb line dropped through all three. A dashed outline beside it stands for an online service, which is not used.',
      'Kodingiz, SI modeli va hisobot joylashgan noutbuk, uchalasidan shoqul ipi o‘tgan. Yonidagi uzuq chiziqli shakl onlayn xizmatni bildiradi, undan foydalanilmaydi.',
    )}">
      <rect class="la-bezel" x="8" y="6" width="316" height="262" rx="20"/>
      <rect class="la-screen" x="20" y="18" width="292" height="238" rx="10"/>
      <path class="la-bezel" d="M0 282h332l-10 20a8 8 0 0 1-7 4H17a8 8 0 0 1-7-4z"/>
      <g class="la-item"><rect x="36" y="34" width="260" height="60" rx="10"/><text x="56" y="72">${t('Your code', 'Kodingiz')}</text></g>
      <g class="la-item"><rect x="36" y="107" width="260" height="60" rx="10"/><text x="56" y="145">${t('AI model', 'SI modeli')}</text></g>
      <g class="la-item"><rect x="36" y="180" width="260" height="60" rx="10"/><text x="56" y="218">${t('Report', 'Hisobot')}</text></g>
      <g class="la-plumb"><path class="la-string" d="M268 18V196"/><path class="la-bob" d="M268 194l5.6 8.4-5.6 12.6-5.6-12.6z"/></g>
      <path class="la-wire" d="M332 137h20"/>
      <path class="la-cut" pathLength="1" d="M360 123l9 28M372 123l9 28"/>
      <path class="la-cloud" d="M412 172c-15 0-26-10-26-23 0-12 9-21 21-23 3-16 16-27 32-27 14 0 26 8 31 21 14 1 24 12 24 25 0 15-11 27-26 27z"/>
      <text class="la-off" x="446" y="206" text-anchor="middle">${t('Online service', 'Onlayn xizmat')}</text>
      <text class="la-off is-strong" x="446" y="230" text-anchor="middle">${t('not used', 'ishlatilmaydi')}</text>
    </svg>
  </div>
</section>`;

  // Every part of Plumb, set out like the parts list on a drawing. Each part carries the mark
  // the What it can do page gives it: ink when it has been shown working with a saved record,
  // blue pencil when it is built but not settled. With motion, ink fills each mark as far as its
  // part has been shown working, one part after another; without it the marks are simply full.
  const level = (/** @type {'dot' | 'half'} */ mark) => html`<svg class="lvl is-${mark}" viewBox="0 0 12 12" role="img" aria-label="${mark === 'dot' ? t('Shown working', 'Ishlashi ko‘rsatilgan') : t('Built, not settled', 'Qurilgan, hali tasdiqlanmagan')}"><circle class="lvl-o" cx="6" cy="6" r="4.1"/>${mark === 'dot' ? html`<circle class="lvl-f" cx="6" cy="6" r="4.6"/>` : html`<path class="lvl-f" d="M6 1.9a4.1 4.1 0 0 1 0 8.2z"/>`}</svg>`;
  /** @type {{ name: unknown, href: string, parts: ['dot' | 'half', unknown][] }[]} */
  const groups = [
    { name: t('Code', 'Kod'), href: '/what-it-does#can-code', parts: [
      ['dot', t('Map the code', 'Kod xaritasini tuzish')],
      ['dot', t('Find access flaws', 'Ruxsat xatolarini topish')],
      ['half', t('Other kinds of flaw', 'Boshqa turdagi xatolar')],
      ['half', t('Secrets, risky settings, vulnerable packages', 'Maxfiy kalitlar, xavfli sozlamalar, zaif paketlar')],
    ] },
    { name: t('Websites', 'Saytlar'), href: '/what-it-does#can-web', parts: [
      ['half', t('Test a website with test accounts', 'Saytni test hisoblari bilan sinash')],
      ['half', t('Judge saved replies', 'Saqlangan javoblarni baholash')],
      ['dot', t('Prove a flaw and its fix', 'Xato va tuzatishni isbotlash')],
    ] },
    { name: t('Questions', 'Savollar'), href: '/what-it-does#can-ask', parts: [
      ['half', t('Ask in plain words', 'Oddiy so‘zlar bilan so‘rash')],
      ['dot', t('Explain a saved finding', 'Saqlangan topilmani tushuntirish')],
    ] },
    { name: t('Results', 'Natijalar'), href: '/what-it-does#can-run', parts: [
      ['dot', t('Reports in four formats', 'To‘rt formatdagi hisobotlar')],
      ['half', t('Your decisions on findings', 'Topilmalar bo‘yicha qarorlaringiz')],
      ['dot', t('Read-only access for AI tools', 'SI vositalari uchun faqat o‘qish')],
      ['half', t('A workbench in your browser', 'Brauzerdagi interfeys')],
    ] },
  ];
  holds(record.signals.config_rules.length > 0 && record.signals.advisories > 0 && record.decisions.includes('resolved'), 'the signals and reviewer decisions the parts list names exist');
  const parts = html`<section class="band band-last" aria-labelledby="parts-h">
  <div class="wrap">
    <h2 class="say" id="parts-h">${t('Every part, and how far each has been checked.', 'Har bir qism va u qanchalik tekshirilgani.')}</h2>
    <figure class="plate plate-parts">
      <figcaption class="plate-cap"><span>${t('Parts list', 'Qismlar ro‘yxati')}</span><span class="parts-key"><span>${glyph('dot')}${t('Shown working', 'Ishlashi ko‘rsatilgan')}</span><span class="is-half">${glyph('half')}${t('Built, not settled', 'Qurilgan, hali tasdiqlanmagan')}</span></span></figcaption>
      <div class="parts" data-parts>
        ${groups.map((group) => html`<section class="parts-group">
          <h3><a href="${group.href}">${group.name}</a></h3>
          <ul>
            ${group.parts.map(([mark, name]) => html`<li>${level(mark)}<span>${name}</span></li>`)}
          </ul>
        </section>`)}
      </div>
    </figure>
    <p class="status is-ring">${glyph('ring')}<span>${t(
      html`<a href="/evidence">Not yet</a>: real projects, a second computer, and a website case settled by its AI model. An empty report never proves an app safe.`,
      html`<a href="/evidence">Hozircha yo‘q</a>: haqiqiy loyihalar, ikkinchi kompyuter va SI modeli aniq xulosaga kelgan birorta sayt holati. Bo‘sh hisobot ilova xavfsiz ekanini isbotlamaydi.`,
    )}</span></p>
    <p class="actions">
      <a class="btn btn-ink" href="/install">${t('Get Plumb', 'Plumbni o‘rnatish')}</a>
    </p>
  </div>
</section>`;

  const proof = html`<section class="band" aria-labelledby="proof-h">
  <div class="wrap">
    <div class="say-row">
      <h2 class="say" id="proof-h">${t('Every answer ends in a report you can check.', 'Har bir javob tekshirsa bo‘ladigan hisobot bilan tugaydi.')}</h2>
      <div>
        <p class="say-note">${t(
          'Not a mock-up: the file Plumb saved.',
          'Maket emas: Plumb saqlagan fayl.',
        )}</p>
        <p class="actions">
          <a class="btn btn-ink" href="/saved-report/report.html">${t('Open the report', 'Hisobotni ochish')}</a>
          <a class="btn" href="/recorded-run">${t('Follow the test', 'Sinovni kuzatish')}</a>
        </p>
      </div>
    </div>
    <figure class="plate plate-proof">
      <figcaption class="plate-cap"><span>${t('The saved report', 'Saqlangan hisobot')}</span><span>${longDay(run.started_at)}</span></figcaption>
      ${reportShot('summary', t(`The saved report: ${count('supported')} supported, ${count('rejected')} rejected, and the list of findings`, `Saqlangan hisobot: ${count('supported')} ta tasdiqlangan, ${count('rejected')} ta rad etilgan va topilmalar ro‘yxati`), [1152, 962])}
    </figure>
  </div>
</section>`;

  return page({
    path,
    title: t(
      'Plumb: finds where your app shows people data that isn’t theirs',
      'Plumb: ilovangizda birovning ma’lumoti boshqasiga ochilib qoladigan joylarni topadi',
    ),
    description: t(
      'Plumb works on your own computer with a small offline AI model. It reads a web app’s code, or tries the website with test accounts, to find places where one user can see another user’s data. A working prototype with recorded tests and stated limits.',
      'Plumb o‘z kompyuteringizda, internetsiz ishlaydigan kichik SI modeli bilan ishlaydi. Bir foydalanuvchi boshqasining ma’lumotlarini ko‘ra oladigan joylarni topish uchun veb-ilova kodini o‘qiydi yoki saytni test hisoblari bilan sinab ko‘radi. Yozib olingan sinovlari va ochiq aytilgan cheklovlari bilan ishlaydigan prototip.',
    ),
    body: html`<div class="home">${hero}${website}${asking}${local}${proof}${parts}</div>`,
    context,
  });
}
