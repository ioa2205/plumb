// @ts-check
// The front page tells the whole story to someone who has never seen the product: what goes
// wrong, how Plumb finds it, why the code stays on the reader's computer, and how far the
// claims go. It shows more than it says. The detail lives on the pages it links to.
import { film } from '../components/film.mjs';
import { glyph, pencilMark } from '../components/glyphs.mjs';
import { page } from '../components/layout.mjs';
import { reportShot } from '../components/parts.mjs';
import { day, gb } from '../lib/format.mjs';
import { holds } from '../lib/holds.mjs';
import { html } from '../lib/html.mjs';
import { t } from '../lib/lang.mjs';
import { websiteLimits } from '../lib/website-limits.mjs';

export const path = '/';

/** @param {import('../components/layout.mjs').PageContext} context */
export function render(context) {
  const { record } = context;
  const { run, model, collection, observation_comparison: comparison, download } = record;
  const [receipt, invoice] = run.findings;
  const memory = `${Math.round(run.machine.total_memory_bytes / 1e9)} GB`;
  const count = (/** @type {string} */ conclusion) => run.findings.filter((/** @type {any} */ finding) => finding.conclusion === conclusion).length;
  const reads = collection.actions.filter((/** @type {any} */ action) => action.purpose === 'read' && /\/receipt$/.test(action.path));
  const asked = (/** @type {string} */ account) => reads.find((/** @type {any} */ action) => action.account === account);

  holds(receipt.conclusion === 'supported' && invoice.conclusion === 'rejected', 'receipt supported, invoice rejected');
  holds(run.target_code_executed === false, 'app code executed: no');
  holds(run.proposal.status === 'refused', 'the fix proposal was refused');
  holds(run.machine.cpu.includes('i5-1135G7'), 'the recorded test ran on the laptop named on this site');
  // Two recorded replies to the same address: the owner's, and the other customer's.
  holds(reads.length === 2 && asked('alice').path === asked('bob').path, 'both accounts asked for the same receipt');
  holds(asked('alice').status === 200 && asked('alice').marker_present === true, 'the owner got her own receipt');
  holds(asked('bob').status === 200 && asked('bob').marker_present === true, 'the other customer got it too');
  holds(collection.external_access === false && collection.loopback_only && collection.runner === 'hash_pinned_owned_tandir', 'requests go only to the bundled practice app on the same computer');
  websiteLimits(download);
  holds(comparison.acceptance_met === false && comparison.conditions.every((/** @type {any} */ entry) => entry.conclusion === 'inconclusive'), 'every recorded judgment of the replies ended Inconclusive');

  const hero = html`<section class="home-hero" aria-labelledby="hero-h">
  <div class="wrap">
    <div class="home-top">
      <h1 class="headline" id="hero-h">${t(
        'Plumb finds where your app shows people data that isn’t theirs.',
        'Plumb ilovangizda birovning ma’lumoti boshqasiga ochilib qoladigan joylarni topadi.',
      )}</h1>
      <div class="home-say">
        <p class="lede">${t(
          'It reads your app’s code on your own computer and points to the exact line. Nothing is uploaded.',
          'U ilovangiz kodini o‘z kompyuteringizda o‘qiydi va aynan qaysi qatorda xato borligini ko‘rsatadi. Hech narsa tashqariga yuborilmaydi.',
        )}</p>
        <p class="actions">
          <a class="btn btn-ink" href="/install">${t('Get Plumb', 'Plumbni o‘rnatish')}</a>
          <a class="btn" href="/how-it-works">${t('How it works', 'Qanday ishlaydi')}</a>
        </p>
      </div>
    </div>
    ${film(record)}
  </div>
</section>`;

  const asks = html`<section class="band" aria-labelledby="asks-h">
  <div class="wrap">
    <h2 class="say" id="asks-h">${t(
      'Tests ask whether the app works. Plumb asks whether it refuses.',
      'Oddiy testlar ilova ishlashini tekshiradi. Plumb esa u rad eta olishini tekshiradi.',
    )}</h2>
    <div class="asks">
      <div class="ask">
        <p class="ask-k">${t('What a test usually asks', 'Odatda test nimani so‘raydi')}</p>
        <p class="ask-q"><i class="token is-owner" aria-hidden="true">A</i>${t('Can Alice open her own receipt?', 'Alice o‘z chekini ocha oladimi?')}</p>
        <p class="ask-a">${glyph('dot')}<span>${t('Yes. As it should be.', 'Ha. Shunday bo‘lishi kerak.')}</span></p>
      </div>
      <div class="ask is-gap">
        <p class="ask-k">${t('What Plumb asks', 'Plumb nimani so‘raydi')}</p>
        <p class="ask-q"><i class="token" aria-hidden="true">B</i>${t('Can Bob open Alice’s receipt?', 'Bob Alice’ning chekini ocha oladimi?')}</p>
        <p class="ask-a"><span class="mark">${glyph('ring')}${pencilMark}</span><span>${t('Yes. It should have been no.', 'Ha. Aslida yo‘q bo‘lishi kerak edi.')}</span></p>
      </div>
    </div>
    <p class="small asks-note">${t(
      `Both answers were recorded on Plumb’s own practice app on ${day(collection.recorded_at)}.`,
      `Ikkala javob ham ${day(collection.recorded_at)} kuni Plumbning o‘z sinov ilovasida yozib olingan.`,
    )} ${websiteLimits(download)}</p>
  </div>
</section>`;

  const local = html`<section class="band" aria-labelledby="local-h">
  <div class="wrap local">
    <div class="local-say">
      <h2 class="say" id="local-h">${t('Your code never leaves your laptop.', 'Kodingiz noutbukingizdan tashqariga chiqmaydi.')}</h2>
      <p class="lede">${t(
        html`Plumb is a program, not a website. Its AI model is one ${gb(model.size)} file that runs on your own computer, so there is no online service to send anything to.`,
        html`Plumb veb-sayt emas, dastur. Uning SI modeli o‘z kompyuteringizda ishlaydigan bitta ${gb(model.size)} hajmli fayl, shuning uchun biror narsa yuboriladigan onlayn xizmatning o‘zi yo‘q.`,
      )}</p>
      <ul class="points">
        <li>${t('Needs no internet once it is set up.', 'O‘rnatib bo‘lingach, internet kerak emas.')}</li>
        <li>${t(`Has run on an ordinary laptop with ${memory} of memory.`, `${memory} operativ xotirali oddiy noutbukda ishlagan.`)}</li>
        <li>${t(
          'Made for small teams with nobody to check their code, and for code that must not leave the company.',
          'Kodini tekshiradigan mutaxassisi yo‘q kichik jamoalar va kompaniyadan tashqariga chiqmasligi kerak bo‘lgan kod uchun.',
        )}</li>
      </ul>
    </div>
    <svg class="local-art" viewBox="0 0 520 320" role="img" aria-label="${t(
      'A laptop holding your code, the AI model and the report. A dashed outline beside it stands for an online service, which is not used.',
      'Kodingiz, SI modeli va hisobot joylashgan noutbuk. Yonidagi uzuq chiziqli shakl onlayn xizmatni bildiradi, undan foydalanilmaydi.',
    )}">
      <rect class="la-bezel" x="8" y="6" width="316" height="262" rx="20"/>
      <rect class="la-screen" x="20" y="18" width="292" height="238" rx="10"/>
      <path class="la-bezel" d="M0 282h332l-10 20a8 8 0 0 1-7 4H17a8 8 0 0 1-7-4z"/>
      <g class="la-item"><rect x="36" y="34" width="260" height="60" rx="10"/><text x="56" y="72">${t('Your code', 'Kodingiz')}</text></g>
      <g class="la-item"><rect x="36" y="107" width="260" height="60" rx="10"/><text x="56" y="145">${t('AI model', 'SI modeli')}</text></g>
      <g class="la-item"><rect x="36" y="180" width="260" height="60" rx="10"/><text x="56" y="218">${t('Report', 'Hisobot')}</text></g>
      <path class="la-wire" d="M332 137h20"/>
      <path class="la-cut" d="M360 123l9 28M372 123l9 28"/>
      <path class="la-cloud" d="M412 172c-15 0-26-10-26-23 0-12 9-21 21-23 3-16 16-27 32-27 14 0 26 8 31 21 14 1 24 12 24 25 0 15-11 27-26 27z"/>
      <text class="la-off" x="446" y="206" text-anchor="middle">${t('Online service', 'Onlayn xizmat')}</text>
      <text class="la-off is-strong" x="446" y="230" text-anchor="middle">${t('not used', 'ishlatilmaydi')}</text>
    </svg>
  </div>
</section>`;

  const honest = html`<section class="band" aria-labelledby="honest-h">
  <div class="wrap">
    <h2 class="say" id="honest-h">${t('What it can do, and what it can’t yet.', 'Nimani qila oladi va nimani hali qila olmaydi.')}</h2>
    <ul class="standings">
      <li>
        <p class="standings-k">${glyph('dot')}${t('Shown working', 'Ishlashi ko‘rsatilgan')}</p>
        <p>${t(
          'Reading an app’s code. It found a flaw planted on purpose and cleared the protected lookalike, on one practice app and one laptop.',
          'Ilova kodini o‘qib tekshirish. U ataylab qoldirilgan xatoni topdi va himoyalangan o‘xshash joyni oqladi: bitta sinov ilovasida, bitta noutbukda.',
        )}</p>
      </li>
      <li>
        <p class="standings-k">${glyph('half')}${t('Built, not settled', 'Qurilgan, hali tasdiqlanmagan')}</p>
        <p>${t(
          'Judging an app from its answers alone. It is built, and its AI model has not settled a case yet.',
          'Ilovani faqat javoblariga qarab baholash. Bu qism qurilgan, lekin SI modeli unda hali birorta holat bo‘yicha aniq xulosaga kelmagan.',
        )}</p>
      </li>
      <li>
        <p class="standings-k">${glyph('ring')}${t('Not yet', 'Hozircha yo‘q')}</p>
        <p>${t(
          'It has not been measured on real projects. It does not fix the code for you. An empty report does not prove an app is safe.',
          'U haqiqiy loyihalarda o‘lchanmagan. Kodni siz uchun tuzatmaydi. Hisobotning bo‘sh chiqishi ilova xavfsiz ekanini isbotlamaydi.',
        )}</p>
      </li>
    </ul>
    <p class="more"><a href="/evidence">${t('Every strength and limit, with the records behind them', 'Barcha imkoniyat va cheklovlar, ularning yozuvlari bilan')}</a></p>
  </div>
</section>`;

  const proof = html`<section class="band" aria-labelledby="proof-h">
  <div class="wrap">
    <div class="proof-say">
      <h2 class="say" id="proof-h">${t('This is the report from that test.', 'Bu o‘sha sinovning hisoboti.')}</h2>
      <div>
        <p class="lede">${t(
          'A picture of the file Plumb saved, not a mock-up. Plumb is a working prototype for Windows.',
          'Bu maket emas, Plumb saqlagan faylning rasmi. Plumb Windows uchun ishlaydigan prototip.',
        )}</p>
        <p class="actions">
          <a class="btn btn-ink" href="/saved-report/report.html">${t('Open the report', 'Hisobotni ochish')}</a>
          <a class="btn" href="/recorded-run">${t('Follow the test step by step', 'Sinovni qadam-baqadam ko‘rish')}</a>
        </p>
      </div>
    </div>
    <figure class="proof-figure">
      ${reportShot('summary', t(`The saved report: ${count('supported')} supported, ${count('rejected')} rejected, and the list of findings`, `Saqlangan hisobot: ${count('supported')} ta tasdiqlangan, ${count('rejected')} ta rad etilgan va topilmalar ro‘yxati`), [1152, 962])}
    </figure>
  </div>
</section>`;

  const next = html`<section class="band band-last" aria-labelledby="next-h">
  <div class="wrap">
    <h2 class="say" id="next-h">${t('Go deeper.', 'Batafsil.')}</h2>
    <div class="next doors">
      <a class="next-link" href="/how-it-works"><span class="next-title">${t('How it works', 'Qanday ishlaydi')}</span><span class="small">${t('The four steps behind every answer.', 'Har bir javob ortidagi to‘rt qadam.')}</span></a>
      <a class="next-link" href="/what-it-does"><span class="next-title">${t('What it can do', 'Imkoniyatlar')}</span><span class="small">${t('Every part of the tool and its command.', 'Vositaning har bir qismi va buyrug‘i.')}</span></a>
      <a class="next-link" href="/recorded-run"><span class="next-title">${t('See it work', 'Amalda ko‘rish')}</span><span class="small">${t('Two recorded cases, step by step.', 'Yozib olingan ikki holat, qadam-baqadam.')}</span></a>
      <a class="next-link" href="/install"><span class="next-title">${t('Get Plumb', 'O‘rnatish')}</span><span class="small">${t('Download it, or let an AI agent install it.', 'Yuklab oling yoki SI agentga o‘rnattiring.')}</span></a>
    </div>
  </div>
</section>`;

  return page({
    path,
    title: t(
      'Plumb: finds where your app shows people data that isn’t theirs',
      'Plumb: ilovangizda birovning ma’lumoti boshqasiga ochilib qoladigan joylarni topadi',
    ),
    description: t(
      'Plumb works on your own computer with a small offline AI model. It reads a web app’s code, or the answers the app gives, to find places where one user can see another user’s data. A working prototype with recorded tests and stated limits.',
      'Plumb o‘z kompyuteringizda, internetsiz ishlaydigan kichik SI modeli bilan ishlaydi. Bir foydalanuvchi boshqasining ma’lumotlarini ko‘ra oladigan joylarni topish uchun veb-ilova kodini yoki ilova bergan javoblarni o‘rganadi. Yozib olingan sinovlari va ochiq aytilgan cheklovlari bilan ishlaydigan prototip.',
    ),
    body: html`<div class="home">${hero}${asks}${local}${honest}${proof}${next}</div>`,
    context,
  });
}
