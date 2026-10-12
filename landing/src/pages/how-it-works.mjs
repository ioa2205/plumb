// @ts-check
import { bobEnd, glyph, pencilMark } from '../components/glyphs.mjs';
import { band, page } from '../components/layout.mjs';
import { codeLines, exhibit, fact, inShort, standing, verdict } from '../components/parts.mjs';
import { storyRows, tape } from '../components/trace.mjs';
import { day, int, minutes } from '../lib/format.mjs';
import { holds } from '../lib/holds.mjs';
import { html } from '../lib/html.mjs';
import { t } from '../lib/lang.mjs';
import { websiteLimits } from '../lib/website-limits.mjs';

export const path = '/how-it-works';

/** @param {import('../components/layout.mjs').PageContext} context */
export function render(context) {
  const { record } = context;
  const { run, excerpts, model, development, runtime, download, cpu_profile: cpu, collection, observation_comparison: comparison } = record;
  const { console_records: consoles, workbench_views: views, report_drafts: drafts, tool_connection: connection } = record;
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
  holds(runtime.replay.after.outcome === 'fixed', 'after the hand-written fix the leak stopped');
  holds(connection.lookups.length === 4, 'the tool connection offers four lookups');
  websiteLimits(download);

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
      html`The ${fact(peer.compared)} places in the practice app that load an order. ${glyph('dot')} checks that it belongs to the person asking. ${glyph('ring')} does not.`,
      html`Sinov ilovasida buyurtma yuklanadigan ${fact(peer.compared)} ta joy. ${glyph('dot')} buyurtma so‘rayotgan odamniki ekanini tekshiradi. ${glyph('ring')} tekshirmaydi.`,
    )}</figcaption>
  </figure>`;

  const head = html`<header class="page-head">
  <div class="wrap">
    <h1>${t('How Plumb works', 'Plumb qanday ishlaydi')}</h1>
    <p class="lede">${t(
      'Plumb looks for one thing: a place where a person can reach data that belongs to someone else. This page shows how it looks, what it asks its AI model, and how it keeps the model from guessing.',
      'Plumb bitta narsani qidiradi: odam begona ma’lumotga yeta oladigan joyni. Bu sahifada u qanday qidirishi, SI modelidan nimani so‘rashi va modelning taxmin qilishiga qanday yo‘l qo‘ymasligi ko‘rsatilgan.',
    )}</p>
    ${inShort([
      t('It maps the app, then compares places that do the same job. The one that skips a check gets questioned.', 'U ilova xaritasini tuzadi, so‘ng bir xil ish bajaradigan joylarni solishtiradi. Tekshiruvi tushib qolgan joy so‘roqqa tutiladi.'),
      t('The AI model gets small questions and judges three times. All three must agree.', 'SI modeliga qisqa savollar beriladi va u uch marta baho beradi. Uchala baho bir xil chiqishi shart.'),
      t('Ordinary code, not the model, checks every cited line before anything is reported.', 'Hisobotga kiritishdan oldin ko‘rsatilgan har bir qatorni model emas, oddiy dastur tekshiradi.'),
    ])}
  </div>
