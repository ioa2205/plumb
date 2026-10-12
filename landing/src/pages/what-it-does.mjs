// @ts-check
import { glyph } from '../components/glyphs.mjs';
import { band, page } from '../components/layout.mjs';
import { fact, factWhole, inShort, reportShot, standing, workbenchShot } from '../components/parts.mjs';
import { reviewConsole } from '../components/terminal.mjs';
import { day, gb, int, longDay, mb, minutes, seconds, shortRun } from '../lib/format.mjs';
import { downloadSizes } from '../lib/guide.mjs';
import { holds } from '../lib/holds.mjs';
import { html } from '../lib/html.mjs';
import { t } from '../lib/lang.mjs';
import { externalLimits, websiteLimits } from '../lib/website-limits.mjs';

export const path = '/what-it-does';

/** @param {import('../components/layout.mjs').PageContext} context */
export function render(context) {
  const { record, site } = context;
  const { run, excerpts, model, development, runtime, download, cpu_profile: cpu, collection, observation_comparison: comparison } = record;
  const { console_records: consoles, workbench_views: views, report_drafts: drafts, tool_connection: connection, journey, chat, signals, decisions } = record;
  const downloads = downloadSizes(record);
  const [receipt, invoice] = run.findings;
  const { peer, overview, coverage } = run;
  const conclusionOf = (/** @type {any[]} */ cases, /** @type {string} */ id) => cases.find((entry) => entry.id === id)?.conclusion;
  const focused = Object.fromEntries(development.focused.map((/** @type {any} */ entry) => [entry.id, entry]));
  const memory = `${Math.round(run.machine.total_memory_bytes / 1e9)} GB`;
  const compared = peer.rows.filter((/** @type {any} */ row) => !row.excluded);
  const count = (/** @type {string} */ conclusion) => run.findings.filter((/** @type {any} */ finding) => finding.conclusion === conclusion).length;
  const otherModels = consoles.models.list.slice(1);
  const access = excerpts.receipt_handler.access;

  holds(receipt.conclusion === 'supported' && invoice.conclusion === 'rejected', 'receipt supported, invoice rejected');
  holds([receipt, invoice].every((finding) => finding.runtime_verification === 'not_attempted'), 'runtime check not attempted');
  holds(run.target_code_executed === false, 'app code executed: no');
  holds(run.proposal.status === 'refused', 'the fix proposal was refused');
  holds(conclusionOf(development.phone_pair, 'D2') === 'Inconclusive', 'the phone number case ended as Inconclusive');
  holds(!focused.B1.protected && focused.B1.focused === 'Inconclusive', 'the unsafe query ended as Inconclusive');
  holds(run.machine.cpu.includes('i5-1135G7') && run.machine.gpu.includes('MX350'), 'measured on an i5-1135G7 with MX350 graphics');
  holds(run.question_limit === 2, 'two-question review');
  holds(compared.length === peer.compared && peer.deviation.missing === 'owner', 'the compared places and the missing check');
  holds(compared.filter((/** @type {any} */ row) => row.applied.includes('owner')).length === peer.deviation.peers_applying, '10 of 11 check the owner');
  holds(receipt.judgments.length === 3 && invoice.judgments.length === 3, 'three judgments each');
  holds(download.has_cpu_profile && download.investigator_same_as_source && download.source_files_checked > 0, 'the download holds the same code as the source, second profile included');
  holds(download.model_loaded === false && download.clean_user_profile === false, 'the download has run no review, and has only been tried on the laptop it was built on');
  holds(cpu.from_source, 'the one run of the second profile was done from source');
  holds(cpu.same_computer_as_recorded_run, 'every review so far ran on one laptop');
  holds(cpu.first_use_check.outcome === 'passed' && cpu.review.lifecycle === 'completed' && cpu.review.exit === 0, 'the second profile has completed one real run');
  holds(
    cpu.review.findings.every((/** @type {any} */ finding, /** @type {number} */ index) => finding.route === run.findings[index].route && finding.conclusion === run.findings[index].conclusion),
    'the second profile gave the same two answers as the recorded test',
  );
  // The second way of looking: built, run once on the practice app, and not yet settled by the model.
  holds(collection.external_access === false && collection.loopback_only && collection.runner === 'hash_pinned_owned_tandir', 'requests go only to the bundled practice app on the same computer');
  holds(collection.human_review === 'pending' && collection.imported === false, 'the recorded collection has not been reviewed into evidence');
  holds(comparison.acceptance_met === false && comparison.conditions.every((/** @type {any} */ entry) => entry.conclusion === 'inconclusive'), 'every recorded judgment of the replies ended Inconclusive');
  holds(comparison.approaches.length === 4 && comparison.conditions.filter((/** @type {any} */ entry) => entry.case === 'receipt-issue').length === 4, 'the receipt evidence was judged four ways');
  holds(access.start === access.end, 'one line loads the order');
  holds(otherModels.length === 4 && otherModels.every((/** @type {any} */ entry) => entry.quality === 'untested' && !entry.installed), 'four other models are listed, none installed or tried');
  holds(consoles.ask.generated_by === 'saved_evidence' && consoles.ask.finding === receipt.display_id, 'the question about the saved finding was answered from saved evidence');
  holds(views.captures === 24 && views.signed_in_acceptance === false && views.fresh_model_acceptance === false, 'the workbench’s new screens were captured with display fixtures only');
  holds(drafts.published === false && drafts.synthetic_only, 'report drafts came from made-up cases and none was exported');
  // The website test and the plain question, as their own records describe them.
  holds(journey.mode === 'owned_fixture' && journey.supported === 0 && journey.findings > 0 && journey.requests <= journey.max_requests, 'the website test ran on the practice website, within its limits, and left only leads');
  holds(download.owned_website_completed === true && download.model_planning_qualified === false, 'the package finished the practice website test; the AI model is not yet trusted to plan the steps');
  holds(chat.mixed_general_declined === true && /not a finding/.test(chat.basis), 'a general answer is labelled as such, and one general part declined to answer');
  holds(journey.browser_used && journey.signup_approved && journey.created === 1 && journey.signed_in === 2, 'the website test used its own browser, signed in two accounts and created one through an approved sign-up');
  holds(['captcha', 'one_time_code'].every((kind) => journey.handed_over.includes(kind)) && journey.commands.includes('stop'), 'CAPTCHAs and one-time codes go to a person, and a test can be stopped');
  holds(signals.config_rules.join() === 'config-fastapi-debug,config-httpx-tls', 'the two risky settings are FastAPI debug mode and HTTPX certificate checks');
  holds(decisions.join() === 'open,dismissed,accepted_risk,resolved', 'a finding can be dismissed, accepted as a risk or resolved');
  holds(runtime.replay.after.outcome === 'fixed', 'after the hand-written fix the leak stopped');
  holds(connection.lookups.length === 4, 'the tool connection offers four lookups');
  websiteLimits(download);

  const head = html`<header class="page-head">
  <div class="wrap">
    <h1>${t('What Plumb can do', 'Plumb nimalar qila oladi')}</h1>
    <p class="lede">${t(
      'The whole tool on one page: what it does and does not do, what using it looks like, every command, and whether you can run it today.',
      'Butun vosita bitta sahifada: nima qiladi va nima qilmaydi, undan foydalanish qanday ko‘rinadi, barcha buyruqlar va bugun ishlatib bo‘ladimi.',
    )}</p>
    ${inShort([
      t('Reading a web app’s code for places that show someone else’s data is shown working, on one practice app.', 'Veb-ilova kodidan begona ma’lumot ochilib qoladigan joylarni topish bitta sinov ilovasida ishlab ko‘rsatilgan.'),
      t('Working from an app’s answers, and answering questions in your own words, are built but not settled.', 'Ilova javoblari asosida tekshirish va o‘z so‘zlaringiz bilan berilgan savollarga javob berish qurilgan, lekin hali yakuniy tasdiqlanmagan.'),
      t('It runs in a terminal or in your browser, on Windows, on your own computer.', 'U terminalda yoki brauzerda, Windows’da, o‘z kompyuteringizda ishlaydi.'),
    ])}
  </div>
</header>`;



  const glance = html`<section class="band" aria-labelledby="glance-h">
  <div class="wrap">
    <div class="lead-in">
      <h2 id="glance-h">${t('What it does, what it doesn’t, and what nobody knows yet.', 'Nima qiladi, nima qilmaydi va nima hali noma’lum.')}</h2>
      <p class="lead-note">${t(
        'Made for small teams with nobody to check their code for security, and for code that must not leave the company.',
        'Kodini xavfsizlik jihatidan tekshiradigan mutaxassisi yo‘q kichik jamoalar uchun, shuningdek kompaniyadan tashqariga chiqmasligi kerak bo‘lgan kod uchun yaratilgan.',
      )}</p>
    </div>
    <div class="glance" id="glance">
      <div>
        <h3>${glyph('dot')} ${t('It does', 'Qiladi')}</h3>
        <ul class="limits">
          ${t(
            html`<li>Reads the code of a web app written in Python with FastAPI or TypeScript with Next.js, and lists every place that loads someone’s data.</li>
          <li>Notices the one place that skips a check all its neighbours make, like the receipt above.</li>
          <li>Asks a small AI model on your laptop short questions about that place, and looks for a reason it might be fine after all.</li>
          <li>Shows the file and lines behind every answer, and saves a report you can open in any browser.</li>
          <li>Takes a plain sentence, such as “check order ownership”, as an instruction, and answers questions in plain words: general ones, and ones about a saved result.</li>
          <li>Tests a website you may test, signed in as your test accounts, once you approve its plan.</li>
          <li>Works from saved requests and replies when there is no code to read.</li>
          <li>Notes secrets left in the code, risky settings and packages with a known advisory, kept apart from its findings.</li>`,
            html`<li>Python (FastAPI) yoki TypeScript (Next.js) da yozilgan veb-ilova kodini o‘qiydi va kimningdir ma’lumoti yuklanadigan barcha joylarni ro‘yxatga oladi.</li>
          <li>Qo‘shni joylarning hammasida bor tekshiruv qaysi joyda tushib qolganini sezadi. Yuqoridagi chek shunga misol.</li>
          <li>Noutbukingizda ishlaydigan kichik SI modeliga o‘sha joy haqida qisqa savollar beradi va xavotirga asos yo‘qligini ko‘rsatadigan sabab qidiradi.</li>
          <li>Har bir javob qaysi fayl va qatorlarga tayanganini ko‘rsatadi, natijani istalgan brauzerda ochiladigan hisobot qilib saqlaydi.</li>
          <li>«Buyurtma egaligini tekshir» kabi oddiy jumlani topshiriq sifatida qabul qiladi, oddiy so‘zlar bilan berilgan savollarga javob beradi: umumiy savollarga ham, saqlangan natija haqidagilariga ham.</li>
          <li>Sinashga ruxsatingiz bor saytni, rejasini tasdiqlaganingizdan keyin, test hisoblaringiz bilan kirib sinaydi.</li>
          <li>O‘qiydigan kod bo‘lmasa, saqlab olingan so‘rov va javoblar asosida ishlaydi.</li>
          <li>Kodda qolib ketgan maxfiy kalitlar, xavfli sozlamalar va zaifligi ma’lum paketlarni qayd etadi, ularni topilmalardan alohida saqlaydi.</li>`,
          )}
        </ul>
      </div>
      <div>
        <h3>${glyph('ring')} ${t('It does not', 'Qilmaydi')}</h3>
        <ul class="limits">
          ${t(
            html`<li>Upload your code anywhere. Once it is set up, reading code needs no internet.</li>
          <li>Run your app’s code, or send a request you have not approved. So far it has sent requests only to its own practice app and its own practice website.</li>
          <li>Act on a question. Asking can never start a review, send a request or change a finding.</li>
          <li>Fix the code for you. In the recorded test its suggested fix was broken, so none was offered.</li>
          <li>Promise that your app is safe. An empty report only means nothing was found in what was checked.</li>`,
            html`<li>Kodingizni hech qayerga yubormaydi. O‘rnatib bo‘lingach, kodni o‘qishga internet kerak emas.</li>
          <li>Ilovangiz kodini ishga tushirmaydi va siz tasdiqlamagan so‘rovni yubormaydi. Hozircha u faqat o‘zining sinov ilovasi va o‘zining sinov saytiga so‘rov yuborgan.</li>
          <li>Savol asosida ish boshlab yubormaydi. Savol berish tekshiruvni boshlamaydi, so‘rov yubormaydi va topilmani o‘zgartirmaydi.</li>
          <li>Kodni siz uchun tuzatmaydi. Sinovda u taklif qilgan tuzatish xato chiqdi, shuning uchun hisobotga kiritilmadi.</li>
          <li>Ilovangiz xavfsiz deb kafolat bermaydi. Hisobot bo‘sh bo‘lsa, bu faqat tekshirilgan qismda hech narsa topilmaganini bildiradi.</li>`,
          )}
        </ul>
      </div>
      <div>
        <h3>${glyph('half')} ${t('Nobody knows yet', 'Hali noma’lum')}</h3>
        <ul class="limits">
          ${t(
            html`<li>How often it is right. It has been shown working on one practice app, not measured on real projects.</li>
          <li>Whether its AI model can judge an app from replies alone. In the one comparison on record, every answer was Inconclusive.</li>
          <li>Whether it runs on your computer. Every review so far ran on one laptop. Plumb can now start a review on other 64-bit Windows computers, but nobody has tried that on a second computer yet.</li>
          <li>How well it finds other kinds of flaw. In tests it missed an unsafe database query and an exposed phone number.</li>
          <li>Whether a larger AI model would help. Plumb lists ${fact(otherModels.length)} others; none has been downloaded or tried.</li>`,
            html`<li>Qanchalik tez-tez to‘g‘ri topishi. U bitta sinov ilovasida ishlab ko‘rsatilgan, haqiqiy loyihalarda o‘lchanmagan.</li>
          <li>SI modeli ilovani faqat javoblariga qarab baholay olishi. Qayd etilgan yagona taqqoslashda barcha javoblar «Noaniq» bo‘lgan.</li>
          <li>Sizning kompyuteringizda ishlay olishi. Hozirgacha barcha tekshiruvlar bitta noutbukda o‘tkazilgan. Plumb endi boshqa 64 bitli Windows kompyuterlarda ham tekshiruvni boshlay oladi, lekin buni ikkinchi kompyuterda hali hech kim sinab ko‘rmagan.</li>
          <li>Boshqa turdagi xatolarni qanchalik yaxshi topishi. Sinovlarda u ma’lumotlar bazasiga xavfli so‘rovni ham, oshkor bo‘lgan telefon raqamini ham aniqlay olmagan.</li>
          <li>Kattaroq SI modeli foyda berishi. Plumb ro‘yxatida yana ${fact(otherModels.length)} ta model bor, lekin ularning birortasi yuklab olinmagan va sinab ko‘rilmagan.</li>`,
          )}
        </ul>
      </div>
    </div>
    <p class="more"><a href="/evidence">${t('Every strength and limit, with the records behind them', 'Barcha imkoniyat va cheklovlar, ularning yozuvlari bilan')}</a></p>
  </div>
</section>`;

  const use = band({
    id: 'use',
    heading: t('What it looks like to use.', 'Undan foydalanish qanday ko‘rinadi.'),
    intro: html`<p>${t(
      'Plumb runs in a terminal, the text window where you type commands. This is what the review printed in the recorded test, word for word. Numbered notes explain it.',
      'Plumb terminalda, ya’ni buyruqlar yoziladigan matnli oynada ishlaydi. Quyida yozib olingan sinovda tekshiruv chiqargan matn so‘zma-so‘z berilgan. Raqamli izohlar uni tushuntiradi.',
    )}</p>`,
    body: html`<div class="use">
      ${reviewConsole(run, { map: 1, questions: 2, receipt: 3, invoice: 4, saved: 5 })}
      <ol class="notes">
        <li><span class="callout">1</span><p>${t('Plumb maps the app first. No AI is involved yet.', 'Plumb avval ilova xaritasini tuzadi. Bu bosqichda SI ishlatilmaydi.')}</p></li>
        <li><span class="callout">2</span><p>${t('Each of these lines is one request the AI model answered, on this laptop.', 'Bu qatorlarning har biri SI modeli shu noutbukning o‘zida javob bergan bitta so‘rov.')}</p></li>
        <li><span class="callout">3</span><p>${t(
          html`The receipt: <strong>Supported</strong>. Nothing in the code limits a receipt to its owner.`,
          html`Chek: <strong>Tasdiqlandi</strong>. Kodda chekni faqat egasiga ko‘rsatadigan hech qanday tekshiruv yo‘q.`,
        )}</p></li>
        <li><span class="callout">4</span><p>${t(
          html`The invoice: <strong>Rejected</strong>. A check in another file protects it, so it is not reported.`,
          html`Hisob-faktura: <strong>Rad etildi</strong>. Uni boshqa fayldagi tekshiruv himoya qiladi, shuning uchun u xato sifatida ko‘rsatilmaydi.`,
        )}</p></li>
        <li><span class="callout">5</span><p>${t(
          html`Where the report was saved. ${fact(`plumb report ${shortRun(run.id)}`)} opens it again without the AI model.`,
          html`Hisobot saqlangan joy. ${fact(`plumb report ${shortRun(run.id)}`)} buyrug‘i uni SI modelisiz qayta ochadi.`,
        )}</p></li>
      </ol>
    </div>
    <figure class="report-figure">
      ${reportShot('summary', t(`The saved report: ${count('supported')} supported, ${count('rejected')} rejected, and the list of findings`, `Saqlangan hisobot: ${count('supported')} ta tasdiqlangan, ${count('rejected')} ta rad etilgan va topilmalar ro‘yxati`), [1152, 962])}
      <figcaption class="small">${t(
        html`The report from that run, opened in a browser. It is a picture of the <a href="/saved-report/report.html">published report file</a>, not a mock-up.`,
        html`O‘sha tekshiruv hisoboti brauzerda ochilgan holda. Bu <a href="/saved-report/report.html">e’lon qilingan hisobot faylining</a> rasmi, maket emas.`,
      )}</figcaption>
    </figure>`,
  });

  const bench = html`<section class="band" id="bench" aria-labelledby="bench-h">
  <div class="wrap">
    <div class="lead-in">
      <h2 id="bench-h">${t('Or in your browser.', 'Yoki brauzeringizda.')}</h2>
      <p class="lead-note">${t(
        html`${fact('plumb web')} opens the workbench: the same reviews, findings, questions, assessments and website tests, with forms in place of commands. It runs on your computer and starts no AI model by itself.`,
        html`${fact('plumb web')} buyrug‘i brauzerdagi interfeysni ochadi: o‘sha tekshiruvlar, topilmalar, savollar, veb-tekshiruvlar va sayt sinovlari, faqat buyruqlar o‘rniga shakllar bilan. U kompyuteringizning o‘zida ishlaydi va o‘zicha SI modelini ishga tushirmaydi.`,
      )}</p>
    </div>
    <figure class="bench-figure">
      ${workbenchShot('case', t('Plumb’s workbench in a browser: one finding, the table comparing it with its neighbours, and the cited code', 'Plumbning brauzerdagi interfeysi: bitta topilma, uni qo‘shnilari bilan solishtiruvchi jadval va ko‘rsatilgan kod'), [1440, 1000])}
      <figcaption class="small">${t(
        'One finding in the workbench: the claim, its neighbours side by side, and the cited code. A capture of the real screen showing an earlier saved run, not a mock-up. The workbench passes its software tests; a full walk-through in a signed-in browser has not been completed.',
        'Interfeysdagi bitta topilma: da’vo, uning qo‘shnilari yonma-yon va ko‘rsatilgan kod. Bu maket emas, avvalroq saqlangan tekshiruv ochilgan haqiqiy ekranning tasviri. Interfeys dasturiy testlardan o‘tadi, lekin hisobga kirilgan brauzerda boshidan oxirigacha tekshirib chiqilmagan.',
      )}</figcaption>
    </figure>
  </div>
</section>`;

  const ask = band({
    id: 'ask',
    heading: t('Ask it in your own words.', 'O‘z so‘zlaringiz bilan so‘rang.'),
    intro: html`<div class="stack-gap">
      ${standing('half', t('Built. Questions about a project not recorded yet', 'Qurilgan. Loyiha haqidagi savollar hali qayd etilmagan'))}
      <p>${t(
        'Type a question about a project, a finished review or an assessment. The AI model answers on your computer and has to point to the exact lines or replies it relies on.',
        'Loyiha, tugagan tekshiruv yoki veb-tekshiruv haqida savol yozing. SI modeli kompyuteringizning o‘zida javob beradi va tayangan qator yoki javoblarni aniq ko‘rsatishi shart.',
      )}</p>
      <p>${t(
        html`Or type ${fact('plumb')} and ask anything, as you would ask a person. A general answer is labelled as general knowledge and is never a finding about your app. One such session was recorded on ${day(chat.recorded_at)}.`,
        html`Yoki ${fact('plumb')} deb yozib, odamdan so‘ragandek istalgan savolni bering. Umumiy javob umumiy bilim deb belgilanadi va hech qachon ilovangiz haqidagi topilma hisoblanmaydi. Bunday suhbat ${day(chat.recorded_at)} kuni bir marta yozib olingan.`,
      )}</p>
    </div>`,
    body: html`<div class="stack-gap">
      <figure class="report-figure is-inline">
        ${workbenchShot('ask', t('The question box of Plumb’s workbench, with an answer that cites the practice app’s receipt code and lists what is still unknown', 'Plumb interfeysidagi savol maydoni: javob sinov ilovasining chek kodiga havola qiladi va nima hali noma’lumligini sanab o‘tadi'), [1056, 1062])}
        <figcaption class="small">${t(
          'The question box in the workbench. The answer text in this picture is a stand-in, and the screen labels it so, because no real conversation about this code has been recorded yet. The code it points to is the practice app’s real receipt code.',
          'Interfeysdagi savol maydoni. Bu rasmdagi javob matni namuna, ekranning o‘zida ham shunday deb yozilgan, chunki bu kod haqida haqiqiy suhbat hali qayd etilmagan. U ko‘rsatayotgan kod esa sinov ilovasining haqiqiy chek kodi.',
        )}</figcaption>
      </figure>
      <ul class="limits">
        ${t(
          html`<li><strong>Every answer shows its evidence.</strong> Ordinary code checks that each cited line or reply exists as quoted. What the answer cannot establish is listed under “Still unknown”.</li>
        <li><strong>A question cannot act.</strong> Asking never starts a review, sends a request, approves a scope or changes a finding.</li>
        <li><strong>There is a quick way without the AI model.</strong> ${fact('plumb ask')} looks up a saved finding and returns its evidence and limits as they were saved.</li>`,
          html`<li><strong>Har bir javob o‘z dalilini ko‘rsatadi.</strong> Ko‘rsatilgan har bir qator yoki javob aynan keltirilganidek mavjudligini oddiy dastur tekshiradi. Javob aniqlab bera olmagan narsalar «Still unknown» («Hali noma’lum») ostida sanab o‘tiladi.</li>
        <li><strong>Savol hech narsani ishga tushira olmaydi.</strong> Savol berish tekshiruvni boshlamaydi, so‘rov yubormaydi, qamrovni tasdiqlamaydi va topilmani o‘zgartirmaydi.</li>
        <li><strong>SI modelisiz tez yo‘l ham bor.</strong> ${fact('plumb ask')} saqlangan topilmani topib, uning dalillari va cheklovlarini saqlangan holicha qaytaradi.</li>`,
        )}
      </ul>
    </div>`,
  });

  /**
   * One line of the list of everything Plumb can do: how far it has been checked, what it is
   * in plain words, and what you type.
   * @param {'dot' | 'half'} mark @param {unknown} name @param {unknown} words @param {string[]} commands
   */
  const can = (mark, name, words, commands) => html`<li class="can">
        ${glyph(mark, mark === 'dot' ? t('Shown working, with a saved record', 'Ishlashi ko‘rsatilgan, saqlangan yozuvi bor') : t('Built; not settled yet', 'Qurilgan, lekin hali yakuniy tasdiqlanmagan'))}
        <div class="can-what"><h4>${name}</h4><p>${words}</p></div>
        <p class="can-type" lang="en">${commands.map((line, index) => html`${index ? html`<br>` : ''}<span class="fact">${line.split(/ (?=[-<"]|plumb )/).map((part, position) => html`${position ? ' ' : ''}<span class="arg">${part}</span>`)}</span>`)}</p>
      </li>`;

  const everything = html`<section class="band" id="everything" aria-labelledby="everything-h">
  <div class="wrap">
    <div class="lead-in">
      <h2 id="everything-h">${t('Everything Plumb can do today.', 'Plumb bugun nimalarni qila oladi.')}</h2>
      <div>
        <p class="lead-note">${t(
          'The whole tool on one page. The mark in front of each line says how far that part has been checked.',
          'Butun vosita bitta sahifada. Har bir qator oldidagi belgi o‘sha qism qanchalik tekshirilganini bildiradi.',
        )}</p>
        <ul class="legend legend-row">
          <li>${glyph('dot')} ${t('Shown working, with a saved record', 'Ishlashi ko‘rsatilgan, saqlangan yozuvi bor')}</li>
          <li>${glyph('half')} ${t('Built and tested as software; not settled in real use', 'Qurilgan va dastur sifatida sinalgan, amalda hali tasdiqlanmagan')}</li>
        </ul>
      </div>
    </div>
    <div class="sheet cans">
      <section class="can-group" aria-labelledby="can-code">
        <h3 id="can-code">${t('Read the code', 'Kodni o‘qish')}</h3>
        <ul>
          ${can('dot', t('Map a project', 'Loyiha xaritasini tuzish'), t(
            html`Lists every address, the checks in front of it and the data behind it. No AI model. The recorded test mapped ${fact(overview.included_files)} files and found ${fact(overview.access_paths)} places where data is loaded.`,
            html`Har bir manzilni, undagi tekshiruvlarni va ortidagi ma’lumotlarni ro‘yxatga oladi. SI modeli ishlatilmaydi. Yozib olingan sinovda ${fact(overview.included_files)} ta fayl xaritaga tushirilib, ma’lumot yuklanadigan ${fact(overview.access_paths)} ta joy topilgan.`,
          ), ['plumb inspect <folder>'])}
          ${can('dot', t('Review it for access flaws', 'Ruxsat xatolarini qidirish'), t(
            'The core of Plumb. In the recorded test it found the receipt flaw and cleared the protected invoice.',
            'Plumbning asosiy ishi. Yozib olingan sinovda u chekdagi xatoni topdi va himoyalangan hisob-fakturani oqladi.',
          ), ['plumb review <folder>'])}
          ${can('half', t('Say what to check in a sentence', 'Nimani tekshirishni bir jumla bilan aytish'), t(
            'Plumb turns the sentence into a scope and shows it to you. Nothing runs until you confirm. It passes its software tests; no recorded review has been started this way.',
            'Plumb jumlani qamrovga aylantirib, sizga ko‘rsatadi. Siz tasdiqlamaguningizcha hech narsa boshlanmaydi. Dasturiy testlardan o‘tadi, lekin shu yo‘l bilan boshlangan tekshiruv hali qayd etilmagan.',
          ), ['plumb review <folder> --prompt "Check order ownership"'])}
          ${can('half', t('Look for other kinds of flaw', 'Boshqa turdagi xatolarni qidirish'), t(
            'Unsafe database queries, file paths that escape their folder, data leaking to the browser. Misses are on record for these.',
            'Ma’lumotlar bazasiga xavfli so‘rovlar, o‘z papkasidan chiqib ketadigan fayl yo‘llari, brauzerga sizib chiqadigan ma’lumotlar. Bularda aniqlanmay qolgan xatolar qayd etilgan.',
          ), ['--family injection', '--family path_traversal', '--family nextjs_exposure'])}
          ${can('half', t('Note secrets, risky settings and vulnerable packages', 'Maxfiy kalitlar, xavfli sozlamalar va zaif paketlarni qayd etish'), t(
            html`Beside its findings, a review notes the shape of a secret left in the code without ever showing its value, ${fact(signals.config_rules.length)} risky settings (debug mode left on in FastAPI, certificate checks turned off in HTTPX), and package versions named in its offline advisory list. That list holds ${fact(signals.advisories)} advisories from the ${signals.advisories_from}, dated ${day(signals.advisories_dated)}. These notes are never counted as findings.`,
            html`Tekshiruv topilmalar yonida koddagi maxfiy kalit izini (qiymatini hech qachon ko‘rsatmay), ${fact(signals.config_rules.length)} ta xavfli sozlamani (FastAPI’da yoqiq qolgan debug rejimi, HTTPX’da o‘chirilgan sertifikat tekshiruvi) va internetsiz ishlaydigan ogohlantirishlar ro‘yxatidagi paket versiyalarini qayd etadi. Bu ro‘yxatda ${signals.advisories_from} manbasidan olingan ${fact(signals.advisories)} ta ogohlantirish bor, sanasi ${day(signals.advisories_dated)}. Bu qaydlar hech qachon topilma sifatida sanalmaydi.`,
          ), ['plumb review <folder>'])}
          ${can('half', t('Write down the rule the code must follow', 'Kod amal qilishi kerak bo‘lgan qoidani yozib qo‘yish'), t(
            'Such as “only the owner may see an order”, tied to the exact code that was reviewed. It tells Plumb what was intended; it is not proof that the code does it.',
            '«Buyurtmani faqat egasi ko‘ra oladi» kabi qoida, aynan tekshirilgan kodga bog‘lab yoziladi. U Plumbga nima ko‘zda tutilganini aytadi, lekin kod shunday ishlashini isbotlamaydi.',
          ), ['plumb policy <run-id> --guard owner --statement "Owner required"'])}
        </ul>
      </section>
      <section class="can-group" aria-labelledby="can-ask">
        <h3 id="can-ask">${t('Ask', 'So‘rash')}</h3>
        <ul>
          ${can('half', t('Ask a general question in plain words', 'Oddiy so‘zlar bilan umumiy savol berish'), t(
            html`Type ${factWhole('plumb')} and write as you would to a person. The model on your computer answers, and every answer says what it rests on: general knowledge is never a finding about your app, and a message cannot start a test. Recorded on ${day(chat.recorded_at)}: a general question answered in ${fact(`${seconds(Number(chat.model_seconds.toFixed(1)))} s`)}; in a mixed question, the general part declined to answer.`,
            html`${factWhole('plumb')} deb yozing va odamga yozgandek savol bering. Kompyuteringizdagi model javob beradi va har bir javob nimaga tayanganini aytadi: umumiy bilim ilovangiz haqidagi topilma hisoblanmaydi, xabar esa sinovni boshlay olmaydi. ${day(chat.recorded_at)} kuni yozib olingan: umumiy savolga ${fact(`${seconds(Number(chat.model_seconds.toFixed(1)))} s`)} ichida javob berildi; aralash savolda esa umumiy qism javob berishdan bosh tortdi.`,
          ), ['plumb', `plumb chat "${chat.prompt}"`])}
          ${can('dot', t('Ask about a saved finding', 'Saqlangan topilma haqida so‘rash'), t(
            html`Answered from the saved evidence, without the AI model. Run for this site on ${day(consoles.recorded_at)}: it returned ${fact(consoles.ask.finding)} with its ${fact(consoles.ask.exhibits)} cited places and ${fact(consoles.ask.limitations)} stated limits.`,
            html`Javob SI modelisiz, saqlangan dalillardan olinadi. Shu sayt uchun ${day(consoles.recorded_at)} kuni ishga tushirilgan: u ${fact(consoles.ask.finding)} topilmasini, u tayangan ${fact(consoles.ask.exhibits)} ta joy va ${fact(consoles.ask.limitations)} ta cheklov bilan qaytardi.`,
          ), [`plumb ask <run-id> "${consoles.ask.prompt}"`])}
          ${can('half', t('Ask anything about a project, a review or an assessment', 'Loyiha, tekshiruv yoki veb-tekshiruv haqida istalgan savolni berish'), t(
            'The AI model answers on your computer and must point to exact lines or replies; what it cannot know is listed. A question can never start a review, send a request or change a finding. It passes its software tests; no real conversation of this kind has been recorded yet.',
            'SI modeli kompyuteringizning o‘zida javob beradi va aniq qator yoki javoblarni ko‘rsatishi shart; bila olmagan narsalari alohida sanab o‘tiladi. Savol tekshiruvni boshlay olmaydi, so‘rov yubora olmaydi va topilmani o‘zgartira olmaydi. Dasturiy testlardan o‘tadi, lekin bunday haqiqiy suhbat hali qayd etilmagan.',
          ), ['plumb chat <id> "How is the caller tied to an order?"'])}
        </ul>
      </section>
      <section class="can-group" aria-labelledby="can-web">
        <h3 id="can-web">${t('Watch the answers', 'Javoblarni kuzatish')}</h3>
        <ul>
          ${can('half', t('Test a website you may test', 'Sinashga ruxsatingiz bor saytni sinash'), t(
            html`You describe the site, the test accounts, what may be done and the limits. Plumb shows its plan and sends nothing until you approve it. Then, in a browser of its own, it signs in as each account, can create one through a sign-up you allowed, and compares what each one gets, in a private report. A CAPTCHA or a one-time code is handed to you to complete. You can stop the test at any time, and an interrupted test continues only when you say so. Run on Plumb’s own practice website on ${day(journey.recorded_at)}: ${fact(journey.signed_in)} accounts signed in and ${fact(journey.created)} created, ${fact(journey.requests)} of ${fact(journey.max_requests)} allowed requests, ${fact(journey.findings)} leads and no confirmed finding. The AI model is not yet trusted to plan the steps, so plain code and you choose them. ${externalLimits(download)}`,
            html`Siz saytni, test hisoblarini, nima qilish mumkinligini va cheklovlarni yozasiz. Plumb rejasini ko‘rsatadi va siz tasdiqlamaguningizcha hech narsa yubormaydi. Keyin o‘z brauzerida har bir hisob bilan kiradi, siz ruxsat bergan ro‘yxatdan o‘tish orqali yangi hisob ocha oladi va har biri nima olganini shaxsiy hisobotda solishtiradi. CAPTCHA yoki bir martalik kodni siz kiritasiz. Sinovni istalgan payt to‘xtata olasiz, to‘xtab qolgan sinov esa faqat siz aytganingizda davom etadi. ${day(journey.recorded_at)} kuni Plumbning o‘z sinov saytida ishga tushirilgan: ${fact(journey.signed_in)} ta hisob bilan kirildi va ${fact(journey.created)} tasi ochildi, ruxsat etilgan ${fact(journey.max_requests)} ta so‘rovdan ${fact(journey.requests)} tasi ishlatildi, ${fact(journey.findings)} ta iz topildi, tasdiqlangan topilma yo‘q. SI modeliga qadamlarni rejalashtirish hali ishonib topshirilmagan, ularni oddiy kod va siz tanlaysiz. ${externalLimits(download)}`,
          ), ['plumb website setup', 'plumb website run <journey-id>', 'plumb website stop <journey-id>'])}
          ${can('half', t('Work from saved requests and replies', 'Saqlab olingan so‘rov va javoblar bilan ishlash'), t(
            'Bring records you collected yourself. Plumb removes passwords and cookies, compares two accounts on the same item, and draws up a map and a checklist. It passes its software tests on made-up records.',
            'O‘zingiz yig‘gan yozuvlarni bering. Plumb ulardagi parol va cookie’larni olib tashlaydi, ikki hisobning bitta narsaga olgan javobini solishtiradi, xarita va tekshirish ro‘yxatini tuzadi. Soxta yozuvlarda dasturiy testlardan o‘tadi.',
          ), ['plumb assess <id> --import-records <file>'])}
          ${can('dot', t('Collect from the practice app, with your approval', 'Sinov ilovasidan ruxsatingiz bilan javob yig‘ish'), t(
            html`Recorded once: ${fact(collection.requests)} requests in ${fact(`${seconds(Number(collection.seconds.toFixed(2)))} s`)}. ${websiteLimits(download)}`,
            html`Bir marta qayd etilgan: ${fact(`${seconds(Number(collection.seconds.toFixed(2)))} s`)} ichida ${fact(collection.requests)} ta so‘rov. ${websiteLimits(download)}`,
          ), ['plumb assess <id> --lab-preview pair'])}
          ${can('half', t('Have the AI model judge the replies', 'Javoblarni SI modeliga baholatish'), t(
            html`Three separate judgments that must agree. It ran for real on ${day(comparison.recorded_at)}, and every result was Inconclusive.`,
            html`Bir-biriga mos kelishi shart bo‘lgan uchta alohida baho. ${day(comparison.recorded_at)} kuni haqiqatan ishga tushirilgan, barcha natijalar «Noaniq» bo‘lgan.`,
          ), ['plumb assess <id> --analyze <comparison-id>'])}
          ${can('half', t('Draft a private report', 'Shaxsiy hisobot qoralamasini tayyorlash'), t(
            html`You preview it, review it and only then save it. Nothing is ever submitted for you. ${fact(drafts.count)} drafts were written from made-up cases; none was exported.`,
            html`Avval ko‘rib chiqasiz, tekshirasiz, shundan keyingina saqlaysiz. Siz uchun hech narsa hech qayerga yuborilmaydi. Soxta holatlar asosida ${fact(drafts.count)} ta qoralama yozilgan, birortasi eksport qilinmagan.`,
          ), ['plumb assess <id> --report'])}
        </ul>
      </section>
      <section class="can-group" aria-labelledby="can-run">
        <h3 id="can-run">${t('Around every review', 'Har bir tekshiruv atrofida')}</h3>
        <ul>
          ${can('dot', t('Keep the report', 'Hisobotni saqlab qo‘yish'), t(
            html`Four files with the same finding numbers: ${run.saved_reports.map((/** @type {any} */ file, /** @type {number} */ index) => html`${index ? ', ' : ''}${fact(file.name)}`)}. The four from the recorded test are <a href="/recorded-run#saved">published here as saved</a>.`,
            html`Topilma raqamlari bir xil bo‘lgan to‘rtta fayl: ${run.saved_reports.map((/** @type {any} */ file, /** @type {number} */ index) => html`${index ? ', ' : ''}${fact(file.name)}`)}. Yozib olingan sinovning to‘rtta fayli <a href="/recorded-run#saved">shu yerda o‘zgarishsiz e’lon qilingan</a>.`,
          ), ['plumb report <run-id>'])}
          ${can('dot', t('Check the computer and choose a model', 'Kompyuterni tekshirish va model tanlash'), t(
            html`Plumb says what fits in the memory that is free, which model has a recorded result, and refuses to start when memory is short. <a href="/install#models">The list it printed</a>.`,
            html`Plumb bo‘sh xotiraga nima sig‘ishini va qaysi modelning qayd etilgan natijasi borligini aytadi, xotira yetmasa, ishni boshlamaydi. <a href="/install#models">U chiqargan ro‘yxat</a>.`,
          ), ['plumb doctor', 'plumb models', 'plumb calibrate'])}
          ${can('half', t('Use it in the browser', 'Brauzerda foydalanish'), t(
            html`A workbench with forms in place of commands: reviews, findings, questions, assessments and website tests. ${fact(views.captures)} pictures of its new screens were checked. A full walk-through in a signed-in browser has not been completed.`,
            html`Buyruqlar o‘rniga shakllar bilan ishlaydigan interfeys: tekshiruvlar, topilmalar, savollar, veb-tekshiruvlar va sayt sinovlari. Yangi ekranlarining ${fact(views.captures)} ta tasviri tekshirilgan. Hisobga kirilgan brauzerda boshidan oxirigacha tekshirib chiqilmagan.`,
          ), ['plumb web'])}
          ${can('half', t('Record your decision on a finding', 'Topilma bo‘yicha qaroringizni yozib qo‘yish'), t(
            'Dismissed, accepted as a risk, or resolved with the commit that fixed it. Each decision is added beside the finding with who made it and why, and never rewrites the finding or its evidence. Done in the workbench.',
            'Rad etildi, xavf sifatida qabul qilindi yoki uni tuzatgan commit bilan hal qilindi. Har bir qaror kim va nima uchun qabul qilgani bilan topilma yoniga qo‘shiladi, topilmaning o‘zini yoki dalillarini hech qachon o‘zgartirmaydi. Bu interfeysda qilinadi.',
          ), ['plumb web'])}
          ${can('dot', t('Test a fix on the practice app', 'Tuzatishni sinov ilovasida sinash'), t(
            html`A fixed script sends real requests before and after one hand-written fix. After it, the other customer was refused and the owner still got her receipt. <a href="/recorded-run#runtime">Recorded on its own</a>.`,
            html`Qat’iy belgilangan skript qo‘lda yozilgan bitta tuzatishdan oldin va keyin haqiqiy so‘rovlar yuboradi. Tuzatishdan keyin begona mijozga rad javobi berildi, buyurtma egasi esa chekini avvalgidek oldi. <a href="/recorded-run#runtime">Alohida qayd etilgan</a>.`,
          ), ['plumb replay <run-id> --finding F-01'])}
          ${can('dot', t('Let other tools read the results', 'Natijalarni boshqa vositalarga o‘qitish'), t(
            html`A read-only connection for AI coding tools (MCP): ${fact(connection.lookups.length)} lookups over saved results. It cannot start a review or change anything.`,
            html`SI dasturlash vositalari uchun faqat o‘qishga mo‘ljallangan ulanish (MCP): saqlangan natijalar ustida ${fact(connection.lookups.length)} ta so‘rov turi. U tekshiruvni boshlay olmaydi va hech narsani o‘zgartira olmaydi.`,
          ), ['python -m backend.mcp'])}
        </ul>
      </section>
    </div>
    <p class="small cans-note">${t(
      html`From source, each command starts with ${factWhole('uv run')}. In the download, ${factWhole('.\\plumb.cmd')} takes the place of ${factWhole('plumb')}.`,
      html`Manba kodidan ishlatilganda har bir buyruq ${factWhole('uv run')} bilan boshlanadi. Tayyor to‘plamda ${factWhole('plumb')} o‘rniga ${factWhole('.\\plumb.cmd')} yoziladi.`,
    )}</p>
  </div>
</section>`;

  const availability = site.download
    ? t(
        html`<p><strong>Yes, in two ways.</strong> <a href="${site.download}">Download the Windows package</a> (${fact(mb(download.archive_bytes))}), or install from the source code on <a href="${site.repository}">GitHub</a>. Both hold the same code and follow the same steps. The <a href="/install">install page</a> has every step.</p>`,
        html`<p><strong>Ha, ikki yo‘l bilan.</strong> <a href="${site.download}">Windows to‘plamini yuklab oling</a> (${fact(mb(download.archive_bytes))}) yoki Plumbni <a href="${site.repository}">GitHub</a>’dagi manba kodidan o‘rnating. Ikkalasida ham kod bir xil, qadamlari ham bir xil. Barcha qadamlar <a href="/install">o‘rnatish sahifasida</a>.</p>`,
      )
    : site.repository
    ? t(
        html`<p><strong>Yes, from the source code.</strong> The code is public in <a href="${site.repository}">the repository</a>. You need a Windows computer and a few commands, or an AI coding agent to type them for you.</p>`,
        html`<p><strong>Ha, manba kodi orqali.</strong> Kod <a href="${site.repository}">repozitoriyda</a> ochiq turibdi. Sizga Windows kompyuter va bir nechta buyruq kerak bo‘ladi. Ularni siz uchun SI agent ham yozib berishi mumkin.</p>`,
      )
    : t(
        html`<p><strong>Not as a download yet.</strong> The code and the ready-made Windows package are being prepared for public release. Until then you can <a href="/contact">ask for a copy</a>.</p>`,
        html`<p><strong>Hozircha yuklab olib bo‘lmaydi.</strong> Kod va tayyor Windows to‘plami ommaga e’lon qilishga tayyorlanmoqda. Ungacha <a href="/contact">nusxa so‘rab yozishingiz</a> mumkin.</p>`,
      );

  const today = band({
    id: 'today',
    heading: t('Can I use it today?', 'Bugun undan foydalansam bo‘ladimi?'),
    body: html`<div class="stack-gap">
      ${availability}
      <p>${t(
        'Plumb is a program for your own computer, not a website, because your code should not leave it.',
        'Plumb veb-sayt emas, o‘z kompyuteringizda ishlaydigan dastur, chunki kodingiz kompyuteringizdan tashqariga chiqmasligi kerak.',
      )}</p>
      <dl class="spec">
        ${site.download
          ? html`<div><dt>${t('The download', 'Tayyor to‘plam')}</dt>
          <dd>${t(
            html`A ZIP built on ${longDay(download.built_on)} from the same code as the source, with Python, Node and the browser view inside. This package has not yet run a review with the AI model: its checks loaded no model. It has only been tried on the laptop it was built on.`,
            html`${longDay(download.built_on)} kuni manba kodining o‘zidan yig‘ilgan ZIP fayl, ichida Python, Node va brauzerdagi interfeys bor. Bu to‘plam SI modeli bilan hali birorta ham tekshiruv o‘tkazmagan: uni sinashda model ishga tushirilmagan. U faqat o‘zi yig‘ilgan noutbukda sinab ko‘rilgan.`,
          )}</dd></div>
        <div><dt>${t('The source code', 'Manba kodi')}</dt>
          <dd>${t(
            'The same program, for people who want to read the code or change it. It needs Git, uv, Node.js and pnpm.',
            'O‘sha dasturning o‘zi, kodni o‘qib chiqmoqchi yoki o‘zgartirmoqchi bo‘lganlar uchun. Unga Git, uv, Node.js va pnpm kerak.',
          )}</dd></div>`
          : ''}
        <div><dt>${t('Which computers', 'Qaysi kompyuterlarda')}</dt>
          <dd>${t(
            html`A full review can start on any 64-bit Windows 10 or 11 computer with an Intel or AMD processor and about ${fact(gb(cpu.required_ram_bytes))} of memory free. A second profile (a tested set of settings), ${factWhole(cpu.id)}, runs the same AI model on the processor alone, so no particular graphics card is needed. It has completed one real run, from source: on ${longDay(cpu.recorded_on)}, on the laptop Plumb is developed on, it gave the same two answers as the recorded test in ${fact(cpu.review.model_requests)} requests to the model. It has not been tried on any other computer, and how fast it is there is not known.`,
            html`To‘liq tekshiruv Intel yoki AMD protsessorli, 64 bitli Windows 10 yoki 11 o‘rnatilgan istalgan kompyuterda boshlanishi mumkin, buning uchun taxminan ${fact(gb(cpu.required_ram_bytes))} operativ xotira bo‘sh bo‘lishi kerak. Ikkinchi profil (birga sinab ko‘rilgan sozlamalar to‘plami), ${factWhole(cpu.id)}, o‘sha SI modelini faqat protsessorda ishlatadi, shuning uchun ma’lum bir videokarta talab qilinmaydi. U bir marta, manba kodidan ishga tushirilgan holda, haqiqiy sinovdan o‘tgan: ${longDay(cpu.recorded_on)} kuni Plumb ishlab chiqilayotgan noutbukda modelga ${fact(cpu.review.model_requests)} ta so‘rov yuborib, yozib olingan sinovdagi ikki javobning o‘zini berdi. Boshqa hech bir kompyuterda sinab ko‘rilmagan, u yerda qanchalik tez ishlashi ham noma’lum.`,
          )}</dd></div>
        <div><dt>${t('Where it has run', 'Qayerda ishlagan')}</dt>
          <dd>${t(
            html`On one laptop only: an Intel Core i5-1135G7 (${fact(run.machine.physical_cores)} cores), ${fact(memory)} of memory and ${run.machine.gpu} graphics. Every result on this site comes from it.`,
            html`Faqat bitta noutbukda: Intel Core i5-1135G7 protsessori (${fact(run.machine.physical_cores)} yadro), ${fact(memory)} operativ xotira va ${run.machine.gpu} videokartasi. Saytdagi barcha natijalar shu noutbukda olingan.`,
          )}</dd></div>
        <div><dt>${t('The AI model', 'SI modeli')}</dt>
          <dd>${t(
            html`${model.family}, an open model, used as published. One ${fact(gb(model.size))} file, licence ${fact(model.license)}. Plumb does not train it.`,
            html`${model.family} — ochiq model, e’lon qilingan holicha ishlatiladi. Bitta ${fact(gb(model.size))} hajmli fayl, litsenziyasi ${fact(model.license)}. Plumb uni o‘qitmaydi.`,
          )}</dd></div>
        <div><dt>${t('Downloads', 'Yuklab olinadigan fayllar')}</dt>
          <dd>${t(
            html`Once, during setup: the AI model, the program that runs it and a pattern scanner (${fact(mb(record.scanner_download.size))}), which helps Plumb decide which questions to ask first. In all, at most ${fact(gb(Math.max(downloads.cpu, downloads.measured)))}. Setup shows the size, source and licence of each file before it starts.`,
            html`Faqat bir marta, o‘rnatish paytida: SI modeli, uni ishga tushiradigan dastur va andoza skaneri (${fact(mb(record.scanner_download.size))}). Skaner Plumbga qaysi savolni birinchi berishni tanlashda yordam beradi. Hammasi birga ko‘pi bilan ${fact(gb(Math.max(downloads.cpu, downloads.measured)))}. O‘rnatuvchi har bir faylning hajmi, manbasi va litsenziyasini oldindan ko‘rsatadi.`,
          )}</dd></div>
        <div><dt>${t('Time', 'Vaqt')}</dt>
          <dd>${t(
            html`The recorded review of two places took ${fact(minutes(run.elapsed_seconds))} on that laptop. That is one run, not a benchmark. Nobody knows how long a review takes on another computer.`,
            html`Ikki joyni tekshirgan yozib olingan sinov o‘sha noutbukda ${fact(minutes(run.elapsed_seconds))} davom etgan. Bu bitta ishga tushirish natijasi, tezlik o‘lchovi emas. Boshqa kompyuterda tekshiruv qancha vaqt olishi noma’lum.`,
          )}</dd></div>
      </dl>
      <div class="routes">
        <a class="route-card" href="/install"><span class="route-title">${t('Install it yourself', 'O‘zingiz o‘rnating')}</span><span class="small">${t('What it needs, each command, and what you will see.', 'Nima kerakligi, har bir buyruq va natijada nimani ko‘rishingiz.')}</span></a>
        <a class="route-card" href="/install/agent"><span class="route-title">${t('Let an AI agent install it', 'SI agentga o‘rnattiring')}</span><span class="small">${t('One message for Claude Code, Codex or a similar agent.', 'Claude Code, Codex yoki shunga o‘xshash agent uchun bitta xabar.')}</span></a>
      </div>
    </div>`,
  });


  const next = html`<section class="band band-last" aria-label="${t('Where to go next', 'Keyingi qadam')}">
  <div class="wrap next">
    <a class="next-link" href="/how-it-works"><span class="next-title">${t('How it works', 'Qanday ishlaydi')}</span><span class="small">${t('The four steps, and how the AI model is kept from guessing.', 'To‘rt qadam va SI modelining taxmin qilishiga qanday yo‘l qo‘yilmasligi.')}</span></a>
    <a class="next-link" href="/recorded-run"><span class="next-title">${t('See it work', 'Amalda ko‘rish')}</span><span class="small">${t('Every step of the recorded test, with the report files.', 'Yozib olingan sinovning har bir qadami, hisobot fayllari bilan.')}</span></a>
    <a class="next-link" href="/evidence"><span class="next-title">${t('Limits', 'Cheklovlar')}</span><span class="small">${t('What passed, what failed, and what comes next.', 'Nima o‘tdi, nima o‘tmadi va keyingi rejalar.')}</span></a>
    <a class="next-link" href="/install"><span class="next-title">${t('Get Plumb', 'O‘rnatish')}</span><span class="small">${t('Download it, or let an AI agent install it for you.', 'Yuklab oling yoki SI agentga o‘rnattiring.')}</span></a>
  </div>
</section>`;

  return page({
    path,
    title: t('What Plumb can do', 'Plumb nimalar qila oladi'),
    description: t(
      'Everything Plumb does today, what it does not do, what using it looks like in a terminal and in a browser, every command, and what it needs to run.',
      'Plumb bugun nimalar qila oladi, nima qilmaydi, terminalda va brauzerda undan foydalanish qanday ko‘rinadi, barcha buyruqlar va ishlashi uchun nima kerak.',
    ),
    body: html`${head}${glance}${use}${bench}${ask}${everything}${today}${next}`,
    context,
  });
}
