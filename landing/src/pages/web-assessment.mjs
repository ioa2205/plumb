// @ts-check
// The second way of looking: judging an app by what it answers, without its code. This page
// follows the one collection on record, request by request, and says how far the AI model got
// with that evidence. Web observations are their own kind of evidence: they are never shown
// as a source finding or as a runtime check.

import { bobEnd, glyph } from '../components/glyphs.mjs';
import { band, page } from '../components/layout.mjs';
import { caseTabs, command, fact, factWhole, inShort, standing, workbenchShot } from '../components/parts.mjs';
import { tape, who } from '../components/trace.mjs';
import { day, int, longDay, minutes, seconds } from '../lib/format.mjs';
import { holds } from '../lib/holds.mjs';
import { html } from '../lib/html.mjs';
import { t } from '../lib/lang.mjs';
import { websiteLimits } from '../lib/website-limits.mjs';

export const path = '/web-assessment';

/** A bar for one measured duration against its limit, drawn with attributes only. */
function bar(/** @type {number} */ value, /** @type {number} */ limit, /** @type {string} */ label) {
  const width = Math.min(value, limit).toFixed(1);
  return html`<svg class="${value >= limit ? 'timebar is-full' : 'timebar'}" viewBox="0 0 ${limit} 8" preserveAspectRatio="none" role="img" aria-label="${label}"><rect class="timebar-track" width="${limit}" height="8"/><rect class="timebar-fill" width="${width}" height="8"/></svg>`;
}

