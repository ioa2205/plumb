// @ts-check
import { bobEnd, glyph, pencilMark } from '../components/glyphs.mjs';
import { band, page } from '../components/layout.mjs';
import { leak } from '../components/leak.mjs';
import { exhibit, fact, reportShot, verdict } from '../components/parts.mjs';
import { reviewConsole } from '../components/terminal.mjs';
import { gb, int, longDay, mb, minutes, shortRun } from '../lib/format.mjs';
import { holds } from '../lib/holds.mjs';
import { html } from '../lib/html.mjs';
import { t } from '../lib/lang.mjs';

export const path = '/';

/** @param {import('../components/layout.mjs').PageContext} context */
export function render(context) {
  const { record, site } = context;
  const { run, excerpts, model, development, runtime } = record;
  const [receipt, invoice] = run.findings;
  const { peer, overview, coverage } = run;
  const conclusionOf = (/** @type {any[]} */ cases, /** @type {string} */ id) => cases.find((entry) => entry.id === id)?.conclusion;
  const focused = Object.fromEntries(development.focused.map((/** @type {any} */ entry) => [entry.id, entry]));
  const memory = `${Math.round(run.machine.total_memory_bytes / 1e9)} GB`;
  const compared = peer.rows.filter((/** @type {any} */ row) => !row.excluded);
  const count = (/** @type {string} */ conclusion) => run.findings.filter((/** @type {any} */ finding) => finding.conclusion === conclusion).length;

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

  const hero = html`<section class="hero" aria-labelledby="hero-h">
  <div class="wrap hero-grid">
    <div class="hero-copy">
      <h1 class="display" id="hero-h">${t(
        'Plumb finds where your app shows people data that isn’t theirs.',
        'Plumb ilovangizda birovning ma’lumoti boshqasiga ochilib qoladigan joylarni topadi.',
      )}</h1>
      <p class="lede">${t(
        'It reads your app’s code on your own computer, with a small AI model that works offline, and points to the exact lines that cause the problem. Your code is never uploaded.',
        'U ilovangiz kodini o‘z kompyuteringizda, internetsiz ishlaydigan kichik sun’iy intellekt modeli yordamida o‘qib chiqadi va muammoga sabab bo‘lgan qatorlarni aniq ko‘rsatadi. Kodingiz hech qayerga yuborilmaydi.',
      )}</p>
      <p class="actions">
        <a class="btn btn-ink" href="#proof">${t('See a real result', 'Haqiqiy natijani ko‘rish')}</a>
        <a class="btn" href="/install">${t('Get Plumb', 'Plumbni o‘rnatish')}</a>
      </p>
      <p class="small status">${t(
        html`A working prototype for Windows. Tested on one practice app and one laptop, ${longDay(run.started_at)}.`,
        html`Windows uchun ishlaydigan prototip. ${longDay(run.started_at)} kuni bitta sinov ilovasi va bitta noutbukda sinab ko‘rilgan.`,
      )}</p>
    </div>
    ${leak(record.sample, runtime.receipt)}
  </div>
</section>`;

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
          <li>Shows the file and lines behind every answer, and saves a report you can open in any browser.</li>`,
            html`<li>Python (FastAPI) yoki TypeScript (Next.js) da yozilgan veb-ilova kodini o‘qiydi va kimningdir ma’lumoti yuklanadigan barcha joylarni ro‘yxatga oladi.</li>
          <li>Qo‘shni joylarning hammasida bor tekshiruv qaysi joyda tushib qolganini sezadi. Yuqoridagi chek shunga misol.</li>
          <li>Noutbukingizda ishlaydigan kichik SI modeliga o‘sha joy haqida qisqa savollar beradi va xavotirga asos yo‘qligini ko‘rsatadigan sabab qidiradi.</li>
          <li>Har bir javob qaysi fayl va qatorlarga tayanganini ko‘rsatadi, natijani istalgan brauzerda ochiladigan hisobot qilib saqlaydi.</li>`,
          )}
        </ul>
      </div>
      <div>
        <h3>${glyph('ring')} ${t('It does not', 'Qilmaydi')}</h3>
        <ul class="limits">
          ${t(
            html`<li>Upload your code anywhere. Once it is set up, it needs no internet.</li>
          <li>Run your app or attack it. It only reads the code.</li>
          <li>Fix the code for you. In the recorded test its suggested fix was broken, so none was offered.</li>
          <li>Promise that your app is safe. An empty report only means nothing was found in what was checked.</li>`,
            html`<li>Kodingizni hech qayerga yubormaydi. O‘rnatib bo‘lingach, internet kerak emas.</li>
          <li>Ilovangizni ishga tushirmaydi va unga hujum qilmaydi. Faqat kodini o‘qiydi.</li>
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
          <li>Whether it runs on your computer. Full reviews with the AI model start only on the one laptop model measured so far.</li>
          <li>How well it finds other kinds of flaw. In tests it missed an unsafe database query and an exposed phone number.</li>`,
            html`<li>Qanchalik tez-tez to‘g‘ri topishi. U bitta sinov ilovasida ishlab ko‘rsatilgan, haqiqiy loyihalarda o‘lchanmagan.</li>
          <li>Sizning kompyuteringizda ishlay olishi. SI modeli bilan to‘liq tekshiruv hozircha faqat o‘lchab ko‘rilgan bitta noutbuk modelida ishga tushadi.</li>
          <li>Boshqa turdagi xatolarni qanchalik yaxshi topishi. Sinovlarda u ma’lumotlar bazasiga xavfli so‘rovni ham, oshkor bo‘lgan telefon raqamini ham aniqlay olmagan.</li>`,
          )}
        </ul>
      </div>
    </div>
    <p class="more"><a href="/evidence">${t('Every strength and limit, with the records behind them', 'Barcha imkoniyat va cheklovlar, ularning yozuvlari bilan')}</a></p>
  </div>
</section>`;

  const dotRow = html`<figure class="dotrow">
    <ul aria-label="${t(`${peer.compared} places in the practice app that load an order`, `Sinov ilovasida buyurtma yuklanadigan ${peer.compared} ta joy`)}">
      ${compared.map((/** @type {any} */ row) => {
        const name = `${row.method} ${row.route}`;
        if (row.subject) {
          return html`<li class="is-odd" title="${name}"><span class="mark">${glyph('ring', t(`${name}: does not check the owner`, `${name}: egasini tekshirmaydi`))}${pencilMark}</span><span class="dot-label">${t('receipt', 'chek')}</span></li>`;
        }
        return html`<li title="${name}">${glyph('dot', t(`${name}: checks the owner`, `${name}: egasini tekshiradi`))}</li>`;
      })}
    </ul>
    <figcaption class="small">${t(
      html`Each mark is one place in the practice app that loads an order. ${glyph('dot')} checks that the order belongs to the person asking. ${glyph('ring')} does not.`,
      html`Har bir belgi sinov ilovasida buyurtma yuklanadigan bitta joy. ${glyph('dot')} buyurtma so‘rayotgan odamniki ekanini tekshiradi. ${glyph('ring')} tekshirmaydi.`,
    )}</figcaption>
  </figure>`;

  const how = band({
    id: 'how',
    heading: t('How it works, in four steps.', 'Qanday ishlaydi: to‘rt qadam.'),
    intro: html`<p>${t(
      'Ask a small AI model a big question and it gives a confident wrong answer. So Plumb never asks it one. The figures under each step come from the recorded test.',
      'Kichik SI modeliga katta savol berilsa, u ishonch bilan xato javob beradi. Shuning uchun Plumb unga katta savol bermaydi. Har bir qadam ostidagi raqamlar yozib olingan sinovdan olingan.',
    )}</p>`,
    body: html`<ol class="plumbline">
      <li>
        <h3>${t('It copies your code and maps it. No AI yet.', 'Kodni nusxalab, xaritasini tuzadi. Bu bosqichda SI ishlatilmaydi.')}</h3>
        <p>${t(
          'Plumb takes a snapshot of the project, so nothing changes halfway through. Then it lists every address the app answers, the checks in front of each one and the data behind it. It reads the files as text and never runs them.',
          'Plumb loyihadan nusxa oladi, shunda tekshiruv davomida hech narsa o‘zgarmaydi. So‘ng ilova javob beradigan har bir manzilni, ulardagi tekshiruvlarni va ular ortidagi ma’lumotlarni ro‘yxatga oladi. Fayllarni oddiy matn sifatida o‘qiydi, hech birini ishga tushirmaydi.',
        )}</p>
        <p class="step-fact">${t(
          html`${fact(overview.included_files)} files · ${fact(overview.fastapi_entries)} FastAPI routes and ${fact(overview.nextjs_entries)} Next.js entry points · ${fact(overview.access_paths)} places where data is loaded`,
          html`${fact(overview.included_files)} ta fayl · ${fact(overview.fastapi_entries)} ta FastAPI manzili va ${fact(overview.nextjs_entries)} ta Next.js kirish nuqtasi · ma’lumot yuklanadigan ${fact(overview.access_paths)} ta joy`,
        )}</p>
      </li>
      <li>
        <h3>${t('It compares places that do the same job.', 'Bir xil ish bajaradigan joylarni solishtiradi.')}</h3>
        <p>${t(
          'If ten places that open an order all check who is asking and one does not, that one gets a question. The app’s own habits are the rule, so nobody has to write rules first.',
          'Buyurtma ochiladigan o‘nta joyning hammasi so‘rayotgan odam kimligini tekshirsa-yu, bittasi tekshirmasa, savol aynan o‘sha joyga beriladi. Qoida o‘rnida ilovaning o‘z odati olinadi, shuning uchun oldindan qoida yozib o‘tirish shart emas.',
        )}</p>
        ${dotRow}
        <p class="step-fact">${t(
          html`${fact(peer.compared)} places load an order · ${fact(peer.deviation.peers_applying)} check the owner · a place is flagged only when at least ${fact(peer.min_peers)} similar places exist and ${fact(`${peer.min_share * 100}%`)} of them agree`,
          html`buyurtma ${fact(peer.compared)} ta joyda yuklanadi · ${fact(peer.deviation.peers_applying)} tasi egasini tekshiradi · kamida ${fact(peer.min_peers)} ta o‘xshash joy bo‘lib, ularning ${fact(`${peer.min_share * 100}%`)} qismi bir xil ish tutsagina joy belgilanadi`,
        )}</p>
      </li>
      <li>
        <h3>${t('It asks small questions and tries to clear the suspect.', 'Qisqa savollar beradi va shubhani yo‘qqa chiqarishga urinadi.')}</h3>
        <p>${t(
          'The model gets a few numbered lines of code and one narrow question, never “is this app safe?”. Plumb also searches for anything that would make the place fine, such as a filter in the database query or a check inside a helper in another file. Then the model judges three times, with the evidence in a different order each time. All three must agree, or the answer is Inconclusive.',
          'Modelga bir necha raqamlangan kod qatori va bitta aniq savol beriladi, undan hech qachon «bu ilova xavfsizmi?» deb so‘ralmaydi. Plumb o‘sha joyni oqlaydigan narsani ham qidiradi: masalan, ma’lumotlar bazasi so‘rovidagi filtr yoki boshqa fayldagi yordamchi funksiya ichidagi tekshiruv. Keyin model uch marta baho beradi, har safar dalillar boshqa tartibda beriladi. Uchala baho bir xil chiqishi shart, aks holda javob «Noaniq» bo‘ladi.',
        )}</p>
        <p class="step-fact">${t(
          html`${fact(int(run.requests.answered))} requests to the model · ${fact(receipt.judgments.length)} judgments per answer · ${fact(minutes(run.elapsed_seconds))} on the laptop`,
          html`modelga ${fact(int(run.requests.answered))} ta so‘rov · har bir javob uchun ${fact(receipt.judgments.length)} ta baho · noutbukda ${fact(minutes(run.elapsed_seconds))}`,
        )}</p>
      </li>
      <li>
        <h3>${t('It checks the citations and writes the report.', 'Havolalarni tekshirib, hisobot yozadi.')}</h3>
        <p>${t(
          'Ordinary code, not the model, confirms that every cited line exists and is real code, not a comment. Each answer is one of three: Supported, Rejected or Inconclusive.',
          'Ko‘rsatilgan har bir qator haqiqatan borligini va izoh emas, ishlaydigan kod ekanini model emas, oddiy dastur tekshiradi. Har bir javob uchtadan biri bo‘ladi: Tasdiqlandi, Rad etildi yoki Noaniq.',
        )}</p>
        <p class="step-fact">${run.saved_reports.map((/** @type {any} */ file, /** @type {number} */ index) => html`${index ? ' · ' : ''}${fact(file.name)}`)}</p>
      </li>
      <li class="bob-end">
        ${bobEnd}
        <h3>${t('An answer you can check yourself.', 'O‘zingiz tekshirib ko‘ra oladigan javob.')}</h3>
        <p>${t(
          'Every conclusion lists the lines it rests on, what was searched for and not found, and what is still unknown.',
          'Har bir xulosada u tayangan qatorlar, nima qidirilib topilmagani va nima hali noma’lumligi ko‘rsatiladi.',
        )}</p>
      </li>
    </ol>`,
  });

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

  const proof = html`<section class="band" id="proof" aria-labelledby="proof-h">
  <div class="wrap">
    <div class="lead-in">
      <h2 id="proof-h">${t('A real test: two addresses that look the same.', 'Haqiqiy sinov: bir xil ko‘rinadigan ikki manzil.')}</h2>
      <div class="prose">
        ${t(
          html`<p>Tandir is a small bakery-ordering app written for this project. Flaws were planted in it on purpose, so the right answer is known in advance.</p>
        <p>Its receipt address and its invoice address look almost the same. The receipt hands any signed-in person the order whose number is in the address. The invoice fetches the order through a helper in another file, and that helper only returns orders that belong to the person asking.</p>
        <p>The difference cannot be seen in the two addresses themselves. Plumb followed the call into the other file and came back with two different answers.</p>`,
          html`<p>Tandir — shu loyiha uchun yozilgan kichik nonvoyxona buyurtma ilovasi. Unga xatolar ataylab qoldirilgan, shuning uchun to‘g‘ri javob oldindan ma’lum.</p>
        <p>Ilovadagi chek manzili bilan hisob-faktura manzili deyarli bir xil ko‘rinadi. Chek manzili tizimga kirgan istalgan odamga manzildagi raqamga mos buyurtmani beradi. Hisob-faktura esa buyurtmani boshqa fayldagi yordamchi funksiya orqali oladi, bu funksiya esa faqat so‘rayotgan odamning o‘ziga tegishli buyurtmalarni qaytaradi.</p>
        <p>Ikki manzilning o‘zida bu farq ko‘rinmaydi. Plumb chaqiruv ortidan boshqa faylga o‘tdi va ikki xil javob bilan qaytdi.</p>`,
        )}
      </div>
    </div>
    <div class="pair">
      <div class="pair-col">
      <article class="sheet case">
        <h3>${t('The receipt', 'Chek')} <span class="aside">${receipt.display_id}</span></h3>
        ${verdict(receipt)}
        ${exhibit(excerpts.receipt_handler, {
          gloss: t(
            'Loads the order by its number alone. The marked line is where Plumb found no check of who owns it.',
            'Buyurtmani faqat raqami bo‘yicha yuklaydi. Belgilangan qatorda Plumb buyurtma kimniki ekanini tekshiradigan kod topmadi.',
          ),
          mark: 'access',
        })}
      </article>
      <div class="note-block">
        <p class="note">${t(
          html`<strong>These answers come from reading code.</strong> In this run Plumb sent nothing to the app, and the report says so: runtime check <span class="unproven">not attempted</span>. Separate, earlier tests did send real requests to the same practice app. They are <a href="/recorded-run#runtime">recorded on their own</a>.`,
          html`<strong>Bu javoblar kodni o‘qib chiqarilgan.</strong> Bu tekshiruvda Plumb ilovaga hech narsa yubormagan va hisobotda shunday yozilgan: jonli sinov <span class="unproven">o‘tkazilmagan</span>. Avvalroq alohida sinovlarda shu ilovaga haqiqiy so‘rovlar yuborilgan. Ular <a href="/recorded-run#runtime">alohida qayd etilgan</a>.`,
        )}</p>
        <p class="run-line">${t(
          html`${fact(int(run.requests.answered))} requests to the model · ${fact(minutes(run.elapsed_seconds))} · ${fact(`${coverage.completed} of ${coverage.total}`)} places reviewed, as chosen before the run · app code executed: ${fact('no')}`,
          html`modelga ${fact(int(run.requests.answered))} ta so‘rov · ${fact(minutes(run.elapsed_seconds))} · ${fact(coverage.total)} ta joydan oldindan tanlangan ${fact(coverage.completed)} tasi tekshirildi · ilova kodi ishga tushirilmadi`,
        )}</p>
      </div>
      </div>
      <article class="sheet case">
        <h3>${t('The invoice', 'Hisob-faktura')} <span class="aside">${invoice.display_id}</span></h3>
        ${verdict(invoice)}
        ${exhibit(excerpts.invoice_handler, {
          gloss: t(
            'Does not load the order itself. It hands the job to a helper.',
            'Buyurtmani o‘zi yuklamaydi, bu ishni yordamchi funksiyaga topshiradi.',
          ),
        })}
        ${exhibit(excerpts.invoice_helper, {
          gloss: t(
            'The helper, in another file. The marked lines only match an order whose customer is the person asking.',
            'Boshqa fayldagi yordamchi funksiya. Belgilangan qatorlar faqat mijozi so‘rayotgan odamning o‘zi bo‘lgan buyurtmani topadi.',
          ),
          mark: 'guard',
        })}
      </article>
    </div>
    <p class="more"><a href="/recorded-run">${t('Follow the whole test, step by step', 'Butun sinovni qadam-baqadam ko‘rish')}</a></p>
  </div>
</section>`;

  const availability = site.download
    ? t(
        html`<p><strong>Yes, as a download.</strong> <a href="${site.download}">Download the Windows package</a> (${fact(mb(record.download.archive_bytes))}), or get the source code on <a href="${site.repository}">GitHub</a>. The <a href="/install">install page</a> has every step.</p>`,
        html`<p><strong>Ha, yuklab olish mumkin.</strong> <a href="${site.download}">Windows to‘plamini yuklab oling</a> (${fact(mb(record.download.archive_bytes))}) yoki manba kodini <a href="${site.repository}">GitHub</a>’dan oling. Barcha qadamlar <a href="/install">o‘rnatish sahifasida</a>.</p>`,
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
        'Plumb is a program for your own computer, not a website, because your code should not leave it. A full review with the AI model starts only on hardware that has been measured, and so far that is one laptop model. On other Windows computers Plumb is built to map a project without the model, but a second computer has not been tried yet.',
        'Plumb veb-sayt emas, o‘z kompyuteringizda ishlaydigan dastur, chunki kodingiz kompyuteringizdan tashqariga chiqmasligi kerak. SI modeli bilan to‘liq tekshiruv faqat o‘lchab ko‘rilgan qurilmada ishga tushadi, hozircha bu bitta noutbuk modeli. Boshqa Windows kompyuterlarda Plumb loyiha xaritasini modelsiz tuza oladigan qilib qurilgan, lekin buni ikkinchi kompyuterda hali sinab ko‘rilmagan.',
      )}</p>
      <dl class="spec">
        <div><dt>${t('Measured on', 'Qayerda o‘lchangan')}</dt>
          <dd>${t(
            html`A laptop with an Intel Core i5-1135G7 (${fact(run.machine.physical_cores)} cores), ${fact(memory)} of memory and ${run.machine.gpu} graphics.`,
            html`Intel Core i5-1135G7 protsessorli (${fact(run.machine.physical_cores)} yadro), ${fact(memory)} operativ xotirali va ${run.machine.gpu} videokartali noutbuk.`,
          )}</dd></div>
        <div><dt>${t('The AI model', 'SI modeli')}</dt>
          <dd>${t(
            html`${model.family}, an open model, used as published. One ${fact(gb(model.size))} file, licence ${fact(model.license)}. Plumb does not train it.`,
            html`${model.family} — ochiq model, e’lon qilingan holicha ishlatiladi. Bitta ${fact(gb(model.size))} hajmli fayl, litsenziyasi ${fact(model.license)}. Plumb uni o‘qitmaydi.`,
          )}</dd></div>
        <div><dt>${t('Downloads', 'Yuklab olinadigan fayllar')}</dt>
          <dd>${t(
            html`Once, during setup: the model and the ${fact(mb(record.runtime_download.size))} program that runs it. Setup shows the size, source and licence of each before it starts.`,
            html`Faqat bir marta, o‘rnatish paytida: model va uni ishga tushiradigan ${fact(mb(record.runtime_download.size))} hajmli dastur. O‘rnatuvchi har birining hajmi, manbasi va litsenziyasini oldindan ko‘rsatadi.`,
          )}</dd></div>
        <div><dt>${t('Time', 'Vaqt')}</dt>
          <dd>${t(
            html`The recorded review of two places took ${fact(minutes(run.elapsed_seconds))}. That is one run, not a benchmark.`,
            html`Ikki joyni tekshirgan yozib olingan sinov ${fact(minutes(run.elapsed_seconds))} davom etgan. Bu bitta ishga tushirish natijasi, tezlik o‘lchovi emas.`,
          )}</dd></div>
      </dl>
      <div class="routes">
        <a class="route-card" href="/install"><span class="route-title">${t('Install it yourself', 'O‘zingiz o‘rnating')}</span><span class="small">${t('What it needs, each command, and what you will see.', 'Nima kerakligi, har bir buyruq va natijada nimani ko‘rishingiz.')}</span></a>
        <a class="route-card" href="/install/agent"><span class="route-title">${t('Let an AI agent install it', 'SI agentga o‘rnattiring')}</span><span class="small">${t('One message for Claude Code, Codex or a similar agent.', 'Claude Code, Codex yoki shunga o‘xshash agent uchun bitta xabar.')}</span></a>
      </div>
    </div>`,
  });

  const words = band({
    id: 'words',
    heading: t('Words used on this site.', 'Saytdagi so‘zlar.'),
    body: html`<dl class="terms terms-words glossary">
      <div><dt>${t('Source code', 'Manba kodi')}</dt><dd>${t(
        'The text programmers write to make an app. Plumb reads it the way you read a page. It does not run it.',
        'Dasturchilar ilova yaratish uchun yozadigan matn. Plumb uni siz kitob sahifasini o‘qigandek o‘qiydi, ishga tushirmaydi.',
      )}</dd></div>
      <div><dt>${t('Address (route)', 'Manzil (route)')}</dt><dd>${t(
        html`A place in an app that a browser or phone can ask for, such as ${fact(receipt.route)}.`,
        html`Ilovada brauzer yoki telefon murojaat qila oladigan joy, masalan ${fact(receipt.route)}.`,
      )}</dd></div>
      <div><dt>${t('Check', 'Tekshiruv')}</dt><dd>${t(
        'A few lines of code that refuse a request unless a condition holds, for example “this order belongs to you”.',
        'Shart bajarilmasa, so‘rovni rad etadigan bir necha qator kod. Masalan: «bu buyurtma sizniki».',
      )}</dd></div>
      <div><dt>${t('AI model', 'SI modeli')}</dt><dd>${t(
        'A large file of numbers that has learned to continue text. Plumb uses a small one that fits on a laptop, and checks every line it cites before trusting its answer.',
        'Matnni davom ettirishni o‘rgangan, sonlardan iborat katta fayl. Plumb noutbukka sig‘adigan kichik modeldan foydalanadi va javobiga ishonishdan oldin u ko‘rsatgan har bir qatorni tekshiradi.',
      )}</dd></div>
      <div><dt>${t('Offline, local', 'Internetsiz, lokal')}</dt><dd>${t(
        'On your own computer. Nothing is sent to an online service to be analysed.',
        'O‘z kompyuteringizda. Tahlil uchun hech narsa onlayn xizmatga yuborilmaydi.',
      )}</dd></div>
      <div><dt>${t('Supported, Rejected, Inconclusive', 'Tasdiqlandi, Rad etildi, Noaniq')}</dt><dd>${t(
        'The three possible answers: the flaw is backed by the code; a protection was found, so there is no flaw here; or the evidence does not settle it.',
        'Uchta mumkin bo‘lgan javob: xato kod bilan tasdiqlandi; himoya topildi, demak bu yerda xato yo‘q; yoki dalillar masalani hal qilmaydi.',
      )}</dd></div>
      <div><dt>${t('Reading code, live test', 'Kodni o‘qish, jonli sinov')}</dt><dd>${t(
        'Reading code shows what the code allows. A live test sends a real request to the running app and shows what happens. This site never mixes the two.',
        'Kodni o‘qish kod nimaga yo‘l qo‘yishini ko‘rsatadi. Jonli sinovda ishlab turgan ilovaga haqiqiy so‘rov yuboriladi va nima bo‘lishi ko‘riladi. Bu saytda ikkalasi hech qachon aralashtirilmaydi.',
      )}</dd></div>
      <div><dt>${t('Prototype', 'Prototip')}</dt><dd>${t(
        'It works on the cases shown here. It is not finished and has not been tested widely.',
        'Bu yerda ko‘rsatilgan holatlarda ishlaydi. Hali tugallanmagan va keng sinovdan o‘tmagan.',
      )}</dd></div>
    </dl>`,
  });

  const next = html`<section class="band band-last" aria-label="${t('Where to go next', 'Keyingi qadam')}">
  <div class="wrap next">
    <a class="next-link" href="/recorded-run"><span class="next-title">${t('The test run', 'Sinov natijasi')}</span><span class="small">${t('Every step of the recorded test, with the report files.', 'Yozib olingan sinovning har bir qadami, hisobot fayllari bilan.')}</span></a>
    <a class="next-link" href="/evidence"><span class="next-title">${t('Strengths and limits', 'Imkoniyat va cheklovlar')}</span><span class="small">${t('What passed, what failed, and what comes next.', 'Nima o‘tdi, nima o‘tmadi va keyingi rejalar.')}</span></a>
    <a class="next-link" href="/install/agent"><span class="next-title">${t('Install with an AI agent', 'SI agent orqali o‘rnatish')}</span><span class="small">${t('Paste one message into Claude Code or Codex.', 'Claude Code yoki Codex’ga bitta xabar yuboring.')}</span></a>
    <a class="next-link" href="/contact"><span class="next-title">${t('Send a message', 'Xabar yuborish')}</span><span class="small">${t('Ask a question without leaving this site.', 'Saytdan chiqmasdan savol bering.')}</span></a>
  </div>
</section>`;

  return page({
    path,
    title: t(
      'Plumb: finds where your app shows people data that isn’t theirs',
      'Plumb: ilovangizda birovning ma’lumoti boshqasiga ochilib qoladigan joylarni topadi',
    ),
    description: t(
      'Plumb reads a web app’s code on your own computer with a small offline AI model, finds places where one user can see another user’s data, and cites the exact lines. A working prototype with a recorded test and stated limits.',
      'Plumb veb-ilova kodini o‘z kompyuteringizda, internetsiz ishlaydigan kichik SI modeli bilan o‘qiydi, bir foydalanuvchi boshqasining ma’lumotlarini ko‘ra oladigan joylarni topadi va aniq qatorlarini ko‘rsatadi. Yozib olingan sinovi va ochiq aytilgan cheklovlari bilan ishlaydigan prototip.',
    ),
    body: html`${hero}${glance}${how}${use}${proof}${today}${words}${next}`,
    context,
  });
}