</header>`;



  const ways = html`<section class="band" id="ways" aria-labelledby="ways-h">
  <div class="wrap">
    <div class="lead-in">
      <h2 id="ways-h">${t('Two ways to look at the same app.', 'Bitta ilovaga ikki tomondan qarash.')}</h2>
      <p class="lead-note">${t(
        'Both look for one thing: a place where a person can reach data that belongs to someone else. They are kept apart, because code and replies prove different things.',
        'Ikkalasi ham bir narsani qidiradi: odam begona ma’lumotga yeta oladigan joyni. Ular bir-biridan alohida yuritiladi, chunki kod bilan javoblar turli narsani isbotlaydi.',
      )}</p>
    </div>
    <div class="ways">
      <article class="sheet way">
        <header class="way-head">
          <h3>${t('Read the code', 'Kodni o‘qish')}</h3>
          ${standing('dot', t('Shown working on a practice app', 'Sinov ilovasida ishlashi ko‘rsatilgan'))}
        </header>
        <p>${t(
          'Point Plumb at a project folder. It lists every address the app answers, compares the ones that do the same job, and questions the AI model about the one that skips a check.',
          'Plumbga loyiha papkasini ko‘rsating. U ilova javob beradigan barcha manzillarni ro‘yxatga oladi, bir xil ish bajaradiganlarini solishtiradi va tekshiruvi tushib qolgan manzil haqida SI modeliga savol beradi.',
        )}</p>
        <figure class="way-proof">
          <figcaption class="way-cap"><span class="path">${excerpts.receipt_handler.path}</span></figcaption>
          ${codeLines(excerpts.receipt_handler, access.start, excerpts.receipt_handler.end, 'access')}
        </figure>
        <p class="way-read">${t(
          html`Line ${fact(access.start)} loads an order by its number alone. Nothing checks whose order it is.`,
          html`${fact(access.start)}-qator buyurtmani faqat raqami bo‘yicha yuklaydi. Buyurtma kimniki ekanini hech narsa tekshirmaydi.`,
        )}</p>
        ${dotRow}
        <ul class="way-result">
          <li class="is-gap">${glyph('dot')}<span>${t('Receipt', 'Chek')}: <strong>${t('Supported', 'Tasdiqlandi')}</strong></span></li>
          <li>${glyph('slash')}<span>${t('Invoice', 'Hisob-faktura')}: <strong>${t('Rejected', 'Rad etildi')}</strong></span></li>
        </ul>
        <p class="more"><a href="/recorded-run">${t('Follow the recorded review', 'Yozib olingan tekshiruvni ko‘rish')}</a></p>
      </article>
      <article class="sheet way">
        <header class="way-head">
          <h3>${t('Watch the answers', 'Javoblarni kuzatish')}</h3>
          ${standing('half', t('Built. The AI verdict is still open', 'Qurilgan. SI modeli hali xulosa bermagan'))}
        </header>
        <p>${t(
          'No code needed. You name the app, two test accounts and a limit on requests. Plumb shows its plan, sends only what you approve, and compares what each account got back.',
          'Kod shart emas. Siz ilovani, ikkita sinov hisobini va so‘rovlar chegarasini ko‘rsatasiz. Plumb rejasini ko‘rsatadi, faqat siz tasdiqlagan so‘rovlarni yuboradi va har bir hisob qanday javob olganini solishtiradi.',
        )}</p>
        ${tape(collection, { only: storyRows(collection), title: t(`Three of ${collection.requests} recorded requests · ${day(collection.recorded_at)}`, `Yozib olingan ${collection.requests} ta so‘rovdan uchtasi · ${day(collection.recorded_at)}`) })}
        <ul class="way-result">
          <li>${glyph('half')}<span>${t(
            html`The AI model judged this evidence ${fact(comparison.approaches.length)} ways: <strong>Inconclusive</strong> each time`,
            html`SI modeli bu dalillarni ${fact(comparison.approaches.length)} xil usulda baholadi: har safar <strong>Noaniq</strong>`,
          )}</span></li>
        </ul>
        <p class="more"><a href="/web-assessment">${t('Follow the recorded collection', 'Yozib olingan so‘rovlarni ko‘rish')}</a></p>
      </article>
    </div>
    <p class="small ways-note">${websiteLimits(download)}</p>
  </div>