/** @param {import('../components/layout.mjs').PageContext} context */
export function render(context) {
  const { record } = context;
  const { collection, observation_comparison: comparison, cards, report_drafts: drafts, workbench_views: views, download, run } = record;
  const { limits } = collection;
  const reads = collection.actions.filter((/** @type {any} */ action) => action.purpose === 'read');
  const read = (/** @type {string} */ account, /** @type {string} */ kind) => reads.filter((/** @type {any} */ action) => action.account === account && action.path.endsWith(`/${kind}`));
  const paths = [...new Set(collection.actions.map((/** @type {any} */ action) => action.template))];
  const receiptCases = comparison.conditions.filter((/** @type {any} */ entry) => entry.case === 'receipt-issue');
  const invoiceCases = comparison.conditions.filter((/** @type {any} */ entry) => entry.case === 'invoice-protected');
  const by = Object.fromEntries(receiptCases.map((/** @type {any} */ entry) => [entry.approach, entry]));
  const hours = Math.round(limits.permission_hours);
  const refused = receiptCases.filter((/** @type {any} */ entry) => entry.stop_reason === 'ValueError').length;
  const correct = comparison.conditions.filter((/** @type {any} */ entry) => entry.correct).length;
  const elapsed = `${seconds(Number(collection.seconds.toFixed(2)))} s`;

  holds(collection.external_access === false && collection.loopback_only && collection.runner === 'hash_pinned_owned_tandir', 'requests went only to the bundled practice app on the same computer');
  holds(collection.model_loaded === false && collection.runtime_verification === 'not_attempted', 'collecting replies loads no model and proves nothing by itself');
  holds(collection.human_review === 'pending' && collection.imported === false, 'the collected replies wait for a person and were not imported');
  holds(collection.requests === 9 && collection.actions.length === 9, 'nine requests were planned and sent');
  holds(collection.actions.filter((/** @type {any} */ action) => !action.kept).every((/** @type {any} */ action) => ['readiness', 'authenticate'].includes(action.purpose)), 'only the readiness check and the sign-ins are not kept');
  holds(Math.abs(limits.permission_hours - hours) < 0.01 && hours === 4, 'the approval lasted four hours');
  holds(read('alice', 'receipt')[0].status === 200 && read('bob', 'receipt')[0].status === 200 && read('bob', 'receipt')[0].marker_present, 'Bob received Alice’s receipt');
  holds(read('alice', 'invoice')[0].status === 200 && read('bob', 'invoice').length === 2 && read('bob', 'invoice').every((/** @type {any} */ action) => action.status === 404), 'the invoice refused Bob twice and answered Alice');
  holds(comparison.acceptance_met === false && comparison.baseline_retained, 'no way of presenting the evidence was promoted');
  holds(comparison.approaches.join() === 'baseline,facts,decomposed,facts_guidance' && receiptCases.length === 4, 'four ways were compared on the receipt evidence');
  holds(receiptCases.every((/** @type {any} */ entry) => entry.expected === 'supported' && entry.conclusion === 'inconclusive'), 'the expected answer was Supported and every answer was Inconclusive');
  holds(by.facts.stop_reason === null && by.facts.answers === 3 && by.facts.attempts === 3, 'the sorted-facts run gave three valid answers');
  holds(by.baseline.stop_reason === 'ValueError' && by.decomposed.stop_reason === 'ValueError' && by.baseline.answers === 2 && by.decomposed.answers === 2, 'two runs stopped after an answer was refused');
  holds(by.facts_guidance.stop_reason === 'BudgetStop' && by.facts_guidance.answers === 2 && by.facts_guidance.attempts === 3, 'the run with a card ran out of time before its third answer');
  holds(invoiceCases.length === 1 && invoiceCases[0].approach === 'baseline' && invoiceCases[0].stop_reason === 'ModelUnavailable' && invoiceCases[0].answers === 1, 'the protected invoice was tried once and cut off');
  holds(comparison.unrun === 7 && comparison.planned === 12 && !comparison.conditions.some((/** @type {any} */ entry) => entry.case === 'receipt-adversarial'), 'seven of twelve planned conditions never ran, including every misleading-text case');
  holds(comparison.limits.condition_seconds === 300 && comparison.limits.condition_attempts === 3 && comparison.limits.retries === 0, 'three attempts and 300 seconds per condition, no retries');
  holds(comparison.model === run.model.id, 'the comparison used the same AI model as the recorded review');
  holds(by.facts.wall_seconds > by.baseline.wall_seconds && refused === 2 && correct === 0, 'sorted facts took longer, two answers were refused, and no verdict was correct');
  holds(cards.cards.length === 3 && comparison.guidance_card === cards.cards[0].id, 'three cards exist and the first was the one compared');
  holds(new Set(cards.cards.flatMap((/** @type {any} */ card) => card.sources.map((/** @type {any} */ source) => source.version))).size === 2, 'the cards draw on two OWASP documents');
  holds(drafts.published === false && drafts.synthetic_only && drafts.count === 12, 'twelve drafts from made-up cases, none exported');
  holds(download.features.website_missing_runner_refused, 'the legacy Tandir collector still requires its separate runner');
  websiteLimits(download);
  holds(views.screens.includes('website-url') && views.fresh_model_acceptance === false, 'the assessment screen was captured with display fixtures');

  const head = html`<header class="page-head">
  <div class="wrap">
    ${caseTabs('answers')}
    <h1>${t('Web assessment: checking an app by its answers', 'Veb-tekshiruv: ilovani javoblariga qarab tekshirish')}</h1>
    <p class="lede">${t(
      'Sometimes there is no code to read, only a running app. Plumb can then work from what the app answers: the same request sent as two different people, compared against a rule you state. This page follows the one collection on record, on Plumb’s own practice app, and says plainly how far the AI model got with it.',
      'Ba’zan o‘qiydigan kod bo‘lmaydi, faqat ishlab turgan ilova bo‘ladi. Shunda Plumb ilova bergan javoblar asosida ishlay oladi: bitta so‘rov ikki xil odam nomidan yuboriladi va javoblar siz aytgan qoida bilan solishtiriladi. Bu sahifada Plumbning o‘z sinov ilovasida yozib olingan yagona so‘rovlar to‘plami ko‘rsatiladi va SI modeli u bilan qayergacha yetgani ochiq aytiladi.',
    )}</p>
    <p class="condition page-condition">${t(
      html`<strong>Experimental, and limited on purpose.</strong> ${websiteLimits(download)} On the evidence below, the AI model has not reached a verdict yet.`,
      html`<strong>Tajriba bosqichida va ataylab cheklangan.</strong> ${websiteLimits(download)} Quyidagi dalillar bo‘yicha SI modeli hali aniq xulosaga kelmagan.`,
    )}</p>
    ${inShort([
      t('With no code to read, Plumb compares what two accounts get back from the same address.', 'O‘qiydigan kod bo‘lmasa, Plumb ikki hisob bitta manzildan qanday javob olganini solishtiradi.'),
      t(html`One collection is on record: ${collection.requests} requests to Plumb’s own practice app. In it, Bob receives Alice’s receipt.`, html`Bitta so‘rovlar to‘plami qayd etilgan: Plumbning o‘z sinov ilovasiga ${collection.requests} ta so‘rov. Unda Bob Alice’ning chekini oladi.`),
      t(html`The AI model judged that evidence ${comparison.approaches.length} ways and reached no verdict.`, html`SI modeli bu dalillarni ${comparison.approaches.length} xil usulda baholadi va aniq xulosaga kelmadi.`),
    ])}
  </div>
</header>`;

  const scope = band({
    id: 'scope',
    heading: t('First you say what is allowed.', 'Avval nimaga ruxsat borligini aytasiz.'),
    intro: html`<p>${t(
      'Nothing is sent until a scope is saved. A question typed to the AI model can never widen it. These are the limits of the recorded collection.',
      'Qamrov saqlanmaguncha hech narsa yuborilmaydi. SI modeliga yozilgan savol uni hech qachon kengaytira olmaydi. Quyida yozib olingan so‘rovlar to‘plamining chegaralari berilgan.',
    )}</p>`,
    body: html`<div class="sheet scope">
      <dl class="scope-list">
        <div><dt>${t('Which app', 'Qaysi ilova')}</dt><dd>${t(
          'Tandir, the practice app that comes with Plumb, started on this computer for the occasion. Its files are compared with pinned fingerprints before it starts.',
          'Tandir — Plumb bilan birga keladigan sinov ilovasi. U aynan shu ish uchun shu kompyuterda ishga tushiriladi. Ishga tushishidan oldin fayllari oldindan belgilangan barmoq izlari bilan solishtiriladi.',
        )}</dd></div>
        <div><dt>${t('As whom', 'Kim nomidan')}</dt><dd><span class="scope-who">${who('alice')}${who('bob')}</span> ${t(
          'Two made-up customers of the practice app. Their passwords are kept out of the evidence.',
          'Sinov ilovasining ikki soxta mijozi. Ularning parollari dalillarga kiritilmaydi.',
        )}</dd></div>
        <div><dt>${t('Which addresses', 'Qaysi manzillar')}</dt><dd lang="en">${paths.map((/** @type {string} */ entry, /** @type {number} */ index) => html`${index ? ' ' : ''}<span class="fact chip">${entry}</span>`)}</dd></div>
        <div><dt>${t('What it may touch', 'Nimaga tegishi mumkin')}</dt><dd>${t(
          html`One made-up order, created for the test and labelled <span class="fact" lang="en">${collection.marker}</span>, so it cannot be mistaken for real data.`,
          html`Sinov uchun yaratilgan bitta soxta buyurtma. Uni haqiqiy ma’lumot bilan adashtirmaslik uchun unga <span class="fact" lang="en">${collection.marker}</span> yorlig‘i qo‘yilgan.`,
        )}</dd></div>
        <div><dt>${t('How much', 'Qancha')}</dt><dd>${t(
          html`At most ${fact(limits.requests)} requests in ${fact(limits.seconds)} seconds. At most ${fact(int(limits.response_bytes))} bytes from one reply and ${fact(int(limits.total_bytes))} in all.`,
          html`${fact(limits.seconds)} soniya ichida ko‘pi bilan ${fact(limits.requests)} ta so‘rov. Bitta javobdan ko‘pi bilan ${fact(int(limits.response_bytes))} bayt, jami ${fact(int(limits.total_bytes))} bayt.`,
        )}</dd></div>
        <div><dt>${t('Until when', 'Qachongacha')}</dt><dd>${t(
          html`The approval runs out after ${fact(hours)} hours.`,
          html`Ruxsat ${fact(hours)} soatdan keyin o‘z kuchini yo‘qotadi.`,
        )}</dd></div>
        <div><dt>${t('It stops when', 'Qachon to‘xtaydi')}</dt><dd>${t(
          'A limit is reached, the app redirects somewhere else, an address outside the list appears, or a reply carries personal data nobody expected.',
          'Chegaraga yetilganda, ilova boshqa joyga yo‘naltirganda, ro‘yxatda yo‘q manzil paydo bo‘lganda yoki javobda hech kim kutmagan shaxsiy ma’lumot uchraganda.',
        )}</dd></div>
      </dl>
    </div>`,
  });

  const trace = html`<section class="band" id="trace" aria-labelledby="trace-h">
  <div class="wrap">
    <div class="lead-in">
      <h2 id="trace-h">${t('Then Plumb shows its plan. You approve it once.', 'Keyin Plumb rejasini ko‘rsatadi. Siz uni bir marta tasdiqlaysiz.')}</h2>
      <div class="prose">
        ${t(
          html`<p>Every request is listed before it is sent: the address, the account and whether it changes anything. An approval is tied to that exact plan and is used up by one run. If a run is interrupted, a new plan and a new approval are needed.</p>
        <p>This is the recorded run of ${longDay(collection.recorded_at)}: ${fact(collection.requests)} requests, sent in order. In this exercise the approval was given by the developer for a fixed test plan.</p>`,
          html`<p>Har bir so‘rov yuborilishidan oldin ro‘yxatda ko‘rsatiladi: manzili, qaysi hisobdan yuborilishi va biror narsani o‘zgartirish-o‘zgartirmasligi. Ruxsat aynan shu rejaga bog‘lanadi va bitta ishga tushirishda sarflanadi. Ish uzilib qolsa, yangi reja va yangi ruxsat kerak bo‘ladi.</p>
        <p>Quyida ${longDay(collection.recorded_at)} kuni yozib olingan ishga tushirish berilgan: tartib bilan yuborilgan ${fact(collection.requests)} ta so‘rov. Bu mashqda ruxsatni dasturchi oldindan belgilangan sinov rejasi uchun bergan.</p>`,
        )}
      </div>
    </div>
    <div class="tape-wide">
      ${tape(collection, { totals: true })}
    </div>
    <ul class="after-tape">
      <li>${glyph('ring')}<span>${t(
        html`<strong>Not evidence yet.</strong> The collected replies wait until a person has read them. In the record that review is still ${fact(collection.human_review)}, and nothing was imported.`,
        html`<strong>Hali dalil emas.</strong> Yig‘ilgan javoblar ularni odam o‘qib chiqmaguncha kutib turadi. Yozuvda bu ko‘rib chiqish hali bajarilmagan (${fact(collection.human_review)}), hech narsa import qilinmagan.`,
      )}</span></li>
      <li>${glyph('ring')}<span>${t(
        html`<strong>No AI model.</strong> Collecting replies loads no model and judges nothing. Runtime check: <span class="unproven">not attempted</span>.`,
        html`<strong>SI modeli ishlatilmagan.</strong> Javob yig‘ishda model yuklanmaydi va hech narsa baholanmaydi. Jonli sinov: <span class="unproven">o‘tkazilmagan</span>.`,
      )}</span></li>
      <li>${glyph('ring')}<span>${t(
        html`<strong>From source only.</strong> The download does not carry the practice app’s runner and refuses this step.`,
        html`<strong>Faqat manba kodidan.</strong> Tayyor to‘plamda sinov ilovasini ishga tushiruvchi qism yo‘q, shuning uchun u bu qadamni rad etadi.`,
      )}</span></li>
    </ul>
  </div>
</section>`;

  const cell = (/** @type {any[]} */ answers, /** @type {boolean} */ wrong) =>
    html`${answers.map((/** @type {any} */ action, /** @type {number} */ index) => html`${index ? ', ' : ''}${fact(action.status)}`)} ${wrong
      ? html`<span class="out-bad">${t('got the order', 'buyurtmani oldi')}</span>`
      : answers[0].status === 200
        ? t('got the order', 'buyurtmani oldi')
        : html`<span lang="en">${fact(answers[0].detail)}</span>`}`;
  const askedAlice = t('Alice, who placed the order', 'Buyurtma bergan Alice');
  const askedBob = t('Bob, another customer', 'Boshqa mijoz Bob');

  const compare = band({
    id: 'compare',
    heading: t('What the answers show.', 'Javoblar nimani ko‘rsatadi.'),
    intro: html`<p>${t(
      'One order, two people, two addresses. The rule the owner of the app states: only the person who placed an order may read it.',
      'Bitta buyurtma, ikki odam, ikki manzil. Ilova egasi aytgan qoida: buyurtmani faqat uni bergan odam o‘qiy oladi.',
    )}</p>`,
    body: html`<div class="stack-gap">
      <table class="plain stack answers">
        <caption class="sr-only">${t('What each account received from each address', 'Har bir hisob har bir manzildan qanday javob olgani')}</caption>
        <thead><tr><th scope="col">${t('Address', 'Manzil')}</th><th scope="col">${askedAlice}</th><th scope="col">${askedBob}</th></tr></thead>
        <tbody>
          <tr class="is-leak"><th scope="row"><span class="fact" lang="en">${read('bob', 'receipt')[0].path}</span></th><td data-label="${askedAlice}">${cell(read('alice', 'receipt'), false)}</td><td data-label="${askedBob}">${cell(read('bob', 'receipt'), true)}</td></tr>
          <tr><th scope="row"><span class="fact" lang="en">${read('bob', 'invoice')[0].path}</span></th><td data-label="${askedAlice}">${cell(read('alice', 'invoice'), false)}</td><td data-label="${askedBob}">${cell(read('bob', 'invoice'), false)}</td></tr>
        </tbody>
      </table>
      <div class="prose">
        ${t(
          html`<p>The receipt gave Bob an order that is not his. The invoice refused him, twice, and still served Alice. The invoice is the control: it shows the app can refuse, so the receipt’s answer is not just how this app treats everyone.</p>
        <p>This is an <strong>observation</strong>: what the app answered on one occasion. It does not show why. The reason is in the code, and the <a href="/recorded-run">code review found it from the other side</a>, at the line that loads the order by its number alone.</p>`,
          html`<p>Chek manzili Bobga o‘ziniki bo‘lmagan buyurtmani berdi. Hisob-faktura manzili esa uni ikki marta rad etdi, Alice’ga esa avvalgidek javob qaytardi. Hisob-faktura bu yerda nazorat vazifasini bajaradi: u ilova rad eta olishini ko‘rsatadi, demak chek manzilining javobi bu ilova hammaga shunday javob berishidan emas.</p>
        <p>Bu <strong>kuzatuv</strong>: ilova bir safar nima deb javob bergani. U sababni ko‘rsatmaydi. Sabab kodda, va <a href="/recorded-run">kod tekshiruvi uni boshqa tomondan topgan</a>: buyurtmani faqat raqami bo‘yicha yuklaydigan qatorda.</p>`,
        )}
      </div>
    </div>`,
  });

  const APPROACH = {
    baseline: {
      name: t('As collected', 'Yig‘ilgan holicha'),
      what: t('The requests and replies as they were saved.', 'So‘rov va javoblar qanday saqlangan bo‘lsa, shunday beriladi.'),
    },
    facts: {
      name: t('Facts sorted first', 'Faktlar avval saralangan'),
      what: t('Who asked, in which session, at which address and what came back, laid out before the question.', 'Kim so‘ragani, qaysi seansda, qaysi manzilga va nima javob kelgani savoldan oldin tartiblab beriladi.'),
    },
    decomposed: {
      name: t('Question in smaller parts', 'Savol kichik qismlarga bo‘lingan'),
      what: t('Each judgment first names the facts it relies on, then answers.', 'Har bir bahoda model avval tayangan faktlarini aytadi, keyin javob beradi.'),
    },
    facts_guidance: {
      name: t('Sorted facts and a method card', 'Saralangan faktlar va uslubiy karta'),
      what: t('The same sorted facts, with one method card added.', 'O‘sha saralangan faktlar, ustiga bitta uslubiy karta qo‘shilgan.'),
    },
  };
  const ended = (/** @type {any} */ entry) =>
    entry.stop_reason === null
      ? t('Three valid answers. All three said Inconclusive.', 'Uchta yaroqli javob. Uchalasi ham «Noaniq» dedi.')
      : entry.stop_reason === 'BudgetStop'
        ? t(
            html`Two answers, then the limit of ${fact(comparison.limits.condition_seconds)} seconds ran out before the third.`,
            html`Ikkita javob, so‘ng uchinchisidan oldin ${fact(comparison.limits.condition_seconds)} soniyalik chegara tugadi.`,
          )
        : t('An answer did not pass Plumb’s checks and was refused, so the case stopped.', 'Javoblardan biri Plumb tekshiruvidan o‘tmadi va rad etildi, shu bilan holat to‘xtatildi.');
  const timeWords = t('Time used', 'Sarflangan vaqt');
  const answersWords = t('Answers', 'Javoblar');
  const endedWords = t('How it ended', 'Qanday tugadi');

  const judged = html`<section class="band" id="judged" aria-labelledby="judged-h">
  <div class="wrap">
    <div class="lead-in">
      <h2 id="judged-h">${t('Then the AI model judges. So far it has not settled this.', 'Keyin SI modeli baho beradi. Hozircha u aniq xulosaga kelmadi.')}</h2>
      <div class="prose">
        ${t(
          html`<p>The model gets a small packet: the replies, the rule and the control. It must answer three separate times and point to the exact fields it relies on. All three must agree, or the result is Inconclusive.</p>
        <p>On ${longDay(comparison.recorded_at)} the receipt evidence above was put to the model in ${fact(comparison.approaches.length)} different ways, on the same laptop and with the same AI model as the code review. The right answer was Supported.</p>`,
          html`<p>Modelga kichik to‘plam beriladi: javoblar, qoida va nazorat manzili. U uch marta alohida javob berishi va tayangan maydonlarini aniq ko‘rsatishi shart. Uchala javob bir xil chiqishi kerak, aks holda natija «Noaniq» bo‘ladi.</p>
        <p>${longDay(comparison.recorded_at)} kuni yuqoridagi chek dalillari modelga ${fact(comparison.approaches.length)} xil usulda berildi. Noutbuk ham, SI modeli ham kod tekshiruvidagi bilan bir xil edi. To‘g‘ri javob «Tasdiqlandi» edi.</p>`,
        )}
      </div>
    </div>
    <div class="sheet approaches">
      <table class="plain stack approach-table">
        <caption class="sr-only">${t('Four ways of presenting the receipt evidence, and how each ended', 'Chek dalillarini berishning to‘rt usuli va har biri qanday tugagani')}</caption>
        <thead><tr><th scope="col">${t('How the evidence was presented', 'Dalillar qanday berilgan')}</th><th scope="col">${answersWords}</th><th scope="col">${timeWords}</th><th scope="col">${endedWords}</th></tr></thead>
        <tbody>
          ${comparison.approaches.map((/** @type {keyof typeof APPROACH} */ id) => {
            const entry = by[id];
            const spent = `${Math.round(entry.wall_seconds)} s`;
            return html`<tr>
            <th scope="row"><span class="approach-name">${APPROACH[id].name}</span><span class="approach-what">${APPROACH[id].what}</span></th>
            <td data-label="${answersWords}">${t(html`${fact(entry.answers)} of ${fact(entry.attempts)}`, html`${fact(entry.attempts)} tadan ${fact(entry.answers)} tasi`)}</td>
            <td data-label="${timeWords}"><span class="fact">${spent}</span>${bar(entry.wall_seconds, comparison.limits.condition_seconds, t(`${spent} of a ${comparison.limits.condition_seconds}-second limit`, `${comparison.limits.condition_seconds} soniyalik chegaradan ${spent}`))}</td>
            <td data-label="${endedWords}"><span class="verdict-inline">${glyph('half')}<strong>${t('Inconclusive', 'Noaniq')}</strong></span> ${ended(entry)}</td>
          </tr>`;
          })}
        </tbody>
      </table>
      <p class="small approach-key">${t(
        html`Each bar runs to the limit of ${fact(comparison.limits.condition_seconds)} seconds per case. Up to ${fact(comparison.limits.condition_attempts)} answers per case, with no retries.`,
        html`Har bir chiziqning to‘liq uzunligi bitta holat uchun belgilangan ${fact(comparison.limits.condition_seconds)} soniyalik chegarani bildiradi. Har bir holat uchun ko‘pi bilan ${fact(comparison.limits.condition_attempts)} ta javob, qayta urinishsiz.`,
      )}</p>
    </div>
    <div class="outcome">
      <div>
        <h3>${t('What this adds up to', 'Bundan chiqadigan xulosa')}</h3>
        <ul class="limits">
          ${t(
            html`<li><strong>No correct verdict, and no wrong one.</strong> The model never said Supported, which was the right answer. It also never cleared the receipt. It kept saying it could not tell.</li>
          <li><strong>Nothing did better than the plain way.</strong> Sorting the facts first did not produce a verdict, and it took longer. Plumb’s own checks refused ${fact(refused)} of the answers. The plain way stays the default.</li>
          <li><strong>Most of the plan never ran.</strong> ${fact(comparison.unrun)} of ${fact(comparison.planned)} planned cases were not reached, including every case with misleading text planted in a reply. The protected invoice was tried once: one answer, Inconclusive, then it was cut off when the whole run was stopped at a limit.</li>`,
            html`<li><strong>To‘g‘ri xulosa ham, xato xulosa ham yo‘q.</strong> Model biror marta ham to‘g‘ri javobni, ya’ni «Tasdiqlandi»ni aytmadi. Chekni oqlab ham yubormadi. U har safar aniq ayta olmasligini bildirdi.</li>
          <li><strong>Hech bir usul oddiy usuldan yaxshi chiqmadi.</strong> Faktlarni avval saralab berish aniq xulosa bermadi, vaqt esa ko‘proq ketdi. Javoblarning ${fact(refused)} tasini Plumbning o‘z tekshiruvi rad etdi. Asosiy usul bo‘lib oddiy usul qolmoqda.</li>
          <li><strong>Rejaning katta qismi bajarilmay qoldi.</strong> Rejalashtirilgan ${fact(comparison.planned)} ta holatdan ${fact(comparison.unrun)} tasiga navbat yetmadi, jumladan javobiga chalg‘ituvchi matn qo‘shilgan holatlarning birortasiga ham. Himoyalangan hisob-faktura bir marta sinaldi: bitta javob, «Noaniq», so‘ng butun ish chegaraga yetgani uchun to‘xtatilayotganda u ham uzib qo‘yildi.</li>`,
          )}
        </ul>
      </div>
      <dl class="facts outcome-facts">
        <div><dt>${t('The whole run', 'Butun ish')}</dt><dd>${minutes(comparison.seconds)}</dd></div>
        <div><dt>${t('Questions put to the model', 'Modelga berilgan savollar')}</dt><dd>${comparison.attempts}</dd></div>
        <div><dt>${t('Answers that came back', 'Qaytgan javoblar')}</dt><dd>${comparison.answers}</dd></div>
        <div><dt>${t('Correct verdicts', 'To‘g‘ri xulosalar')}</dt><dd>${correct}</dd></div>
        <div><dt>${t('Profile', 'Profil')}</dt><dd>${comparison.profile}</dd></div>
        <div><dt>${t('App code executed', 'Ilova kodi ishga tushirilganmi')}</dt><dd>${t('no', 'yo‘q')}</dd></div>
      </dl>
    </div>
  </div>
</section>`;

  const bring = band({
    id: 'import',
    heading: t('Or bring records you already have.', 'Yoki o‘zingizda bor yozuvlarni bering.'),
    intro: html`<div class="stack-gap">
      ${standing('half', t('Built. Tested on made-up records only', 'Qurilgan. Faqat soxta yozuvlarda sinalgan'))}
      <p>${t(
        'For apps Plumb should not contact itself, or may not contact yet: it works from what you saved.',
        'Plumb o‘zi murojaat qilmasligi kerak yoki hali murojaat qila olmaydigan ilovalar uchun: u siz saqlagan yozuvlar bilan ishlaydi.',
      )}</p>
    </div>`,
    body: html`<div class="stack-gap">
      <ul class="limits">
        ${t(
          html`<li><strong>What you can bring.</strong> Requests and replies saved from your browser’s developer tools, plain records, your own notes, and screenshots.</li>
        <li><strong>Imports stay inert.</strong> Plumb never opens a link it finds inside a record, and it shows saved pages as text.</li>
        <li><strong>Secrets are removed first.</strong> Passwords, cookies and tokens are taken out before anything is saved. If a record carries personal data nobody expected, the assessment stops and offers a private note about what happened.</li>
        <li><strong>You still review it.</strong> Pattern matching cannot recognise every private value, so read what you import.</li>
        <li><strong>What you get.</strong> A map of the addresses that were really seen, a checklist of what to compare by hand, and the same three-judgment analysis as above.</li>`,
          html`<li><strong>Nimalarni berish mumkin.</strong> Brauzeringizning dasturchi vositalaridan saqlab olingan so‘rov va javoblar, oddiy yozuvlar, o‘z qaydlaringiz va skrinshotlar.</li>
        <li><strong>Import qilingan narsa harakatsiz qoladi.</strong> Plumb yozuv ichida uchragan havolani hech qachon ochmaydi, saqlangan sahifalarni esa matn sifatida ko‘rsatadi.</li>
        <li><strong>Maxfiy ma’lumotlar avval olib tashlanadi.</strong> Parollar, cookie va tokenlar biror narsa saqlanishidan oldin chiqarib tashlanadi. Yozuvda hech kim kutmagan shaxsiy ma’lumot uchrasa, tekshiruv to‘xtaydi va nima bo‘lgani haqida shaxsiy qayd tuzishni taklif qiladi.</li>
        <li><strong>Baribir o‘zingiz ko‘rib chiqasiz.</strong> Andozalar har qanday maxfiy qiymatni taniy olmaydi, shuning uchun import qilayotgan narsangizni o‘qib chiqing.</li>
        <li><strong>Natijada nima olasiz.</strong> Haqiqatan ko‘rilgan manzillar xaritasi, qo‘lda solishtirish kerak bo‘lgan narsalar ro‘yxati va yuqoridagidek uch bahoga asoslangan tahlil.</li>`,
        )}
      </ul>
      <figure class="report-figure is-inline">
        ${workbenchShot('assess', t('The web assessment screen of Plumb’s workbench: the approved address, who authorised it, and the limits on requests and time', 'Plumb interfeysidagi veb-tekshiruv ekrani: tasdiqlangan manzil, kim ruxsat bergani hamda so‘rovlar va vaqt chegaralari'), [1056, 1300])}
        <figcaption class="small">${t(
          html`The same steps in the workbench, in a browser. A capture of the real screen with example values filled in for the picture: no collection was approved from it. ${fact(views.captures)} pictures of the new screens were checked for overflow and page errors.`,
          html`Xuddi shu qadamlar brauzerdagi interfeysda. Bu haqiqiy ekranning tasviri, maydonlar rasm uchun namunaviy qiymatlar bilan to‘ldirilgan: undan hech qanday so‘rov yuborishga ruxsat berilmagan. Yangi ekranlarning ${fact(views.captures)} ta tasviri sahifadan chiqib ketish va xatolar bo‘yicha tekshirilgan.`,
        )}</figcaption>
      </figure>
    </div>`,
  });

  const PARTS = {
    description: t('what was seen', 'nima kuzatilgani'),
    endpoints: t('the addresses involved', 'tegishli manzillar'),
    safe_steps: t('safe steps to see it again', 'buni qayta ko‘rish uchun xavfsiz qadamlar'),
    impact: t('what it could mean', 'bu nimaga olib kelishi mumkinligi'),
    mitigation: t('how to fix it', 'qanday tuzatish kerakligi'),
    tools: t('the tools and AI model used', 'ishlatilgan vositalar va SI modeli'),
    limitations: t('what the draft does not show', 'qoralama nimani ko‘rsatmasligi'),
  };

  const report = band({
    id: 'report',
    heading: t('The report stays with you.', 'Hisobot o‘zingizda qoladi.'),
    body: html`<ol class="plumbline">
      <li>
        <h3>${t('Plumb drafts it.', 'Plumb qoralama tuzadi.')}</h3>
        <p>${t(
          html`A private draft, saved outside the project: ${drafts.parts.map((/** @type {keyof typeof PARTS} */ part, /** @type {number} */ index) => html`${index ? ', ' : ''}${PARTS[part]}`)}.`,
          html`Loyihadan tashqarida saqlanadigan shaxsiy qoralama: ${drafts.parts.map((/** @type {keyof typeof PARTS} */ part, /** @type {number} */ index) => html`${index ? ', ' : ''}${PARTS[part]}`)}.`,
        )}</p>
      </li>
      <li>
        <h3>${t('You preview it.', 'Siz uni ko‘rib chiqasiz.')}</h3>
        <p>${t(
          'The preview carries a fingerprint. If the evidence changes afterwards, that preview no longer counts and a new one is needed.',
          'Ko‘rib chiqish nusxasining o‘z barmoq izi bo‘ladi. Keyin dalillar o‘zgarsa, bu nusxa o‘z kuchini yo‘qotadi va yangisi kerak bo‘ladi.',
        )}</p>
      </li>
      <li>
        <h3>${t('A person signs it off.', 'Uni odam tasdiqlaydi.')}</h3>
        <p>${t(
          'Saving the report needs that exact fingerprint and a named reviewer.',
          'Hisobotni saqlash uchun aynan o‘sha barmoq izi va ko‘rib chiqqan odamning ismi kerak.',
        )}</p>
      </li>
      <li class="bob-end">
        ${bobEnd}
        <h3>${t('Nothing is sent anywhere.', 'Hech narsa hech qayerga yuborilmaydi.')}</h3>
        <p>${t(
          html`Plumb never submits, uploads or publishes a report. On record: ${fact(drafts.count)} drafts written from the made-up cases of the comparison above. None was exported.`,
          html`Plumb hisobotni hech qachon o‘zi topshirmaydi, yuklamaydi va e’lon qilmaydi. Yozuvlarda: yuqoridagi taqqoslashning soxta holatlari asosida yozilgan ${fact(drafts.count)} ta qoralama. Birortasi eksport qilinmagan.`,
        )}</p>
      </li>
    </ol>`,
  });

  const CARD = {
    'GUIDE-object-authorization': t(
      'One item, two accounts: may the second account read what belongs to the first?',
      'Bitta narsa, ikkita hisob: ikkinchi hisob birinchisiga tegishli narsani o‘qiy oladimi?',
    ),
    'GUIDE-function-authorization': t(
      'One restricted action, several roles: seeing a button does not mean being allowed to use it.',
      'Bitta cheklangan amal, bir nechta rol: tugmani ko‘rish undan foydalanishga ruxsat bor degani emas.',
    ),
    'GUIDE-session-continuity': t(
      'Who a session belongs to, and whether signing out really ends it.',
      'Seans kimga tegishli va hisobdan chiqish uni haqiqatan tugatadimi.',
    ),
  };
  holds(cards.cards.every((/** @type {any} */ card) => card.id in CARD), 'each card has its one-line description');

  const cardBand = band({
    id: 'cards',
    heading: t('Three method cards.', 'Uchta uslubiy karta.'),
    intro: html`<div class="stack-gap">
      ${standing('half', t('Included. No benefit measured', 'Qo‘shilgan. Foydasi o‘lchanmagan'))}
      <p>${t(
        'Short notes on how to test one kind of problem, which Plumb can hand to the AI model with the evidence. They were written for Plumb from two public OWASP documents and carry their own licence.',
        'Bitta turdagi muammoni qanday sinash haqidagi qisqa qaydlar. Plumb ularni dalillar bilan birga SI modeliga bera oladi. Ular Plumb uchun OWASP’ning ikki ochiq hujjati asosida yozilgan va alohida litsenziyaga ega.',
      )}</p>
    </div>`,
    body: html`<div class="stack-gap">
      <ul class="cards">
        ${cards.cards.map(
          (/** @type {any} */ card) => html`<li class="sheet card">
          <h3 lang="en">${card.title}</h3>
          <p>${CARD[/** @type {keyof typeof CARD} */ (card.id)]}</p>
          <p class="card-src" lang="en">${card.sources.map((/** @type {any} */ source, /** @type {number} */ index) => html`${index ? html`<br>` : ''}<span class="fact">${source.id}</span>`)}</p>
        </li>`,
        )}
      </ul>
      <ul class="limits">
        ${t(
          html`<li><strong>A card is advice on method.</strong> It is never evidence about your app, and it can never approve a request or state your rule for you.</li>
        <li><strong>It is off unless you ask for it.</strong> In the comparison above, the run with a card ran out of time before its third answer, so nothing is known about whether a card helps.</li>
        <li><strong>Found by plain word search.</strong> The cards are looked up on your computer. No online service is involved.</li>
        <li><strong>Three cards are not coverage.</strong> They touch access to items, access to actions, and sessions. Version ${fact(cards.version)}, licence ${fact(cards.license)}.</li>`,
          html`<li><strong>Karta — uslub bo‘yicha maslahat.</strong> U hech qachon ilovangiz haqidagi dalil bo‘lmaydi, so‘rovni tasdiqlay olmaydi va qoidangizni siz uchun aytib bera olmaydi.</li>
        <li><strong>O‘zingiz so‘ramaguningizcha ishlatilmaydi.</strong> Yuqoridagi taqqoslashda karta qo‘shilgan urinish uchinchi javobdan oldin vaqti tugab qolgan, shuning uchun karta yordam berishi haqida hech narsa ma’lum emas.</li>
        <li><strong>Oddiy so‘z qidiruvi bilan topiladi.</strong> Kartalar kompyuteringizning o‘zida qidiriladi. Hech qanday onlayn xizmat ishlatilmaydi.</li>
        <li><strong>Uchta karta to‘liq qamrov degani emas.</strong> Ular narsalarga kirish, amallarga kirish va seanslarga tegishli. Versiya ${fact(cards.version)}, litsenziya ${fact(cards.license)}.</li>`,
        )}
      </ul>
    </div>`,
  });

  const notThis = band({
    id: 'not',
    heading: t('What this is not.', 'Bu nima emas.'),
    body: html`<ul class="limits">
      ${t(
        html`<li><strong>Not a way to test a website you may not test.</strong> The collection on this page contacts only Plumb’s own practice app, on this computer; that is built in, not a setting. <a href="/what-it-does#can-web">A website test</a> is a separate path, with its own approved scope and plan.</li>
        <li><strong>Not a scanner.</strong> It does not crawl an app or try lists of attacks. It sends a short plan you have read and approved.</li>
        <li><strong>Not a proof.</strong> An observation shows what the app answered once. A source finding shows what the code allows. A runtime check shows a flaw working under a fixed script. Plumb reports each under its own name and never turns one into another.</li>
        <li><strong>Not a browser.</strong> The collection sends plain web requests, so pages that only work with scripts are out of its reach. A website test uses a browser of its own, and only for the steps in its approved plan.</li>
        <li><strong>Not something that leaves your computer.</strong> Records, drafts and the AI model stay in Plumb’s data folder.</li>`,
        html`<li><strong>Sinashga ruxsatingiz yo‘q saytni sinash vositasi emas.</strong> Bu sahifadagi yig‘ish faqat Plumbning o‘z sinov ilovasiga, shu kompyuterning o‘zida murojaat qiladi. Bu sozlama emas, dasturning tuzilishi shunday. <a href="/what-it-does#can-web">Sayt sinovi</a> esa alohida yo‘l, uning o‘z tasdiqlangan qamrovi va rejasi bor.</li>
        <li><strong>Skaner emas.</strong> U ilovani boshdan-oyoq aylanib chiqmaydi va hujumlar ro‘yxatini sinab ko‘rmaydi. Siz o‘qib, tasdiqlagan qisqa rejanigina yuboradi.</li>
        <li><strong>Isbot emas.</strong> Kuzatuv ilova bir safar nima deb javob berganini ko‘rsatadi. Koddan chiqarilgan xulosa kod nimaga yo‘l qo‘yishini ko‘rsatadi. Jonli sinov esa xato qat’iy belgilangan skript ostida amalda ishlashini ko‘rsatadi. Plumb har birini o‘z nomi bilan beradi va hech qachon birini boshqasiga aylantirmaydi.</li>
        <li><strong>Brauzer emas.</strong> Yig‘ish oddiy veb-so‘rovlar yuboradi, shuning uchun faqat skriptlar bilan ishlaydigan sahifalar uning qamrovidan tashqarida. Sayt sinovi esa o‘z brauzeridan foydalanadi, faqat tasdiqlangan rejadagi qadamlar uchun.</li>
        <li><strong>Kompyuteringizdan tashqariga chiqadigan narsa emas.</strong> Yozuvlar, qoralamalar va SI modeli Plumbning ma’lumotlar papkasida qoladi.</li>`,
      )}
    </ul>`,
  });

  const commands = band({
    id: 'commands',
    heading: t('The commands.', 'Buyruqlar.'),
    intro: html`<p>${t(
      html`From a source install, one action per command. The workbench (${factWhole('plumb web')}) offers the same steps as forms.`,
      html`Manba kodidan o‘rnatilgan Plumb uchun, har bir buyruq bitta amal bajaradi. Brauzerdagi interfeys (${factWhole('plumb web')}) xuddi shu qadamlarni shakllar ko‘rinishida taklif qiladi.`,
    )}</p>`,
    body: html`<div class="stack-gap">
      ${command(
        [
          'uv run plumb assess --create <scope.json>',
          'uv run plumb assess <assessment-id> --lab-preview pair',
          'uv run plumb assess <assessment-id> --lab-run <approved-actions.json>',
          'uv run plumb assess <assessment-id> --import-collection <reviewed-collection.json>',
          'uv run plumb assess <assessment-id> --analyze <comparison-id>',
          'uv run plumb assess <assessment-id> --report',
        ].join('\n'),
      )}
      <p class="small">${t(
        'In order: save the scope, see the plan, run the approved plan, import the replies you have reviewed, have the AI model judge one comparison, and preview the private report.',
        'Tartib bilan: qamrovni saqlash, rejani ko‘rish, tasdiqlangan rejani bajarish, ko‘rib chiqilgan javoblarni import qilish, bitta taqqoslashni SI modeliga baholatish va shaxsiy hisobotni oldindan ko‘rish.',
      )}</p>
      ${command(
        [
          'uv run plumb assess <assessment-id> --import-records <records.json> --review <review.json>',
          'uv run plumb assess <assessment-id> --map',
          'uv run plumb assess <assessment-id> --checklist',
          'uv run plumb chat <assessment-id> "What evidence is missing?" --kind assessment',
        ].join('\n'),
      )}
      <p class="small">${t(
        'With your own records: import them with your review, see the map and the checklist, and ask a question about what was imported.',
        'O‘z yozuvlaringiz bilan: ularni ko‘rib chiqqaningizni tasdiqlab import qilish, xarita va tekshirish ro‘yxatini ko‘rish hamda import qilingan narsa haqida savol berish.',
      )}</p>
      <p class="more"><a href="/install">${t('Install Plumb first', 'Avval Plumbni o‘rnating')}</a></p>
    </div>`,
  });

  return page({
    path,
    title: t('Web assessment: checking an app by its answers', 'Veb-tekshiruv: ilovani javoblariga qarab tekshirish'),
    description: t(
      'How Plumb works without source code: a scope you declare, a plan you approve, the nine recorded requests to its practice app, what the replies showed, and why the AI model’s verdict on them is still Inconclusive.',
      'Plumb manba kodisiz qanday ishlaydi: siz belgilaydigan qamrov, siz tasdiqlaydigan reja, sinov ilovasiga yuborilgan to‘qqizta yozib olingan so‘rov, javoblar nimani ko‘rsatgani va nega SI modelining ular bo‘yicha xulosasi hali «Noaniq».',
    ),
    body: html`${head}${scope}${trace}${compare}${judged}${bring}${report}${cardBand}${notThis}${commands}`,
    context,
  });
}
