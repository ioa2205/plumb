// @ts-check
import { glyph } from '../components/glyphs.mjs';
import { band, page } from '../components/layout.mjs';
import { fact, factWhole } from '../components/parts.mjs';
import { day, int, mb, shortHash } from '../lib/format.mjs';
import { holds } from '../lib/holds.mjs';
import { html } from '../lib/html.mjs';
import { lang, t } from '../lib/lang.mjs';

export const path = '/evidence';

/** In Uzbek the recorded English word is shown beside its translation, so reports can be matched. */
const recorded = (/** @type {string} */ word) => (lang() === 'uz' ? html` <span class="fact">${word}</span>` : '');

/** @param {import('../components/layout.mjs').PageContext} context */
export function render(context) {
  const { record } = context;
  const { run, runtime, software, development, package: pack, cpu_profile: cpu } = record;
  const [receipt, invoice] = run.findings;
  const { baseline, family_run: familyRun } = development;
  const { python } = software;
  const conclusions = (/** @type {any[]} */ cases) => Object.fromEntries(cases.map((entry) => [entry.id, entry.conclusion]));
  const actionPhone = conclusions(development.action_phone);
  const phonePair = conclusions(development.phone_pair);

  holds(python.failed_first_run === 1 && python.passed_on_isolated_retry === 1, 'one test failed and passed when rerun alone');
  holds(python.skipped === 3, 'three tests were skipped');
  holds(actionPhone.D2 === 'Inconclusive' && phonePair.D2 === 'Inconclusive', 'the phone number case was Inconclusive in two runs');
  holds(actionPhone.D1 === 'Supported' && actionPhone['D1-L'] === 'Rejected' && phonePair['D2-L'] === 'Rejected', 'the action pair and the protected phone case were correct');
  const focused = Object.fromEntries(development.focused.map((/** @type {any} */ entry) => [entry.id, entry]));
  holds(
    !focused.B1.protected && focused.B1.original === 'Inconclusive' && focused.B1.focused === 'Inconclusive',
    'the unsafe query stayed Inconclusive',
  );
  holds(
    focused['B2-L'].protected && focused['B2-L'].original === 'Inconclusive' && focused['B2-L'].focused === 'Inconclusive',
    'the safe command case was not cleared in two runs',
  );
  holds(familyRun.inconclusive === 11 && familyRun.expected_rejections === 1, 'eleven Inconclusive and one expected rejection');
  holds(run.proposal.status === 'refused', 'the fix proposal was refused');
  holds(run.initial_refusal.model_loaded === false, 'refused once before the recorded run');
  holds(pack.clean_user_profile === false && run.browser_rendering_claimed === false, 'clean account and browser rendering are untested');
  holds(runtime.receipt.outcome === 'reproduced' && runtime.invoice.outcome === 'not_reproduced' && runtime.replay.after.outcome === 'fixed', 'runtime outcomes');
  const check = cpu.first_use_check;
  const [cpuReceipt, cpuInvoice] = cpu.review.findings;
  holds(record.download.has_cpu_profile === false, 'the second profile is in the source code, not in the download');
  holds(cpu.same_computer_as_recorded_run, 'the second profile ran on the same laptop as everything else');
  holds(check.outcome === 'passed' && check.answers_matching_expected_kind === 0, 'the first-use check passed although no answer named the expected kind of check');
  holds(cpu.review.lifecycle === 'completed' && cpu.review.exit === 0 && cpu.review.memory_abort === null, 'the processor-only review ended normally');
  holds(
    cpuReceipt.route === receipt.route && cpuInvoice.route === invoice.route && cpuReceipt.conclusion === receipt.conclusion && cpuInvoice.conclusion === invoice.conclusion,
    'the same two routes got the same conclusions',
  );

  const head = html`<header class="page-head">
  <div class="wrap">
    <h1>${t('Strengths, limits and what comes next', 'Imkoniyatlar, cheklovlar va keyingi rejalar')}</h1>
    <p class="lede">${t(
      'What has been built, what has been checked, what went wrong, and what nobody has tested yet. Each figure is read from a saved record when this site is built.',
      'Nima qurilgan, nima tekshirilgan, nima ishlamagan va nimani hali hech kim sinab ko‘rmagan. Har bir raqam sayt yig‘ilayotganda saqlangan yozuvlardan olinadi.',
    )}</p>
  </div>
</header>`;

  const shown = t('Shown working', 'Ishlashi ko‘rsatilgan');
  const partly = t('Partly checked', 'Qisman tekshirilgan');
  const absent = t('Not available', 'Mavjud emas');
  const built = band({
    id: 'built',
    heading: t('What is built, and how far each part has been checked.', 'Nima qurilgan va har bir qism qanchalik tekshirilgan.'),
    intro: html`<ul class="legend">
      <li>${glyph('dot')} ${t('Shown working, with a saved record', 'Ishlashi ko‘rsatilgan, saqlangan yozuvi bor')}</li>
      <li>${glyph('half')} ${t('Built; partly checked, or with misses on record', 'Qurilgan, lekin qisman tekshirilgan yoki aniqlanmay qolgan xatolari bor')}</li>
      <li>${glyph('ring')} ${t('Not available', 'Mavjud emas')}</li>
    </ul>`,
    body: html`<dl class="ledger">
      <div>${glyph('dot', shown)}<dt>${t('Missing ownership checks in FastAPI routes', 'FastAPI manzillarida tushib qolgan egalik tekshiruvlari')}</dt>
        <dd>${t(
          'Found the receipt flaw and cleared the protected invoice route in the recorded run. That is two cases on a practice app, not a measure of reliability.',
          'Yozib olingan sinovda chek manzilidagi xatoni topdi va himoyalangan hisob-faktura manzilini oqladi. Bu sinov ilovasidagi ikki holat, ishonchlilik o‘lchovi emas.',
        )}</dd></div>
      <div>${glyph('dot', shown)}<dt>${t('Reports you can keep', 'Saqlab qo‘yiladigan hisobotlar')}</dt>
        <dd>${t(
          html`HTML, Markdown, JSON and SARIF, with the same finding numbers in each. The four files from the recorded run are <a href="/recorded-run#saved">published as saved</a>.`,
          html`HTML, Markdown, JSON va SARIF; to‘rttasida ham topilma raqamlari bir xil. Yozib olingan sinovning to‘rtta fayli <a href="/recorded-run#saved">o‘zgarishsiz e’lon qilingan</a>.`,
        )}</dd></div>
      <div>${glyph('dot', shown)}<dt>${t('Running locally, within memory', 'Lokal ishlash va xotira nazorati')}</dt>
        <dd>${t(
          'Model, code and results stay on the machine. Plumb refuses to start a review when free memory is below the measured requirement, and did so once before the recorded run.',
          'Model, kod va natijalar kompyuterning o‘zida qoladi. Bo‘sh xotira o‘lchangan talabdan kam bo‘lsa, Plumb tekshiruvni boshlamaydi. Yozib olingan sinovdan oldin bir marta aynan shunday bo‘lgan.',
        )}</dd></div>
      <div>${glyph('half', partly)}<dt>${t('Reviews on other computers', 'Boshqa kompyuterlarda tekshiruv')}</dt>
        <dd>${t(
          html`A second profile, ${factWhole(cpu.id)}, runs the same AI model on the processor alone, so a 64-bit Windows computer other than the measured laptop model can start a review. It is in the source code, not in the download. It has completed <a href="#passed">one real run</a>, on the laptop Plumb is developed on, and has not been tried on a second computer.`,
          html`Ikkinchi profil, ${factWhole(cpu.id)}, o‘sha SI modelini faqat protsessorda ishlatadi, shu tufayli o‘lchangan noutbuk modelidan boshqa 64 bitli Windows kompyuter ham tekshiruvni boshlay oladi. U manba kodida bor, tayyor to‘plamda yo‘q. Plumb ishlab chiqilayotgan noutbukda <a href="#passed">bir marta haqiqiy sinovdan</a> o‘tgan, ikkinchi kompyuterda esa sinab ko‘rilmagan.`,
        )}</dd></div>
      <div>${glyph('half', partly)}<dt>${t('Other kinds of flaw', 'Boshqa turdagi xatolar')}</dt>
        <dd>${t(
          'Unsafe database queries, file paths that escape their folder and data leaking to the browser each have a working path. Misses are on record: an unsafe query and an exposed phone number both ended as Inconclusive.',
          'Ma’lumotlar bazasiga xavfli so‘rovlar, o‘z papkasidan tashqariga chiqib ketadigan fayl yo‘llari va brauzerga sizib chiqadigan ma’lumotlar uchun ham tekshirish yo‘li bor. Lekin aniqlanmay qolgan holatlar qayd etilgan: xavfli so‘rov ham, oshkor bo‘lgan telefon raqami ham «Noaniq» bilan tugagan.',
        )}</dd></div>
      <div>${glyph('half', partly)}<dt>Next.js ${t('and', 'va')} TypeScript</dt>
        <dd>${t(
          'Parsed and mapped. In one development run an unguarded server action was reported and its protected twin cleared. Reliability across the framework is unmeasured.',
          'Kod tahlil qilinadi va xaritaga tushiriladi. Ishlab chiqish jarayonidagi bitta sinovda himoyasiz server amali (server action) topilgan, uning himoyalangan egizagi esa oqlangan. Butun freymvork bo‘yicha ishonchlilik o‘lchanmagan.',
        )}</dd></div>
      <div>${glyph('half', partly)}<dt>${t('Suggested fixes', 'Tuzatish takliflari')}</dt>
        <dd>${t(
          'Plumb asks the model for a fix and validates it. In the recorded run the proposal had a syntax error and was refused, so no fix was offered.',
          'Plumb modeldan tuzatish so‘raydi va uni tekshiradi. Yozib olingan sinovda taklifda sintaksis xatosi bor edi, u rad etildi va hech qanday tuzatish taklif qilinmadi.',
        )}</dd></div>
      <div>${glyph('half', partly)}<dt>${t('Browser view, pause and resume', 'Brauzerdagi interfeys, to‘xtatish va davom ettirish')}</dt>
        <dd>${t(
          'A local web interface over the same saved results, and reviews that continue from a checkpoint. Both pass their software tests. How the browser view looks and behaves has not been formally checked.',
          'Xuddi shu saqlangan natijalar ustida ishlaydigan lokal veb-interfeys va nazorat nuqtasidan davom etadigan tekshiruvlar. Ikkalasi ham dasturiy testlardan o‘tadi. Interfeysning brauzerdagi ko‘rinishi va ishlashi hali rasman tekshirilmagan.',
        )}</dd></div>
      <div>${glyph('ring', absent)}<dt>${t('Proving a flaw by running the app', 'Ilovani ishga tushirib xatoni isbotlash')}</dt>
        <dd>${t(
          'Plumb does not run the code it reviews, so it cannot confirm that a flaw works in practice. The one exception is the bundled practice app, tested by a fixed script.',
          'Plumb tekshirayotgan kodini ishga tushirmaydi, shuning uchun xato amalda ishlashini tasdiqlay olmaydi. Yagona istisno — Plumb bilan birga keladigan sinov ilovasi: u qat’iy belgilangan skript bilan sinaladi.',
        )}</dd></div>
    </dl>`,
  });

  const kinds = band({
    id: 'kinds',
    heading: t('Two kinds of evidence, kept apart.', 'Ikki xil dalil, ular aralashtirilmaydi.'),
    intro: html`<p>${t(
      html`A <strong>source finding</strong> is a conclusion from reading code. A <strong>runtime check</strong> is what happened when a request was really sent. Plumb never upgrades one into the other.`,
      html`<strong>Koddan chiqarilgan xulosa</strong> kodni o‘qish natijasi. <strong>Jonli sinov</strong> esa haqiqiy so‘rov yuborilganda nima bo‘lganini ko‘rsatadi. Plumb hech qachon birini ikkinchisi o‘rniga qo‘ymaydi.`,
    )}</p>`,
    body: html`<div class="stack-gap">
      <div class="sheet">
        <h4>${t('From reading the code', 'Kodni o‘qishdan')}</h4>
        <dl class="terms terms-words">
          <div><dt>${glyph('dot')} ${t('Supported', 'Tasdiqlandi')}${recorded('supported')}</dt><dd>${t(
            'The investigation supports this specific claim, and the source evidence passed validation.',
            'Tekshiruv aynan shu da’voni tasdiqlaydi va koddagi dalillar tekshiruvdan o‘tgan.',
          )}</dd></div>
          <div><dt>${glyph('slash')} ${t('Rejected', 'Rad etildi')}${recorded('rejected')}</dt><dd>${t(
            'A confirmed, cited protection clears this specific lead.',
            'Tasdiqlangan va aniq ko‘rsatilgan himoya bu shubhani yo‘qqa chiqaradi.',
          )}</dd></div>
          <div><dt>${glyph('half')} ${t('Inconclusive', 'Noaniq')}${recorded('inconclusive')}</dt><dd>${t(
            'The evidence or the three judgments do not settle it. Plumb neither reports a flaw nor clears the code.',
            'Dalillar yoki uchta baho masalani hal qilmaydi. Plumb xato bor ham demaydi, kodni oqlamaydi ham.',
          )}</dd></div>
        </dl>
        <h4>${t('From sending real requests', 'Haqiqiy so‘rov yuborishdan')}</h4>
        <dl class="terms terms-words">
          <div><dt>${t('Reproduced', 'Xato takrorlandi')}${recorded('reproduced')}</dt><dd>${t(
            'A recorded request that should have been refused succeeded, and the legitimate request also succeeded.',
            'Rad etilishi kerak bo‘lgan so‘rov o‘tib ketgan, qonuniy so‘rov ham o‘tgan.',
          )}</dd></div>
          <div><dt>${t('Not reproduced', 'Xato takrorlanmadi')}${recorded('not_reproduced')}</dt><dd>${t(
            'The recorded request did not reproduce the claim. This does not prove the code is safe in general.',
            'Yuborilgan so‘rov da’voni tasdiqlamadi. Bu kod umuman xavfsiz degani emas.',
          )}</dd></div>
          <div><dt class="unproven">${t('Not attempted', 'O‘tkazilmagan')}${recorded('not_attempted')}</dt><dd>${t(
            'Nothing was sent. Both findings of the recorded run carry this label.',
            'Hech narsa yuborilmagan. Yozib olingan sinovning ikkala topilmasida ham shu belgi turibdi.',
          )}</dd></div>
        </dl>
        <h4>${t('About scope', 'Qamrov haqida')}</h4>
        <dl class="terms terms-words">
          <div><dt>${t('Pending, excluded, unsupported', 'Kutilmoqda, qamrovdan tashqari, qo‘llab-quvvatlanmaydi')}</dt><dd>${t(
            'Work that was not finished, was outside the chosen scope, or needs something Plumb cannot do. These stay in the totals, so a report never looks more complete than it is.',
            'Tugallanmagan, tanlangan qamrovdan tashqarida qolgan yoki Plumb bajara olmaydigan ishlar. Ular umumiy hisobdan chiqarib tashlanmaydi, shuning uchun hisobot hech qachon aslidagidan to‘liqroq ko‘rinmaydi.',
          )}</dd></div>
        </dl>
      </div>
    </div>`,
  });

  const result = t('Result', 'Natija');
  const reach = t('How far it reaches', 'Qamrovi');
  const passed = band({
    id: 'passed',
    heading: t('What has passed.', 'Nima sinovdan o‘tgan.'),
    intro: html`<p>${t('Each line says what was checked and how far the result reaches.', 'Har bir qatorda nima tekshirilgani va natija nimani qamrashi aytilgan.')}</p>`,
    body: html`<table class="plain stack passed">
      <caption class="sr-only">${t('Checks that passed, with their result and reach', 'O‘tgan tekshiruvlar, natijasi va qamrovi bilan')}</caption>
      <thead><tr><th scope="col">${t('Check', 'Tekshiruv')}</th><th scope="col">${result}</th><th scope="col">${reach}</th></tr></thead>
      <tbody>
        <tr>
          <th scope="row">${t('The recorded run', 'Yozib olingan sinov')}<br><span class="small">${day(run.started_at)}</span></th>
          <td data-label="${result}">${t(
            html`Receipt route ${fact(receipt.conclusion)}, invoice route ${fact(invoice.conclusion)}. ${fact(receipt.judgments.length + invoice.judgments.length)} judgments, ${fact(run.requests.answered)} requests, normal exit. <a href="/recorded-run">Walkthrough</a>`,
            html`Chek manzili: ${fact(receipt.conclusion)}, hisob-faktura manzili: ${fact(invoice.conclusion)}. ${fact(receipt.judgments.length + invoice.judgments.length)} ta baho, ${fact(run.requests.answered)} ta so‘rov, ish odatdagidek tugagan. <a href="/recorded-run">Batafsil</a>`,
          )}</td>
          <td data-label="${reach}">${t(
            html`Two chosen routes of one practice app, read from source. ${fact(run.coverage.completed)} of ${fact(run.coverage.total)} access checks.`,
            html`Bitta sinov ilovasining oldindan tanlangan ikki manzili, faqat kodni o‘qish orqali. ${fact(run.coverage.total)} ta joydan ${fact(run.coverage.completed)} tasi.`,
          )}</td>
        </tr>
        <tr>
          <th scope="row">${t('A review on the processor alone', 'Faqat protsessorda o‘tkazilgan tekshiruv')}<br><span class="small">${day(cpu.recorded_on)}</span></th>
          <td data-label="${result}">${t(
            html`With the second profile, ${factWhole(cpu.id)}. First its check of the program that runs the model passed: ${fact(check.answers_valid)} of ${fact(check.answers)} test answers came back in the required form with valid citations, and in ${fact(check.leak_pairs_clean)} of ${fact(check.leak_pairs)} pairs of requests nothing from the first request showed up in the second. Then the review: receipt route ${fact(cpuReceipt.conclusion)}, invoice route ${fact(cpuInvoice.conclusion)}, ${fact(cpu.review.model_requests)} requests, normal exit.`,
            html`Ikkinchi profil, ${factWhole(cpu.id)} bilan. Avval modelni ishga tushiradigan dasturning sinovi o‘tdi: ${fact(check.answers)} ta sinov javobidan ${fact(check.answers_valid)} tasi talab qilingan shaklda va to‘g‘ri havolalar bilan keldi, ${fact(check.leak_pairs)} juft so‘rovdan ${fact(check.leak_pairs_clean)} tasida birinchi so‘rovdagi ma’lumot ikkinchisida ko‘rinmadi. So‘ng tekshiruv: chek manzili ${fact(cpuReceipt.conclusion)}, hisob-faktura manzili ${fact(cpuInvoice.conclusion)}, ${fact(cpu.review.model_requests)} ta so‘rov, ish odatdagidek tugagan.`,
          )}</td>
          <td data-label="${reach}">${t(
            html`One run, on the laptop Plumb is developed on, of the same two routes as the recorded run. It has not been tried on any other computer, and its speed there is unknown. The check looks at the form of an answer, not at whether it is right: on all ${fact(check.answers)} test snippets the model named a different kind of check than the expected one, and the check passed all the same.`,
            html`Plumb ishlab chiqilayotgan noutbukdagi bitta sinov, yozib olingan sinovdagi ikki manzilning o‘zida. Boshqa hech bir kompyuterda sinab ko‘rilmagan, u yerdagi tezligi ham noma’lum. Sinov javobning shakliga qaraydi, to‘g‘riligiga emas: sinov uchun berilgan ${fact(check.answers)} ta kod parchasining hammasida model kutilganidan boshqa turdagi tekshiruvni ko‘rsatdi, sinov esa baribir o‘tdi.`,
          )}</td>
        </tr>
        <tr>
          <th scope="row">${t('Software tests', 'Dasturiy testlar')}</th>
          <td data-label="${result}">${t(
            html`${fact(int(python.collected))} Python tests collected. ${fact(int(python.passed_first_run))} passed. ${fact(python.failed_first_run)} failed on a Windows temporary-file permission error and passed when rerun alone. ${fact(python.skipped)} were skipped because Windows did not let the tests create symbolic links. ${fact(software.frontend_tests)} browser-view tests pass.`,
            html`${fact(int(python.collected))} ta Python testi yig‘ilgan. ${fact(int(python.passed_first_run))} tasi o‘tgan. ${fact(python.failed_first_run)} tasi Windows’dagi vaqtinchalik faylga ruxsat xatosi tufayli o‘tmagan, alohida qayta ishga tushirilganda esa o‘tgan. ${fact(python.skipped)} tasi o‘tkazib yuborilgan, chunki Windows testlarga ramziy havola (symlink) yaratishga ruxsat bermagan. Brauzerdagi interfeysning ${fact(software.frontend_tests)} ta testi o‘tadi.`,
          )}</td>
          <td data-label="${reach}">${t(
            'That the program does what its tests expect. Says nothing about how often the model judges correctly.',
            'Dastur testlarda kutilgan ishni bajarishini ko‘rsatadi. Model qanchalik tez-tez to‘g‘ri baho berishi haqida hech narsa demaydi.',
          )}</td>
        </tr>
        <tr>
          <th scope="row">${t('The Windows package', 'Windows to‘plami')}</th>
          <td data-label="${result}">${t(
            html`One ZIP, ${fact(mb(pack.archive_bytes))}, ${fact(int(pack.inventoried_files))} files, fingerprint ${fact(`${shortHash(pack.archive_sha256)}…`)}. Extracted into a folder with spaces and run through its public commands with no developer tools available. Private files confirmed absent.`,
            html`Bitta ZIP fayl: ${fact(mb(pack.archive_bytes))}, ${fact(int(pack.inventoried_files))} ta fayl, barmoq izi ${fact(`${shortHash(pack.archive_sha256)}…`)}. Nomida bo‘sh joy bor papkaga chiqarilgan va dasturchi vositalari bo‘lmagan holda, ochiq buyruqlari orqali ishga tushirilgan. Ichida shaxsiy fayllar yo‘qligi tasdiqlangan.`,
          )}</td>
          <td data-label="${reach}">${t(
            'The same laptop and Windows account it was built on. A clean account is untested.',
            'U yig‘ilgan noutbuk va Windows hisobining o‘zi. Yangi hisobda sinab ko‘rilmagan.',
          )}</td>
        </tr>
        <tr>
          <th scope="row">${t('Runtime checks on the practice app', 'Sinov ilovasidagi jonli sinovlar')}<br><span class="small">${day(runtime.receipt.at)} ${t('and', 'va')} ${day(runtime.replay.at)}</span></th>
          <td data-label="${result}">${t(
            html`Receipt flaw reproduced with real requests. Invoice route refused the same request. After one reviewed fix, the receipt request was refused and the owner still succeeded. <a href="/recorded-run#runtime">Details</a>`,
            html`Chek manzilidagi xato haqiqiy so‘rovlar bilan takrorlangan. Hisob-faktura manzili xuddi shunday so‘rovni rad etgan. Ko‘rib chiqilgan bitta tuzatishdan keyin chek so‘rovi rad etilgan, buyurtma egasi esa avvalgidek javob olgan. <a href="/recorded-run#runtime">Batafsil</a>`,
          )}</td>
          <td data-label="${reach}">${t(
            'One bundled app and a fixed script. Plumb cannot run other projects.',
            'Plumb bilan birga keladigan bitta ilova va qat’iy belgilangan skript. Plumb boshqa loyihalarni ishga tushira olmaydi.',
          )}</td>
        </tr>
      </tbody>
    </table>`,
  });

  const misses = band({
    id: 'misses',
    heading: t('What did not work.', 'Nima ishlamadi.'),
    intro: html`<p>${t(
      'These are development results on the practice app. Where a flaw was really there, Inconclusive is a miss: Plumb did not report it.',
      'Bular sinov ilovasidagi ishlab chiqish natijalari. Xato haqiqatan bor joyda «Noaniq» natija aniqlanmay qolgan xato hisoblanadi: Plumb uni ko‘rsatmagan.',
    )}</p>`,
    body: html`<ul class="limits">
      ${t(
        html`<li><strong>An unsafe database query was not caught.</strong> A query built from text the caller controls ended as Inconclusive, and stayed Inconclusive after a change aimed at exactly that case.</li>
      <li><strong>An exposed phone number was not caught.</strong> In two separate runs the case ended as ${fact(phonePair.D2)}, with all three model answers empty. A gap in the code handed to the model was found and repaired afterwards. The case has not been run again since.</li>
      <li><strong>A broad run mostly abstained.</strong> An earlier version was pointed at ${fact(familyRun.cases)} cases across the other kinds of flaw. It made ${fact(familyRun.requests)} requests and returned ${fact(familyRun.inconclusive)} Inconclusive results and ${fact(familyRun.expected_rejections)} correct rejection.</li>
      <li><strong>Suggested fixes are unreliable.</strong> In the recorded run the model’s fix had a syntax error and was ${fact(run.proposal.status)}. In another run the proposed change only removed indentation and added no protection. A rule was added afterwards to refuse changes that alter nothing.</li>
      <li><strong>A safe case was not cleared.</strong> A command built the safe way drew inconsistent judgments in two runs and ended Inconclusive both times.</li>`,
        html`<li><strong>Ma’lumotlar bazasiga xavfli so‘rov aniqlanmadi.</strong> So‘rovchi o‘zi kiritadigan matndan tuzilgan so‘rov «Noaniq» bilan tugadi va aynan shu holatga qaratilgan o‘zgarishdan keyin ham «Noaniq»ligicha qoldi.</li>
      <li><strong>Oshkor bo‘lgan telefon raqami aniqlanmadi.</strong> Ikkita alohida sinovda bu holat ${fact(phonePair.D2)} bilan tugadi, modelning uchala javobi ham bo‘sh edi. Keyinroq modelga beriladigan kod qismida kamchilik topilib, tuzatildi. Shundan beri bu holat qayta sinalmagan.</li>
      <li><strong>Keng sinovda u asosan javob bermadi.</strong> Avvalgi versiya boshqa turdagi xatolarga oid ${fact(familyRun.cases)} ta holatda sinab ko‘rilgan. U ${fact(familyRun.requests)} ta so‘rov yuborib, ${fact(familyRun.inconclusive)} ta «Noaniq» natija va ${fact(familyRun.expected_rejections)} ta to‘g‘ri rad javobini qaytargan.</li>
      <li><strong>Tuzatish takliflari ishonchsiz.</strong> Yozib olingan sinovda model taklif qilgan tuzatishda sintaksis xatosi bor edi va u rad etildi (${fact(run.proposal.status)}). Boshqa sinovda taklif qilingan o‘zgarish faqat satr boshidagi bo‘shliqlarni olib tashlagan, hech qanday himoya qo‘shmagan. Shundan keyin hech narsani o‘zgartirmaydigan tuzatishlarni rad etadigan qoida qo‘shildi.</li>
      <li><strong>Xavfsiz holat oqlanmadi.</strong> Xavfsiz usulda tuzilgan buyruq ikki sinovda bir-biriga zid baholar oldi va ikkala safar ham «Noaniq» bilan tugadi.</li>`,
      )}
    </ul>`,
  });

  const why = band({
    id: 'why',
    heading: t('Why the model is not simply asked.', 'Nega modeldan shunchaki so‘ralmaydi.'),
    body: html`<div class="stack-gap prose">
      ${t(
        html`<p>Early in the project the same model was asked directly, once per case, about ${fact(baseline.cases)} practice cases: ${fact(baseline.vulnerable)} with a planted flaw and ${fact(baseline.controls)} written to be safe.</p>
      <p>It reported a flaw in ${fact(baseline.one_shot.controls_flagged)} of the ${fact(baseline.controls)} safe cases. It did find ${fact(baseline.one_shot.authorization_found)} of ${fact(baseline.one_shot.authorization_of)} permission flaws. A pattern scanner without any model flagged ${fact(baseline.scanner.controls_flagged)} of the safe cases and found ${fact(baseline.scanner.authorization_found)} of ${fact(baseline.scanner.authorization_of)}.</p>
      <p>That result is why Plumb compares routes, searches for a reason to clear a suspect, and asks three times. It is not evidence that Plumb does better. Plumb has not been scored on those same ${fact(baseline.cases)} cases.</p>`,
        html`<p>Loyiha boshida xuddi shu modeldan ${fact(baseline.cases)} ta sinov holati haqida to‘g‘ridan-to‘g‘ri, har biri uchun bir martadan so‘ralgan. Ularning ${fact(baseline.vulnerable)} tasiga ataylab xato qoldirilgan, ${fact(baseline.controls)} tasi esa xavfsiz qilib yozilgan.</p>
      <p>Model ${fact(baseline.controls)} ta xavfsiz holatning ${fact(baseline.one_shot.controls_flagged)} tasida xato bor deb javob bergan. Ruxsatga oid ${fact(baseline.one_shot.authorization_of)} ta xatoning ${fact(baseline.one_shot.authorization_found)} tasini topgan. Modelsiz ishlaydigan andoza skaneri esa xavfsiz holatlarning ${fact(baseline.scanner.controls_flagged)} tasini belgilagan va ${fact(baseline.scanner.authorization_of)} ta xatodan ${fact(baseline.scanner.authorization_found)} tasini topgan.</p>
      <p>Aynan shu natija tufayli Plumb manzillarni solishtiradi, shubhani yo‘qqa chiqaradigan sabab qidiradi va uch marta so‘raydi. Bu Plumb yaxshiroq ishlashining isboti emas: Plumb o‘sha ${fact(baseline.cases)} ta holatda baholanmagan.</p>`,
      )}
    </div>`,
  });

  const untested = band({
    id: 'untested',
    heading: t('Not tested, and not claimed.', 'Sinalmagan va da’vo qilinmaydi.'),
    body: html`<ul class="limits">
      ${t(
        html`<li><strong>Any accuracy figure.</strong> No precision, recall or false-alarm rate exists for Plumb. A sealed test set was prepared and has not been opened.</li>
      <li><strong>Comparison with other tools or models.</strong> None has been run on equal terms. That includes the larger models Plumb can install from its list: none has been downloaded or run here, so nothing is known about how they compare.</li>
      <li><strong>A second computer.</strong> Everything here was recorded on one laptop, under one Windows account. That includes the one run of the second profile, which was added so that other computers can start a review.</li>
      <li><strong>macOS and Linux.</strong> Plumb runs on 64-bit Windows 10 or 11 only for now.</li>
      <li><strong>Running reviewed code safely.</strong> No isolated environment was available on this laptop, so none has passed its checks and Plumb does not run the projects it reviews.</li>
      <li><strong>How the browser view and the report look.</strong> They pass their software checks. Their appearance on desktop and phone, and their accessibility, have not been formally checked.</li>
      <li><strong>Other languages and frameworks.</strong> Only Python with FastAPI and TypeScript with Next.js are mapped.</li>
      <li><strong>A video.</strong> No screen recording exists. The saved report files are the record.</li>`,
        html`<li><strong>Har qanday aniqlik ko‘rsatkichi.</strong> Plumb uchun aniqlik, to‘liqlik yoki yolg‘on signallar ulushi hisoblanmagan. Yopiq test to‘plami tayyorlangan, lekin hali ochilmagan.</li>
      <li><strong>Boshqa vositalar yoki modellar bilan taqqoslash.</strong> Teng sharoitda birorta ham taqqoslash o‘tkazilmagan. Plumb o‘z ro‘yxatidan o‘rnata oladigan kattaroq modellar ham shunga kiradi: ularning birortasi bu yerda yuklab olinmagan va ishga tushirilmagan, shuning uchun ular bir-biridan qanday farq qilishi haqida hech narsa ma’lum emas.</li>
      <li><strong>Ikkinchi kompyuter.</strong> Bu yerdagi hamma narsa bitta noutbukda, bitta Windows hisobida yozib olingan. Boshqa kompyuterlar ham tekshiruvni boshlay olishi uchun qo‘shilgan ikkinchi profilning yagona sinovi ham shu noutbukda o‘tgan.</li>
      <li><strong>macOS va Linux.</strong> Plumb hozircha faqat 64 bitli Windows 10 yoki 11 da ishlaydi.</li>
      <li><strong>Tekshirilayotgan kodni xavfsiz ishga tushirish.</strong> Bu noutbukda ajratilgan muhit yo‘q edi, shuning uchun bunday muhit sinovdan o‘tmagan va Plumb tekshirayotgan loyihalarni ishga tushirmaydi.</li>
      <li><strong>Interfeys va hisobotning brauzerdagi ko‘rinishi.</strong> Ular dasturiy tekshiruvlardan o‘tadi. Kompyuter va telefondagi ko‘rinishi hamda imkoniyati cheklangan foydalanuvchilar uchun qulayligi rasman tekshirilmagan.</li>
      <li><strong>Boshqa dasturlash tillari va freymvorklar.</strong> Faqat Python (FastAPI) va TypeScript (Next.js) xaritaga tushiriladi.</li>
      <li><strong>Video.</strong> Ekran yozuvi yo‘q. Saqlangan hisobot fayllari yozuv vazifasini bajaradi.</li>`,
      )}
    </ul>`,
  });

  const next = band({
    id: 'next',
    heading: t('What comes next.', 'Keyingi rejalar.'),
    intro: html`<p>${t(
      'From the project plan. These are intentions, not promises, and none of them is done.',
      'Loyiha rejasidan olingan. Bular va’da emas, niyat, va hozircha birortasi ham bajarilmagan.',
    )}</p>`,
    body: html`<ul class="limits">
      ${t(
        html`<li><strong>Measure how often it is right.</strong> Open the sealed test set once, score Plumb on it, and compare it with a pattern scanner and with the model asked directly.</li>
      <li><strong>Repair the recorded misses.</strong> Unsafe database queries, data leaking from Next.js pages, and suggested fixes that are not valid code.</li>
      <li><strong>A safe place to run reviewed code.</strong> With an isolated runner such as Windows Sandbox or Docker, a finding could be tested with real requests on projects other than the practice app.</li>
      <li><strong>More computers.</strong> Run the second profile on a computer other than this laptop, test the installation under a clean Windows account, and measure hardware beyond this one laptop, including larger models on stronger machines.</li>
      <li><strong>More frameworks.</strong> Django, Flask, Express and Hono, each with its own test cases.</li>
      <li><strong>A review on every change.</strong> A command that looks only at what a change touched, so Plumb can run when code is sent for review.</li>
      <li><strong>Finish checking the browser view.</strong> Confirm how it and the HTML report look and behave on desktop and phone.</li>`,
        html`<li><strong>Qanchalik tez-tez to‘g‘ri topishini o‘lchash.</strong> Yopiq test to‘plamini bir marta ochib, Plumbni unda baholash va natijani andoza skaneri hamda to‘g‘ridan-to‘g‘ri so‘ralgan model bilan solishtirish.</li>
      <li><strong>Aniqlanmay qolgan xatolarni tuzatish.</strong> Ma’lumotlar bazasiga xavfli so‘rovlar, Next.js sahifalaridan sizib chiqadigan ma’lumotlar va yaroqsiz kod bo‘lib chiqadigan tuzatish takliflari.</li>
      <li><strong>Tekshirilayotgan kodni ishga tushirish uchun xavfsiz joy.</strong> Windows Sandbox yoki Docker kabi ajratilgan muhit bo‘lsa, topilmalarni sinov ilovasidan tashqari loyihalarda ham haqiqiy so‘rovlar bilan tekshirish mumkin bo‘ladi.</li>
      <li><strong>Ko‘proq kompyuterlar.</strong> Ikkinchi profilni shu noutbukdan boshqa kompyuterda ishga tushirib ko‘rish, o‘rnatishni yangi Windows hisobida sinash va boshqa qurilmalarni ham o‘lchash, jumladan kuchliroq kompyuterlarda kattaroq modellarni.</li>
      <li><strong>Ko‘proq freymvorklar.</strong> Django, Flask, Express va Hono, har biri o‘z sinov holatlari bilan.</li>
      <li><strong>Har bir o‘zgarishda tekshiruv.</strong> Faqat o‘zgarish tekkan joylarni ko‘radigan buyruq. Shunda kod ko‘rib chiqishga yuborilganda Plumb avtomatik ishlay oladi.</li>
      <li><strong>Interfeysni tekshirib tugatish.</strong> Brauzerdagi interfeys va HTML hisobot kompyuter hamda telefonda qanday ko‘rinishi va ishlashini tasdiqlash.</li>`,
      )}
    </ul>`,
  });

  const care = band({
    id: 'care',
    heading: t('How Plumb treats the machine it runs on.', 'Plumb o‘zi ishlayotgan kompyuterga qanday munosabatda bo‘ladi.'),
    body: html`<ul class="limits">
      ${t(
        html`<li><strong>Reviewed code is read as text.</strong> It is never imported, installed or executed.</li>
      <li><strong>Programs in the reviewed folder are not started.</strong> Windows looks in the current folder first when a program is started by name, so a file hidden in a project under the name of a Windows tool could have been started. Installed from source, Plumb now leaves the current folder out of that search. The download was built before this fix.</li>
      <li><strong>No cloud model.</strong> There are no API keys and no remote model calls. The model runs on the same computer.</li>
      <li><strong>Memory is checked before every launch.</strong> A watcher stops Plumb’s own model if free memory falls too low. It never closes other programs.</li>
      <li><strong>Comments and names are not evidence.</strong> A comment saying the code is safe does not count. Only executable code can clear a suspect.</li>
      <li><strong>Secrets are masked.</strong> Text with the known shapes of passwords and keys is replaced in reports, and the reports leave out source text.</li>`,
        html`<li><strong>Tekshirilayotgan kod matn sifatida o‘qiladi.</strong> U hech qachon import qilinmaydi, o‘rnatilmaydi va ishga tushirilmaydi.</li>
      <li><strong>Tekshirilayotgan papkadagi dasturlar ishga tushirilmaydi.</strong> Windows dasturni nomi bo‘yicha ishga tushirayotganda avval joriy papkaga qaraydi, shuning uchun loyihaga Windows vositasi nomi bilan yashirib qo‘yilgan fayl ishga tushib ketishi mumkin edi. Manba kodidan o‘rnatilgan Plumb endi joriy papkani bu qidiruvdan chiqarib tashlaydi. Tayyor to‘plam bu tuzatishdan oldin yig‘ilgan.</li>
      <li><strong>Bulutdagi model yo‘q.</strong> API kalitlari ham, masofaviy modelga murojaat ham yo‘q. Model shu kompyuterning o‘zida ishlaydi.</li>
      <li><strong>Har safar ishga tushishdan oldin xotira tekshiriladi.</strong> Bo‘sh xotira haddan tashqari kamayib ketsa, nazoratchi Plumbning o‘z modelini to‘xtatadi. Boshqa dasturlarni u hech qachon yopmaydi.</li>
      <li><strong>Izohlar va nomlar dalil hisoblanmaydi.</strong> «Bu kod xavfsiz» degan izoh inobatga olinmaydi. Shubhani faqat ishlaydigan kod yo‘qqa chiqara oladi.</li>
      <li><strong>Maxfiy ma’lumotlar yashiriladi.</strong> Parol va kalitlarga o‘xshash matn hisobotlarda almashtiriladi, manba matni esa hisobotlarga kiritilmaydi.</li>`,
      )}
    </ul>`,
  });

  const records = band({
    id: 'records',
    heading: t('The records behind this site.', 'Sayt tayangan yozuvlar.'),
    intro: html`<p>${t(
      'A script reads these files and fills in the figures. If a file changes, the fingerprint here changes with it.',
      'Skript shu fayllarni o‘qib, raqamlarni o‘z joyiga qo‘yadi. Fayl o‘zgarsa, bu yerdagi barmoq izi ham o‘zgaradi.',
    )}</p>`,
    body: html`<details class="more-detail">
      <summary>${t(`${Object.keys(record.sources).length} files`, `${Object.keys(record.sources).length} ta fayl`)}</summary>
      <ul class="record-list">
        ${Object.entries(record.sources).map(
          ([file, hash]) => html`<li><span class="fact">${file}</span> <span class="hash">${shortHash(/** @type {string} */ (hash))}…</span></li>`,
        )}
      </ul>
    </details>
    <p class="small">${t(
      html`The four report files of the recorded run are <a href="/recorded-run#saved">published in full</a>. The other records are kept with the project.`,
      html`Yozib olingan sinovning to‘rtta hisobot fayli <a href="/recorded-run#saved">to‘liq e’lon qilingan</a>. Qolgan yozuvlar loyiha bilan birga saqlanadi.`,
    )}</p>`,
  });

  return page({
    path,
    title: t('Strengths, limits and what comes next', 'Imkoniyatlar, cheklovlar va keyingi rejalar'),
    description: t(
      'What Plumb does well, the misses on record, the difference between source findings and runtime checks, everything that has not been tested, and what is planned next.',
      'Plumb nimani yaxshi bajaradi, qaysi xatolarni aniqlay olmagan, koddan chiqarilgan xulosa jonli sinovdan qanday farq qiladi, nima hali sinalmagan va keyin nima rejalashtirilgan.',
    ),
    body: html`${head}${built}${passed}${misses}${untested}${next}${kinds}${why}${care}${records}`,
    context,
  });
}