</section>`;

  const how = band({
    id: 'how',
    heading: t('How reading the code works, in four steps.', 'Kodni o‘qib tekshirish qanday ishlaydi: to‘rt qadam.'),
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
      <div><dt>${t('Request and reply', 'So‘rov va javob')}</dt><dd>${t(
        'A request is what a browser sends to an address. The reply is what the app sends back, with a number saying how it went: 200 for “here it is”, 404 for “not found”.',
        'So‘rov — brauzer manzilga yuboradigan murojaat. Javob — ilova qaytaradigan narsa. Javobdagi raqam ish qanday bitganini bildiradi: 200 «mana, oling», 404 esa «topilmadi» degani.',
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
        'The three possible answers: the flaw is backed by the evidence; a protection was found, so there is no flaw here; or the evidence does not settle it.',
        'Uchta mumkin bo‘lgan javob: xato dalillar bilan tasdiqlandi; himoya topildi, demak bu yerda xato yo‘q; yoki dalillar masalani hal qilmaydi.',
      )}</dd></div>
      <div><dt>${t('Reading code, watching answers, live test', 'Kodni o‘qish, javoblarni kuzatish, jonli sinov')}</dt><dd>${t(
        'Reading code shows what the code allows. Watching answers shows what a running app sent back on one occasion. A live test is a fixed script that sends real requests to prove a flaw. This site never mixes the three.',
        'Kodni o‘qish kod nimaga yo‘l qo‘yishini ko‘rsatadi. Javoblarni kuzatish ishlab turgan ilova bir safar nima qaytarganini ko‘rsatadi. Jonli sinov esa xatoni isbotlash uchun haqiqiy so‘rovlar yuboradigan qat’iy belgilangan skript. Bu saytda uchalasi hech qachon aralashtirilmaydi.',
      )}</dd></div>
      <div><dt>${t('Scope', 'Qamrov')}</dt><dd>${t(
        'What you allow before anything is sent: which app, which test accounts, how many requests and until when.',
        'Biror narsa yuborilishidan oldin siz bergan ruxsat doirasi: qaysi ilova, qaysi sinov hisoblari, nechta so‘rov va qachongacha.',
      )}</dd></div>
      <div><dt>${t('Prototype', 'Prototip')}</dt><dd>${t(
        'It works on the cases shown here. It is not finished and has not been tested widely.',
        'Bu yerda ko‘rsatilgan holatlarda ishlaydi. Hali tugallanmagan va keng sinovdan o‘tmagan.',
      )}</dd></div>
    </dl>`,
  });


  const next = html`<section class="band band-last" aria-label="${t('Where to go next', 'Keyingi qadam')}">
  <div class="wrap next">
    <a class="next-link" href="/what-it-does"><span class="next-title">${t('What it can do', 'Nimalar qila oladi')}</span><span class="small">${t('Every part of the tool, with its command and how far it has been checked.', 'Vositaning har bir qismi, buyrug‘i va qanchalik tekshirilgani bilan.')}</span></a>
    <a class="next-link" href="/recorded-run"><span class="next-title">${t('See it work', 'Amalda ko‘rish')}</span><span class="small">${t('Every step of the recorded test, with the report files.', 'Yozib olingan sinovning har bir qadami, hisobot fayllari bilan.')}</span></a>
    <a class="next-link" href="/evidence"><span class="next-title">${t('Limits', 'Cheklovlar')}</span><span class="small">${t('What passed, what failed, and what comes next.', 'Nima o‘tdi, nima o‘tmadi va keyingi rejalar.')}</span></a>
    <a class="next-link" href="/install"><span class="next-title">${t('Get Plumb', 'O‘rnatish')}</span><span class="small">${t('Download it, or let an AI agent install it for you.', 'Yuklab oling yoki SI agentga o‘rnattiring.')}</span></a>
  </div>
</section>`;

  return page({
    path,
    title: t('How Plumb works', 'Plumb qanday ishlaydi'),
    description: t(
      'How Plumb finds places where one user can see another user’s data: it maps the app, compares places that do the same job, asks a small local AI model narrow questions, and checks every cited line.',
      'Plumb bir foydalanuvchi boshqasining ma’lumotlarini ko‘ra oladigan joylarni qanday topadi: ilova xaritasini tuzadi, bir xil ish bajaradigan joylarni solishtiradi, kompyuterdagi kichik SI modeliga aniq savollar beradi va ko‘rsatilgan har bir qatorni tekshiradi.',
    ),
    body: html`${head}${ways}${how}${proof}${words}${next}`,
    context,
  });
}
