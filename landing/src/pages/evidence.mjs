// @ts-check
import { glyph } from '../components/glyphs.mjs';
import { band, page } from '../components/layout.mjs';
import { fact, factWhole, inShort } from '../components/parts.mjs';
import { day, int, mb, minutes, seconds, shortHash } from '../lib/format.mjs';
import { holds } from '../lib/holds.mjs';
import { html } from '../lib/html.mjs';
import { lang, t } from '../lib/lang.mjs';
import { externalLimits, websiteLimits } from '../lib/website-limits.mjs';

export const path = '/evidence';

/** In Uzbek the recorded English word is shown beside its translation, so reports can be matched. */
const recorded = (/** @type {string} */ word) => (lang() === 'uz' ? html` <span class="fact">${word}</span>` : '');

/** @param {import('../components/layout.mjs').PageContext} context */
export function render(context) {
  const { record } = context;
  const { run, runtime, software, development, download, cpu_profile: cpu } = record;
  const { collection, observation_comparison: comparison, console_records: consoles, cards, workbench_views: views, report_drafts: drafts, journey, chat } = record;
  const { latest } = software;
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
  holds(download.clean_user_profile === false && run.browser_rendering_claimed === false, 'clean account and browser rendering are untested');
  holds(runtime.receipt.outcome === 'reproduced' && runtime.invoice.outcome === 'not_reproduced' && runtime.replay.after.outcome === 'fixed', 'runtime outcomes');
  const check = cpu.first_use_check;
  const [cpuReceipt, cpuInvoice] = cpu.review.findings;
  holds(download.has_cpu_profile && download.investigator_same_as_source && download.source_files_checked > 0, 'the download holds the same code as the source, second profile and working-folder fix included');
  holds(download.model_loaded === false && download.developer_tools_on_path === false && download.folder_name_had_spaces, 'the download was checked without a model, with no developer tools, from a folder with spaces in its name');
  holds(download.downloaded_or_installed === false && download.model_already_installed, 'the checks of the download fetched nothing: the model was already on the laptop');
  holds(download.same_investigator_as_cpu_profile_run === false && cpu.from_source, 'the download’s investigator has changed since the processor-only review, which was run from source');
  holds(typeof download.older_report_refused === 'boolean' && typeof download.recorded_report_opened === 'boolean', 'report outcomes come from the current package checks');
  holds(download.launch_rechecks_memory, 'memory admission is checked again before every model launch');
  holds(cpu.same_computer_as_recorded_run, 'the second profile ran on the same laptop as everything else');
  holds(check.outcome === 'passed' && check.answers_matching_expected_kind === 0, 'the first-use check passed although no answer named the expected kind of check');
  holds(cpu.review.lifecycle === 'completed' && cpu.review.exit === 0 && cpu.review.memory_abort === null, 'the processor-only review ended normally');
  holds(
    cpuReceipt.route === receipt.route && cpuInvoice.route === invoice.route && cpuReceipt.conclusion === receipt.conclusion && cpuInvoice.conclusion === invoice.conclusion,
    'the same two routes got the same conclusions',
  );

  // The newer parts: collecting and judging replies, questions, model choices, cards.
  holds(collection.requests === 9 && collection.external_access === false && collection.loopback_only, 'nine requests went to the practice app and nowhere else');
  holds(collection.human_review === 'pending' && collection.imported === false && collection.model_loaded === false, 'the collected replies were not reviewed into evidence and no model was loaded');
  holds(comparison.acceptance_met === false && comparison.conditions.every((/** @type {any} */ entry) => entry.conclusion === 'inconclusive' && entry.correct === false), 'every judgment of the replies ended Inconclusive');
  holds(comparison.unrun === 7 && comparison.planned === 12 && comparison.attempts === 12 && comparison.answers === 10, 'twelve questions, ten answers, seven of twelve planned cases never ran');
  holds(comparison.conditions.some((/** @type {any} */ entry) => entry.approach === 'facts_guidance' && entry.stop_reason === 'BudgetStop'), 'the run with a card ran out of time');
  holds(consoles.ask.generated_by === 'saved_evidence' && consoles.models.list.length === 5, 'the saved-finding question used no model, and five models are listed');
  holds(consoles.models.list.slice(1).every((/** @type {any} */ entry) => entry.quality === 'untested' && !entry.installed), 'no other model has been downloaded or tried');
  holds(views.captures === 24 && views.signed_in_acceptance === false && views.fresh_model_acceptance === false, 'the workbench pictures used stand-in content and no signed-in walk-through');
  holds(drafts.count === 12 && drafts.published === false, 'twelve report drafts, none exported');
  holds(latest.failed === 1 && latest.skipped === 3 && latest.collected === latest.passed + latest.failed + latest.skipped, 'the latest whole run of the tests had one failure and three skips');
  holds(journey.mode === 'owned_fixture' && journey.supported === 0 && journey.findings > 0, 'the one website test ran on the practice website and left only leads');
  holds(download.model_planning_qualified === false, 'the AI model is not yet trusted to plan website steps');
  holds(chat.turns > 1 && chat.mixed_general_declined === true && /not a finding/.test(chat.basis), 'one recorded chat session; its general answer is labelled, and one general part declined');

  const head = html`<header class="page-head">
  <div class="wrap">
    <h1>${t('Strengths, limits and what comes next', 'Imkoniyatlar, cheklovlar va keyingi rejalar')}</h1>
    <p class="lede">${t(
      'What has been built, what has been checked, what went wrong, and what nobody has tested yet. Each figure is read from a saved record when this site is built.',
      'Nima qurilgan, nima tekshirilgan, nima ishlamagan va nimani hali hech kim sinab ko‘rmagan. Har bir raqam sayt yig‘ilayotganda saqlangan yozuvlardan olinadi.',
    )}</p>
    ${inShort([
      t('Shown working: reading an app’s code, on one practice app and one laptop.', 'Ishlashi ko‘rsatilgan: ilova kodini o‘qib tekshirish, bitta sinov ilovasida va bitta noutbukda.'),
      t('Not working yet: the AI model reaches no verdict from an app’s answers, and in tests it missed other kinds of flaw.', 'Hali ishlamaydi: SI modeli ilova javoblari bo‘yicha aniq xulosaga kelmaydi, sinovlarda esa boshqa turdagi xatolarni aniqlay olmagan.'),
      t('Not tested: real projects, a website other than its own, a second computer, how good the AI model’s answers are.', 'Sinalmagan: haqiqiy loyihalar, o‘zinikidan boshqa sayt, ikkinchi kompyuter, SI modeli javoblarining sifati.'),
    ])}
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
      <div>${glyph('dot', shown)}<dt>${t('Collecting replies from the practice app', 'Sinov ilovasidan javob yig‘ish')}</dt>
        <dd>${t(
          html`With a plan that was shown and approved first, Plumb sent ${fact(collection.requests)} requests to its own practice app and saved what came back. <a href="/web-assessment#trace">Each request and reply</a>. ${websiteLimits(download)}`,
          html`Avval ko‘rsatilib, tasdiqlangan reja bo‘yicha Plumb o‘zining sinov ilovasiga ${fact(collection.requests)} ta so‘rov yuborib, kelgan javoblarni saqladi. <a href="/web-assessment#trace">Har bir so‘rov va javob</a>. ${websiteLimits(download)}`,
        )}</dd></div>
      <div>${glyph('half', partly)}<dt>${t('Testing a website you may test', 'Sinashga ruxsatingiz bor saytni sinash')}</dt>
        <dd>${t(
          html`Built: scope, plan, your approval, sign-in as each test account, comparisons and a private report. Run once on Plumb’s own practice website on ${day(journey.recorded_at)}: ${fact(journey.requests)} of ${fact(journey.max_requests)} allowed requests, ${fact(journey.findings)} leads and no confirmed finding. The AI model is not yet trusted to plan the steps, so plain code and the reviewer choose them. ${externalLimits(download)}`,
          html`Qurilgan: qamrov, reja, sizning tasdig‘ingiz, har bir test hisobi bilan kirish, solishtirish va shaxsiy hisobot. ${day(journey.recorded_at)} kuni Plumbning o‘z sinov saytida bir marta ishga tushirilgan: ruxsat etilgan ${fact(journey.max_requests)} ta so‘rovdan ${fact(journey.requests)} tasi, ${fact(journey.findings)} ta iz, tasdiqlangan topilma yo‘q. SI modeliga qadamlarni rejalashtirish hali ishonib topshirilmagan, ularni oddiy kod va tekshiruvchi tanlaydi. ${externalLimits(download)}`,
        )}</dd></div>
      <div>${glyph('half', partly)}<dt>${t('Judging an app from its replies', 'Ilovani javoblariga qarab baholash')}</dt>
        <dd>${t(
          html`The whole path is built: a scope you declare, saved requests and replies, a comparison of two accounts, three judgments by the AI model and a private report draft. In the one comparison on record the model’s answer was Inconclusive every time. <a href="/web-assessment#judged">What happened</a>.`,
          html`Butun yo‘l qurilgan: siz belgilaydigan qamrov, saqlangan so‘rov va javoblar, ikki hisobni solishtirish, SI modelining uchta bahosi va shaxsiy hisobot qoralamasi. Qayd etilgan yagona taqqoslashda modelning javobi har safar «Noaniq» bo‘lgan. <a href="/web-assessment#judged">Nima bo‘lgani</a>.`,
        )}</dd></div>
      <div>${glyph('half', partly)}<dt>${t('Questions in plain words', 'Oddiy so‘zlar bilan savollar')}</dt>
        <dd>${t(
          html`A question about a saved finding is answered from the saved evidence, without the AI model; that was run for this site on ${day(consoles.recorded_at)}. General questions in plain words were recorded once, on ${day(chat.recorded_at)}: the model answered and labelled its answer as general knowledge, and in a mixed question its general part declined to answer. Open questions to the AI model about a project, a review or an assessment are built and pass their software tests; none has been recorded, so nothing is known about how good those answers are.`,
          html`Saqlangan topilma haqidagi savolga SI modelisiz, saqlangan dalillar asosida javob beriladi; bu shu sayt uchun ${day(consoles.recorded_at)} kuni ishga tushirib ko‘rilgan. Oddiy so‘zlar bilan berilgan umumiy savollar ${day(chat.recorded_at)} kuni bir marta yozib olingan: model javob berib, uni umumiy bilim deb belgiladi, aralash savolda esa umumiy qism javob berishdan bosh tortdi. Loyiha, tekshiruv yoki veb-tekshiruv haqida SI modeliga erkin savol berish imkoniyati qurilgan va dasturiy testlardan o‘tadi; bunday suhbat hali qayd etilmagan, shuning uchun bu javoblar qanchalik yaxshi ekani haqida hech narsa ma’lum emas.`,
        )}</dd></div>
      <div>${glyph('half', partly)}<dt>${t('Choosing the AI model', 'SI modelini tanlash')}</dt>
        <dd>${t(
          html`Plumb lists ${fact(consoles.models.list.length)} pinned models and says which fit in free memory. Only the default has a recorded result. The other ${fact(consoles.models.list.length - 1)} have not been downloaded or run. <a href="/install#models">The list it printed</a>.`,
          html`Plumb oldindan belgilangan ${fact(consoles.models.list.length)} ta modelni sanab, qaysilari bo‘sh xotiraga sig‘ishini aytadi. Faqat asosiy modelning qayd etilgan natijasi bor. Qolgan ${fact(consoles.models.list.length - 1)} tasi yuklab olinmagan va ishga tushirilmagan. <a href="/install#models">U chiqargan ro‘yxat</a>.`,
        )}</dd></div>
      <div>${glyph('half', partly)}<dt>${t('Method cards', 'Uslubiy kartalar')}</dt>
        <dd>${t(
          html`${fact(cards.cards.length)} short notes on testing method, written from OWASP documents, that Plumb can hand to the AI model. The one run that used a card ran out of time, so no benefit has been measured. They are off unless asked for.`,
          html`Sinash uslubi haqidagi ${fact(cards.cards.length)} ta qisqa qayd. Ular OWASP hujjatlari asosida yozilgan, Plumb ularni SI modeliga bera oladi. Karta ishlatilgan yagona urinishda vaqt tugab qolgan, shuning uchun foydasi o‘lchanmagan. So‘ralmaguncha ishlatilmaydi.`,
        )}</dd></div>
      <div>${glyph('half', partly)}<dt>${t('Reviews on other computers', 'Boshqa kompyuterlarda tekshiruv')}</dt>
        <dd>${t(
          html`A second profile, ${factWhole(cpu.id)}, runs the same AI model on the processor alone, so a 64-bit Windows computer other than the measured laptop model can start a review. It is in the download and in the source code alike. It has completed <a href="#passed">one real run</a>, from source, on the laptop Plumb is developed on, and has not been tried on a second computer.`,
          html`Ikkinchi profil, ${factWhole(cpu.id)}, o‘sha SI modelini faqat protsessorda ishlatadi, shu tufayli o‘lchangan noutbuk modelidan boshqa 64 bitli Windows kompyuter ham tekshiruvni boshlay oladi. U tayyor to‘plamda ham, manba kodida ham bor. Plumb ishlab chiqilayotgan noutbukda, manba kodidan ishga tushirilgan holda, <a href="#passed">bir marta haqiqiy sinovdan</a> o‘tgan, ikkinchi kompyuterda esa sinab ko‘rilmagan.`,
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
          html`A local web interface over the same saved results, and reviews that continue from a checkpoint. Both pass their software tests. ${fact(views.captures)} pictures of its newer screens were checked for overflow and page errors, with stand-in content. A full walk-through in a signed-in browser has not been completed.`,
          html`Xuddi shu saqlangan natijalar ustida ishlaydigan lokal veb-interfeys va nazorat nuqtasidan davom etadigan tekshiruvlar. Ikkalasi ham dasturiy testlardan o‘tadi. Yangi ekranlarining ${fact(views.captures)} ta tasviri namunaviy ma’lumot bilan, sahifadan chiqib ketish va xatolar bo‘yicha tekshirilgan. Hisobga kirilgan brauzerda boshidan oxirigacha tekshirib chiqilmagan.`,
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
    heading: t('Three kinds of evidence, kept apart.', 'Uch xil dalil, ular aralashtirilmaydi.'),
    intro: html`<p>${t(
      html`A <strong>source finding</strong> is a conclusion from reading code. A <strong>web observation</strong> is what a running app answered when it was asked. A <strong>runtime check</strong> is a fixed script proving a flaw with real requests. Plumb never upgrades one into another.`,
      html`<strong>Koddan chiqarilgan xulosa</strong> kodni o‘qish natijasi. <strong>Veb-kuzatuv</strong> ishlab turgan ilova so‘rovga nima deb javob berganini ko‘rsatadi. <strong>Jonli sinov</strong> esa xatoni haqiqiy so‘rovlar bilan isbotlaydigan qat’iy belgilangan skript. Plumb hech qachon birini boshqasi o‘rniga qo‘ymaydi.`,
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
        <h4>${t('From what a running app answered', 'Ishlab turgan ilovaning javoblaridan')}</h4>
        <dl class="terms terms-words">
          <div><dt>${t('Observation', 'Kuzatuv')}</dt><dd>${t(
            'A saved request and its reply, with the account it was sent as. It shows what happened once. It is not proof of why, and it is never shown as a source finding or a runtime check.',
            'Saqlangan so‘rov va uning javobi, qaysi hisob nomidan yuborilgani bilan birga. U bir safar nima bo‘lganini ko‘rsatadi. Sababini isbotlamaydi va hech qachon koddan chiqarilgan xulosa yoki jonli sinov sifatida ko‘rsatilmaydi.',
          )}</dd></div>
          <div><dt>${t('Its three answers', 'Uning uchta javobi')}</dt><dd>${t(
            html`The same words, Supported, Rejected and Inconclusive, here about replies and not about code. So far every recorded answer of this kind is ${glyph('half')} Inconclusive.`,
            html`So‘zlar o‘sha-o‘sha: Tasdiqlandi, Rad etildi va Noaniq, lekin bu yerda ular kod haqida emas, javoblar haqida. Hozircha bu turdagi barcha qayd etilgan javoblar ${glyph('half')} «Noaniq».`,
          )}</dd></div>
        </dl>
        <h4>${t('From sending real requests under a fixed script', 'Qat’iy belgilangan skript bilan haqiqiy so‘rov yuborishdan')}</h4>
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
          <th scope="row">${t('Requests to the practice app', 'Sinov ilovasiga so‘rovlar')}<br><span class="small">${day(collection.recorded_at)}</span></th>
          <td data-label="${result}">${t(
            html`${fact(collection.requests)} planned requests, all approved, all sent once. ${fact(int(collection.bytes_received))} bytes came back in ${fact(`${seconds(Number(collection.seconds.toFixed(2)))} s`)}, inside every limit that was set. The receipt answered the other customer; the invoice refused him. <a href="/web-assessment#trace">The requests</a>`,
            html`Rejalashtirilgan ${fact(collection.requests)} ta so‘rovning hammasi tasdiqlangan va bir martadan yuborilgan. ${fact(`${seconds(Number(collection.seconds.toFixed(2)))} s`)} ichida ${fact(int(collection.bytes_received))} bayt javob kelgan, belgilangan chegaralarning birortasi buzilmagan. Chek manzili begona mijozga javob bergan, hisob-faktura manzili esa uni rad etgan. <a href="/web-assessment#trace">So‘rovlar</a>`,
          )}</td>
          <td data-label="${reach}">${t(
            'One fixed plan against the bundled practice app, on the same computer, approved by the developer as an exercise. The replies were not reviewed by a person and were not turned into evidence. Plumb cannot contact other apps.',
            'Plumb bilan birga keladigan sinov ilovasiga qarshi, shu kompyuterning o‘zida bajarilgan bitta qat’iy reja. Uni dasturchi mashq sifatida tasdiqlagan. Javoblarni odam ko‘rib chiqmagan va ular dalilga aylantirilmagan. Plumb boshqa ilovalarga murojaat qila olmaydi.',
          )}</td>
        </tr>
        <tr>
          <th scope="row">${t('Software tests', 'Dasturiy testlar')}</th>
          <td data-label="${result}">${t(
            html`${fact(int(python.collected))} Python tests collected. ${fact(int(python.passed_first_run))} passed. ${fact(python.failed_first_run)} failed on a Windows temporary-file permission error and passed when rerun alone. ${fact(python.skipped)} were skipped because Windows did not let the tests create symbolic links. ${fact(software.frontend_tests)} browser-view tests pass. That was the earlier checkpoint. After the newer parts were added, the whole suite ran again on ${day(latest.date)}: ${fact(int(latest.collected))} collected, ${fact(int(latest.passed))} passed, ${fact(latest.failed)} failed and ${fact(latest.skipped)} skipped. The failing area was repaired and then passed its ${fact(latest.repaired_checks)} checks; the whole suite was not run again after that.`,
            html`${fact(int(python.collected))} ta Python testi yig‘ilgan. ${fact(int(python.passed_first_run))} tasi o‘tgan. ${fact(python.failed_first_run)} tasi Windows’dagi vaqtinchalik faylga ruxsat xatosi tufayli o‘tmagan, alohida qayta ishga tushirilganda esa o‘tgan. ${fact(python.skipped)} tasi o‘tkazib yuborilgan, chunki Windows testlarga ramziy havola (symlink) yaratishga ruxsat bermagan. Brauzerdagi interfeysning ${fact(software.frontend_tests)} ta testi o‘tadi. Bu avvalgi nazorat nuqtasi edi. Yangi qismlar qo‘shilgandan keyin butun to‘plam ${day(latest.date)} kuni qayta ishga tushirilgan: ${fact(int(latest.collected))} ta test yig‘ilgan, ${fact(int(latest.passed))} tasi o‘tgan, ${fact(latest.failed)} tasi o‘tmagan, ${fact(latest.skipped)} tasi o‘tkazib yuborilgan. Xato chiqqan qism tuzatilib, o‘zining ${fact(latest.repaired_checks)} ta tekshiruvidan o‘tgan; shundan keyin butun to‘plam qayta ishga tushirilmagan.`,
          )}</td>
          <td data-label="${reach}">${t(
            'That the program does what its tests expect. Says nothing about how often the model judges correctly.',
            'Dastur testlarda kutilgan ishni bajarishini ko‘rsatadi. Model qanchalik tez-tez to‘g‘ri baho berishi haqida hech narsa demaydi.',
          )}</td>
        </tr>
        <tr>
          <th scope="row">${t('The Windows package', 'Windows to‘plami')}<br><span class="small">${day(download.checked_at)}</span></th>
          <td data-label="${result}">${t(
            html`The ZIP offered for download: ${fact(mb(download.archive_bytes))}, ${fact(int(download.inventoried_files))} files, fingerprint ${fact(`${shortHash(download.archive_sha256)}…`)}. Run from a folder with spaces in its name, through its public commands, with no developer tools available: it mapped the practice app and served its browser view.${download.recorded_report_opened ? t(" It also opened the recorded report.", " Yozib olingan hisobotni ham ochdi.") : ""} Every file in the ZIP matched that folder, and private files are confirmed absent. Its ${fact(download.investigator_files)} investigator files match the current source and have changed since the earlier processor-only review. Those earlier answers do not qualify the current investigator. ${download.older_report_refused ? t("The report command refused a historical report.", "report buyrug‘i tarixiy hisobotni rad etdi.") : ""} Memory admission is checked again before every model launch.`,
            html`Yuklab olish uchun taklif qilingan ZIP fayl: ${fact(mb(download.archive_bytes))}, ${fact(int(download.inventoried_files))} ta fayl, barmoq izi ${fact(`${shortHash(download.archive_sha256)}…`)}. Nomida bo‘sh joy bor papkadan, dasturchi vositalari bo‘lmagan holda, ochiq buyruqlari orqali ishga tushirilgan: sinov ilovasining xaritasini tuzdi va brauzerdagi interfeysini ishga tushirdi.${download.recorded_report_opened ? t(" It also opened the recorded report.", " Yozib olingan hisobotni ham ochdi.") : ""} ZIP ichidagi har bir fayl o‘sha papkadagisi bilan mos kelgan, ichida shaxsiy fayllar yo‘qligi tasdiqlangan. Tekshiruvchining ${fact(download.investigator_files)} ta fayli hozirgi manba kodiga mos, avvalgi faqat protsessorda o‘tkazilgan tekshiruvdan keyin esa o‘zgargan. Avvalgi javoblar hozirgi tekshiruvchi sifatini tasdiqlamaydi. ${download.older_report_refused ? t("The report command refused a historical report.", "report buyrug‘i tarixiy hisobotni rad etdi.") : ""} Model har safar ishga tushishidan oldin xotira yetarliligi qayta tekshiriladi.`,
          )}</td>
          <td data-label="${reach}">${t(
            'The laptop and the Windows account it was built on, where the AI model was already installed: nothing was downloaded or installed. A clean account and a second computer are untested. No AI model was loaded, so this package has not run a review.',
            'U yig‘ilgan noutbuk va Windows hisobining o‘zi. SI modeli u yerda oldindan o‘rnatilgan edi, shuning uchun hech narsa yuklab olinmagan va o‘rnatilmagan. Yangi hisobda va ikkinchi kompyuterda sinab ko‘rilmagan. Sinovlarda SI modeli ishga tushirilmagan, demak bu to‘plam hali birorta ham tekshiruv o‘tkazmagan.',
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
        html`<li><strong>From replies alone, the AI model reached no verdict.</strong> The receipt evidence, where the right answer was Supported, was put to the model ${fact(comparison.approaches.length)} different ways on ${day(comparison.recorded_at)}. Every result was Inconclusive. The run took ${fact(minutes(comparison.seconds))}, asked ${fact(comparison.attempts)} questions and got ${fact(comparison.answers)} answers; ${fact(comparison.unrun)} of ${fact(comparison.planned)} planned cases were never reached. <a href="/web-assessment#judged">The four attempts</a>.</li>
      <li><strong>An unsafe database query was not caught.</strong> A query built from text the caller controls ended as Inconclusive, and stayed Inconclusive after a change aimed at exactly that case.</li>
      <li><strong>An exposed phone number was not caught.</strong> In two separate runs the case ended as ${fact(phonePair.D2)}, with all three model answers empty. A gap in the code handed to the model was found and repaired afterwards. The case has not been run again since.</li>
      <li><strong>A broad run mostly abstained.</strong> An earlier version was pointed at ${fact(familyRun.cases)} cases across the other kinds of flaw. It made ${fact(familyRun.requests)} requests and returned ${fact(familyRun.inconclusive)} Inconclusive results and ${fact(familyRun.expected_rejections)} correct rejection.</li>
      <li><strong>Suggested fixes are unreliable.</strong> In the recorded run the model’s fix had a syntax error and was ${fact(run.proposal.status)}. In another run the proposed change only removed indentation and added no protection. A rule was added afterwards to refuse changes that alter nothing.</li>
      <li><strong>A safe case was not cleared.</strong> A command built the safe way drew inconsistent judgments in two runs and ended Inconclusive both times.</li>`,
        html`<li><strong>SI modeli faqat javoblarga qarab aniq xulosaga kela olmadi.</strong> To‘g‘ri javobi «Tasdiqlandi» bo‘lgan chek dalillari ${day(comparison.recorded_at)} kuni modelga ${fact(comparison.approaches.length)} xil usulda berildi. Barcha natijalar «Noaniq» bo‘ldi. Ish ${fact(minutes(comparison.seconds))} davom etdi, modelga ${fact(comparison.attempts)} ta savol berilib, ${fact(comparison.answers)} ta javob olindi; rejalashtirilgan ${fact(comparison.planned)} ta holatdan ${fact(comparison.unrun)} tasiga navbat yetmadi. <a href="/web-assessment#judged">To‘rt urinish</a>.</li>
      <li><strong>Ma’lumotlar bazasiga xavfli so‘rov aniqlanmadi.</strong> So‘rovchi o‘zi kiritadigan matndan tuzilgan so‘rov «Noaniq» bilan tugadi va aynan shu holatga qaratilgan o‘zgarishdan keyin ham «Noaniq»ligicha qoldi.</li>
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
      <li><strong>A web assessment of a real app.</strong> Every request Plumb has sent went to its own practice app or its own practice website, and every imported record so far was made up for testing. Nobody has used it on an app they run.</li>
      <li><strong>How good the AI model’s answers are.</strong> One session of general questions was recorded on ${day(chat.recorded_at)}, and no answer has been graded. Questions about a project, a review or an assessment have not been recorded.</li>
      <li><strong>A second computer.</strong> Everything here was recorded on one laptop, under one Windows account. That includes the one run of the second profile, which was added so that other computers can start a review.</li>
      <li><strong>A review with the downloaded package.</strong> The package offered for download passed its checks without loading the AI model. The recorded test used an earlier package, and the one run of the second profile was done from source.</li>
      <li><strong>macOS and Linux.</strong> Plumb runs on 64-bit Windows 10 or 11 only for now.</li>
      <li><strong>Running reviewed code safely.</strong> No isolated environment was available on this laptop, so none has passed its checks and Plumb does not run the projects it reviews.</li>
      <li><strong>How the browser view and the report look.</strong> They pass their software checks. Their appearance on desktop and phone, and their accessibility, have not been formally checked.</li>
      <li><strong>Other languages and frameworks.</strong> Only Python with FastAPI and TypeScript with Next.js are mapped.</li>
      <li><strong>A video.</strong> No screen recording exists. The saved report files are the record.</li>`,
        html`<li><strong>Har qanday aniqlik ko‘rsatkichi.</strong> Plumb uchun aniqlik, to‘liqlik yoki yolg‘on signallar ulushi hisoblanmagan. Yopiq test to‘plami tayyorlangan, lekin hali ochilmagan.</li>
      <li><strong>Boshqa vositalar yoki modellar bilan taqqoslash.</strong> Teng sharoitda birorta ham taqqoslash o‘tkazilmagan. Plumb o‘z ro‘yxatidan o‘rnata oladigan kattaroq modellar ham shunga kiradi: ularning birortasi bu yerda yuklab olinmagan va ishga tushirilmagan, shuning uchun ular bir-biridan qanday farq qilishi haqida hech narsa ma’lum emas.</li>
      <li><strong>Haqiqiy ilovaning veb-tekshiruvi.</strong> Plumb yuborgan barcha so‘rovlar o‘zining sinov ilovasiga yoki o‘zining sinov saytiga ketgan, hozirgacha import qilingan barcha yozuvlar esa sinov uchun to‘qib chiqarilgan. Uni hali hech kim o‘zi yuritadigan ilovada qo‘llab ko‘rmagan.</li>
      <li><strong>SI modeli javoblarining sifati.</strong> ${day(chat.recorded_at)} kuni umumiy savollar bilan bitta suhbat yozib olingan, lekin birorta javob baholanmagan. Loyiha, tekshiruv yoki veb-tekshiruv haqidagi savollar hali qayd etilmagan.</li>
      <li><strong>Ikkinchi kompyuter.</strong> Bu yerdagi hamma narsa bitta noutbukda, bitta Windows hisobida yozib olingan. Boshqa kompyuterlar ham tekshiruvni boshlay olishi uchun qo‘shilgan ikkinchi profilning yagona sinovi ham shu noutbukda o‘tgan.</li>
      <li><strong>Yuklab olinadigan to‘plam bilan tekshiruv.</strong> Yuklab olish uchun taklif qilingan to‘plam o‘z sinovlaridan SI modeli ishga tushirilmagan holda o‘tgan. Yozib olingan sinov avvalgi to‘plamda o‘tkazilgan, ikkinchi profilning yagona sinovi esa manba kodidan ishga tushirilgan.</li>
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
      <li><strong>Get a verdict from replies.</strong> Find out, from the saved answers, why the model stays undecided on web observations, change one thing, and run the unfinished cases, including the ones with misleading text.</li>
      <li><strong>Repair the recorded misses.</strong> Unsafe database queries, data leaking from Next.js pages, and suggested fixes that are not valid code.</li>
      <li><strong>A safe place to run reviewed code.</strong> With an isolated runner such as Windows Sandbox or Docker, a finding could be tested with real requests on projects other than the practice app.</li>
      <li><strong>More computers.</strong> Run the second profile on a computer other than this laptop, test the installation under a clean Windows account, and measure hardware beyond this one laptop, including larger models on stronger machines.</li>
      <li><strong>More frameworks.</strong> Django, Flask, Express and Hono, each with its own test cases.</li>
      <li><strong>A review on every change.</strong> A command that looks only at what a change touched, so Plumb can run when code is sent for review.</li>
      <li><strong>Finish checking the browser view.</strong> Confirm how it and the HTML report look and behave on desktop and phone.</li>`,
        html`<li><strong>Qanchalik tez-tez to‘g‘ri topishini o‘lchash.</strong> Yopiq test to‘plamini bir marta ochib, Plumbni unda baholash va natijani andoza skaneri hamda to‘g‘ridan-to‘g‘ri so‘ralgan model bilan solishtirish.</li>
      <li><strong>Javoblar bo‘yicha aniq xulosaga erishish.</strong> Saqlangan javoblarga qarab, model nega veb-kuzatuvlarda bir qarorga kela olmayotganini aniqlash, bitta narsani o‘zgartirish va bajarilmay qolgan holatlarni, jumladan chalg‘ituvchi matnli holatlarni ham sinash.</li>
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
      <li><strong>Programs in the reviewed folder are not started.</strong> Windows looks in the current folder first when a program is started by name, so a file hidden in a project under the name of a Windows tool could have been started. Plumb now leaves the current folder out of that search, in the download as well as from source.</li>
      <li><strong>Requests need an approval tied to one plan.</strong> Only explicitly approved origins, paths, accounts and actions may run, within the plan’s limits. External mode also requires the network boundary check on this computer.</li>
      <li><strong>Imported records stay inert.</strong> Plumb never opens a link found inside a saved request or reply. Passwords, cookies and tokens are removed before saving, and unexpected personal data stops the assessment.</li>
      <li><strong>A question cannot act.</strong> Asking the AI model something never starts a review, sends a request, approves a scope or changes a finding. Those have their own controls.</li>
      <li><strong>No cloud model.</strong> There are no API keys and no remote model calls. The model runs on the same computer.</li>
      <li><strong>Memory is checked before every launch.</strong> A watcher stops Plumb’s own model if free memory falls too low. It never closes other programs.</li>
      <li><strong>Comments and names are not evidence.</strong> A comment saying the code is safe does not count. Only executable code can clear a suspect.</li>
      <li><strong>Secrets are masked.</strong> Text with the known shapes of passwords and keys is replaced in reports, and the reports leave out source text.</li>`,
        html`<li><strong>Tekshirilayotgan kod matn sifatida o‘qiladi.</strong> U hech qachon import qilinmaydi, o‘rnatilmaydi va ishga tushirilmaydi.</li>
      <li><strong>Tekshirilayotgan papkadagi dasturlar ishga tushirilmaydi.</strong> Windows dasturni nomi bo‘yicha ishga tushirayotganda avval joriy papkaga qaraydi, shuning uchun loyihaga Windows vositasi nomi bilan yashirib qo‘yilgan fayl ishga tushib ketishi mumkin edi. Plumb endi joriy papkani bu qidiruvdan chiqarib tashlaydi, tayyor to‘plamda ham, manba kodidan o‘rnatilganda ham.</li>
      <li><strong>So‘rov yuborish uchun bitta rejaga bog‘langan ruxsat kerak.</strong> Reja chegaralari ichida faqat aniq tasdiqlangan manzillar, yo‘llar, hisoblar va amallar bajariladi. Tashqi rejim uchun shu kompyuterda tarmoq chegarasi tekshiruvi ham kerak.</li>
      <li><strong>Import qilingan yozuvlar harakatsiz qoladi.</strong> Plumb saqlangan so‘rov yoki javob ichidagi havolani hech qachon ochmaydi. Parollar, cookie va tokenlar saqlashdan oldin olib tashlanadi, kutilmagan shaxsiy ma’lumot uchrasa, tekshiruv to‘xtaydi.</li>
      <li><strong>Savol hech narsani ishga tushira olmaydi.</strong> SI modeliga savol berish tekshiruvni boshlamaydi, so‘rov yubormaydi, qamrovni tasdiqlamaydi va topilmani o‘zgartirmaydi. Bularning har biri uchun alohida boshqaruv bor.</li>
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
