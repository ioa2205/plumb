// @ts-check
import { band, page } from '../components/layout.mjs';
import { command, fact, factWhole, reportShot } from '../components/parts.mjs';
import { reviewConsole } from '../components/terminal.mjs';
import { day, gb, int, longDay, mb, shortHash } from '../lib/format.mjs';
import { guide, refusals } from '../lib/guide.mjs';
import { holds } from '../lib/holds.mjs';
import { html } from '../lib/html.mjs';
import { t } from '../lib/lang.mjs';

export const path = '/install';

/** @param {import('../components/layout.mjs').PageContext} context */
export function render(context) {
  const { record, site } = context;
  const { run, model, download, cpu_profile: cpu } = record;
  const { admission } = run;
  const { steps, packageSteps, downloads } = guide(record, site);
  const [cpuReceipt, cpuInvoice] = cpu.review.findings;
  const since = download.since_recorded_test;

  holds(!site.download || site.download.endsWith(`/${download.name}`), 'the download link is the package the saved checks describe');
  holds(download.clean_user_profile === false && download.developer_tools_on_path === false, 'the download was tried under the account that built it, with developer tools off the path');
  holds(download.model_loaded === false, 'the checks of the download loaded no AI model');
  holds(download.downloaded_or_installed === false && download.model_already_installed, 'the checks of the download fetched nothing: the model was already on the laptop');
  holds(download.investigator_same_as_source && download.source_files_checked > 0, 'the download is the same code as the source');
  holds(
    download.has_cpu_profile && download.has_calibrate_command && download.first_use_check_importable && download.doctor_advises_on_models && download.setup_takes_model && download.knows_pattern_scanner,
    'the download has the second profile, calibrate, --model, the model advice in doctor and the pattern scanner',
  );
  holds(download.same_investigator_as_cpu_profile_run && cpu.from_source, 'the download’s investigator is the one that completed the processor-only review, which was run from source');
  holds(
    since.same + since.changed.length + since.added.length === download.investigator_files && since.changed.length > 1 && since.added.length === 1,
    'since the package of the recorded test, some investigator files have changed and one is new',
  );
  holds(run.machine.cpu.includes('i5-1135G7') && run.machine.gpu.includes('MX350'), 'measured on an i5-1135G7 with MX350 graphics');
  holds(cpu.same_computer_as_recorded_run, 'the second profile has only run on the laptop Plumb is developed on');
  holds(cpu.first_use_check.outcome === 'passed' && cpu.review.lifecycle === 'completed' && cpu.review.exit === 0, 'the second profile passed its check and completed one review');
  holds(
    cpuReceipt.route === run.findings[0].route && cpuInvoice.route === run.findings[1].route &&
      cpuReceipt.conclusion === run.findings[0].conclusion && cpuInvoice.conclusion === run.findings[1].conclusion,
    'the same two addresses got the same answers as in the recorded test',
  );
  holds(record.other_models_label === 'quality not yet compared with the default', 'the label Plumb prints beside models other than the default');

  const head = html`<header class="page-head">
  <div class="wrap">
    <h1>${t('Get Plumb', 'Plumbni o‘rnatish')}</h1>
    <p class="lede">${site.download
      ? t(
          'Plumb is a program you run on your own Windows computer. Download the ready-made package or install it from source. Both hold the same code and follow the same steps. This page lists what you need, every command in order, and what you will see.',
          'Plumb o‘z Windows kompyuteringizda ishlaydigan dastur. Tayyor to‘plamni yuklab oling yoki manba kodidan o‘rnating. Ikkalasida ham kod bir xil, qadamlari ham bir xil. Bu sahifada nima kerakligi, barcha buyruqlar tartib bilan va natijada nimani ko‘rishingiz aytilgan.',
        )
      : t(
          'Plumb is a program you run on your own Windows computer. This page says why there is no download button yet, what you need, every command in order, and what you will see.',
          'Plumb o‘z Windows kompyuteringizda ishlaydigan dastur. Bu sahifada hozircha nega yuklab olish tugmasi yo‘qligi, nima kerakligi, barcha buyruqlar tartib bilan va natijada nimani ko‘rishingiz aytilgan.',
        )}</p>
  </div>
</header>`;

  const availability = site.repository && site.download
    ? t(
        html`<p class="condition"><strong>The source code and a Windows package are public.</strong> Get the code from <a href="${site.repository}">the repository</a>, or <a href="${site.download}">download the package</a> (${fact(mb(download.archive_bytes))}, SHA-256 ${fact(`${shortHash(download.archive_sha256)}…`)}).</p>`,
        html`<p class="condition"><strong>Manba kodi va Windows to‘plami ochiq.</strong> Kodni <a href="${site.repository}">repozitoriydan</a> oling yoki <a href="${site.download}">to‘plamni yuklab oling</a> (${fact(mb(download.archive_bytes))}, SHA-256 ${fact(`${shortHash(download.archive_sha256)}…`)}).</p>`,
      )
    : site.repository
      ? t(
          html`<p class="condition"><strong>The source code is public.</strong> Anyone can get it from <a href="${site.repository}">the repository</a> and run Plumb as described below. The ready-made Windows package is not published yet; ask for it through the <a href="/contact">contact page</a>.</p>`,
          html`<p class="condition"><strong>Manba kodi ochiq.</strong> Uni istalgan odam <a href="${site.repository}">repozitoriydan</a> olib, Plumbni quyidagidek ishga tushira oladi. Tayyor Windows to‘plami hali e’lon qilinmagan, uni <a href="/contact">aloqa sahifasi</a> orqali so‘rashingiz mumkin.</p>`,
        )
      : t(
          html`<p class="condition"><strong>Not available for download yet.</strong> The source code and the Windows package are sent on request. Ask through the <a href="/contact">contact page</a>.</p>`,
          html`<p class="condition"><strong>Hozircha yuklab olib bo‘lmaydi.</strong> Manba kodi va Windows to‘plami so‘rov bo‘yicha yuboriladi. <a href="/contact">Aloqa sahifasi</a> orqali so‘rang.</p>`,
        );

  const downloadBand = band({
    id: 'today',
    heading: t('Download Plumb.', 'Plumbni yuklab oling.'),
    body: html`<div class="stack-gap">
      <div class="download-card">
        <div class="download-main">
          <p class="download-title">${t('Plumb for Windows', 'Windows uchun Plumb')}</p>
          <p class="small">${t(
            html`Portable ZIP · ${fact(mb(download.archive_bytes))} · ${fact(int(download.inventoried_files))} files · prototype, checked on ${day(download.checked_at)}`,
            html`Ko‘chma ZIP · ${fact(mb(download.archive_bytes))} · ${fact(int(download.inventoried_files))} ta fayl · prototip, ${day(download.checked_at)} kuni tekshirilgan`,
          )}</p>
        </div>
        <a class="btn btn-ink download-button" href="${site.download}">${t('Download ZIP', 'ZIP faylni yuklab olish')}</a>
        <p class="download-hash"><span class="small">SHA-256</span> <span class="fact">${download.archive_sha256}</span></p>
      </div>
      <p class="small">${t(
        html`The source code is on <a href="${site.repository}">GitHub</a>, under the MIT licence.`,
        html`Manba kodi <a href="${site.repository}">GitHub</a>’da, MIT litsenziyasi ostida.`,
      )}</p>
      <ul class="limits">
        ${t(
          html`<li><strong>This package has not yet run a review with the AI model.</strong> Its checks loaded no model. The recorded test of ${longDay(run.started_at)} used an earlier package, and the one review with ${factWhole(cpu.id)} was run from source.</li>
        <li><strong>It holds the same code as the source.</strong> It was built on ${longDay(download.built_on)}. ${fact(int(download.source_files_checked))} of its files were compared with the source code, and all of them matched. So it has the second profile, ${factWhole(cpu.id)}, the <span class="fact whole">calibrate</span> command, the <span class="fact whole">--model</span> option, the part of <span class="fact whole">doctor</span> that says which AI models fit in your free memory, and a setup that also installs the pattern scanner. It also has the fix that keeps Plumb from starting a program hidden in the folder being reviewed under the name of a Windows tool.</li>
        <li><strong>Its investigator is the one that completed the ${factWhole(cpu.id)} review.</strong> The investigator is the part of Plumb that carries out a review. Its ${fact(download.investigator_files)} files are byte for byte the ones that completed that review on ${longDay(cpu.recorded_on)}. Compared with the package used in the recorded test, ${fact(since.same)} of them are the same, ${fact(since.changed.length)} have changed and ${fact(since.added.length)} is new.</li>
        <li><strong>It has only been tried on the laptop it was built on.</strong> There, under the Windows account that built it and with developer tools removed from the path, it mapped the practice app, opened the recorded report and served its browser view. The AI model and the program that runs it were already on that laptop, so these checks downloaded and installed nothing. A fresh Windows account and other computers have not been tested.</li>
        <li><strong>The AI model is not inside.</strong> Setup downloads it (${fact(gb(model.size))}) from Hugging Face after showing you its size, source and licence.</li>
        <li><strong>Plumb is not a web service.</strong> It runs on your computer on purpose, so that your code stays with you.</li>`,
          html`<li><strong>Bu to‘plam SI modeli bilan hali birorta ham tekshiruv o‘tkazmagan.</strong> Uni sinashda model ishga tushirilmagan. ${longDay(run.started_at)} kungi yozib olingan sinov avvalgi to‘plamda o‘tkazilgan, ${factWhole(cpu.id)} profilidagi yagona tekshiruv esa manba kodidan ishga tushirilgan.</li>
        <li><strong>Undagi kod manba kodi bilan bir xil.</strong> U ${longDay(download.built_on)} kuni yig‘ilgan. Ichidagi ${fact(int(download.source_files_checked))} ta fayl manba kodi bilan solishtirilgan, hammasi mos kelgan. Demak, unda ikkinchi profil (${factWhole(cpu.id)}), <span class="fact whole">calibrate</span> buyrug‘i, <span class="fact whole">--model</span> parametri, <span class="fact whole">doctor</span> buyrug‘ining qaysi SI modellari bo‘sh xotirangizga sig‘ishini aytadigan qismi va andoza skanerini ham o‘rnatadigan o‘rnatuvchi bor. Tekshirilayotgan papkaga Windows vositasi nomi bilan yashirib qo‘yilgan dastur ishga tushib ketishiga yo‘l qo‘ymaydigan tuzatish ham unda bor.</li>
        <li><strong>Uning tekshiruvchisi ${factWhole(cpu.id)} profilidagi tekshiruvni bajargan kodning o‘zi.</strong> Tekshiruvchi — Plumbning tekshiruvni bajaradigan qismi. Uning ${fact(download.investigator_files)} ta fayli ${longDay(cpu.recorded_on)} kuni o‘sha tekshiruvni bajargan fayllar bilan baytma-bayt bir xil. Yozib olingan sinovda ishlatilgan to‘plam bilan solishtirganda ularning ${fact(since.same)} tasi o‘zgarmagan, ${fact(since.changed.length)} tasi o‘zgargan, ${fact(since.added.length)} tasi yangi.</li>
        <li><strong>U faqat yig‘ilgan noutbukda sinab ko‘rilgan.</strong> U yerda, o‘zi yig‘ilgan Windows hisobida va dasturchi vositalari olib tashlangan holda, sinov ilovasining xaritasini tuzdi, yozib olingan hisobotni ochdi va brauzerdagi interfeysini ishga tushirdi. SI modeli va uni ishga tushiradigan dastur o‘sha noutbukda oldindan bor edi, shuning uchun bu sinovlarda hech narsa yuklab olinmagan va o‘rnatilmagan. Yangi Windows hisobi va boshqa kompyuterlarda sinab ko‘rilmagan.</li>
        <li><strong>SI modeli to‘plam ichida emas.</strong> O‘rnatuvchi uni (${fact(gb(model.size))}) hajmi, manbasi va litsenziyasini ko‘rsatgandan keyin Hugging Face’dan yuklab oladi.</li>
        <li><strong>Plumb veb-xizmat emas.</strong> U ataylab sizning kompyuteringizda ishlaydi, shunda kodingiz o‘zingizda qoladi.</li>`,
        )}
      </ul>
      <div class="routes">
        <a class="route-card" href="#package"><span class="route-title">${t('After downloading', 'Yuklab olgandan keyin')}</span><span class="small">${t('Extract, set up, map the practice app, then review.', 'Arxivdan chiqaring, o‘rnating, sinov ilovasining xaritasini tuzing, so‘ng tekshiring.')}</span></a>
        <a class="route-card" href="/install/agent"><span class="route-title">${t('Let an AI agent install it', 'SI agentga o‘rnattiring')}</span><span class="small">${t('Paste one message into Claude Code, Codex or a similar agent.', 'Claude Code, Codex yoki shunga o‘xshash agentga bitta xabar yuboring.')}</span></a>
      </div>
    </div>`,
  });

  const today = band({
    id: 'today',
    heading: t('Why there is no download button yet.', 'Nega hozircha yuklab olish tugmasi yo‘q.'),
    body: html`<div class="stack-gap">
      ${availability}
      <ul class="limits">
        ${site.repository
          ? ''
          : t(
              html`<li><strong>The code is not public yet.</strong> It is being prepared for release, without the private notes it was built with.</li>`,
              html`<li><strong>Kod hali ommaga ochilmagan.</strong> U ishlab chiqish jarayonidagi shaxsiy qaydlardan tozalanib, e’lon qilishga tayyorlanmoqda.</li>`,
            )}
        ${t(
          html`<li><strong>The ready-made package has only been tried where it was built.</strong> It is a ${fact(mb(download.archive_bytes))} ZIP that worked on this one laptop, under the Windows account it was built with. A fresh Windows account has not been tested, and a download button would promise more than that.</li>
        <li><strong>The AI model is not inside it.</strong> It is a separate ${fact(gb(model.size))} file that setup downloads from Hugging Face, after showing you its size, source and licence.</li>
        <li><strong>Plumb is not a web service.</strong> Putting this website on a server does not make Plumb run there. It runs on your computer on purpose, so that your code stays with you.</li>`,
          html`<li><strong>Tayyor to‘plam faqat yig‘ilgan joyida sinalgan.</strong> Bu ${fact(mb(download.archive_bytes))} hajmli ZIP fayl bitta noutbukda, u yig‘ilgan Windows hisobida ishlagan. Yangi Windows hisobida sinab ko‘rilmagan, yuklab olish tugmasi esa bundan ko‘prog‘ini va’da qilgan bo‘lardi.</li>
        <li><strong>SI modeli to‘plam ichida emas.</strong> U alohida, ${fact(gb(model.size))} hajmli fayl. O‘rnatuvchi uni hajmi, manbasi va litsenziyasini ko‘rsatgandan keyin Hugging Face’dan yuklab oladi.</li>
        <li><strong>Plumb veb-xizmat emas.</strong> Bu saytni serverga joylash Plumbni o‘sha yerda ishlatib qo‘ymaydi. U ataylab sizning kompyuteringizda ishlaydi, shunda kodingiz o‘zingizda qoladi.</li>`,
        )}
      </ul>
      <div class="routes">
        <a class="route-card" href="#source"><span class="route-title">${t('Install it yourself', 'O‘zingiz o‘rnating')}</span><span class="small">${t(`${steps.length} short steps in PowerShell, below.`, `PowerShell’da ${steps.length} ta qisqa qadam, quyida.`)}</span></a>
        <a class="route-card" href="/install/agent"><span class="route-title">${t('Let an AI agent install it', 'SI agentga o‘rnattiring')}</span><span class="small">${t('Paste one message into Claude Code, Codex or a similar agent.', 'Claude Code, Codex yoki shunga o‘xshash agentga bitta xabar yuboring.')}</span></a>
      </div>
    </div>`,
  });

  const needs = band({
    id: 'needs',
    heading: t('What you need.', 'Nima kerak.'),
    body: html`<dl class="spec">
      <div><dt>${t('System', 'Tizim')}</dt>
        <dd>${t(
          'Windows 10 or 11, 64-bit, with PowerShell. No administrator rights, Docker or Windows Sandbox. Plumb does not run on macOS or Linux yet. From source, each command there is written to say so in one sentence and stop; no Mac or Linux computer was at hand to try that on.',
          '64 bitli Windows 10 yoki 11 va PowerShell. Administrator huquqlari, Docker yoki Windows Sandbox kerak emas. Plumb macOS va Linuxda hozircha ishlamaydi. Manba kodidan o‘rnatilgan bo‘lsa, u yerda har bir buyruq shuni bir jumla bilan aytib, to‘xtaydigan qilib yozilgan, lekin buni sinab ko‘rish uchun Mac yoki Linux kompyuter bo‘lmagan.',
        )}</dd></div>
      <div><dt>${site.download ? t('Tools, for the source install', 'Dasturlar, manba kodidan o‘rnatish uchun') : t('Tools', 'Dasturlar')}</dt>
        <dd>${t(
          'Git, uv, Node.js 24 or newer, and pnpm. uv brings Python 3.12 with it.',
          'Git, uv, Node.js 24 yoki undan yangi versiyasi va pnpm. Python 3.12 ni uv o‘zi olib keladi.',
        )}</dd></div>
      <div><dt>${t('For reviews with the AI model', 'SI modeli bilan tekshiruv uchun')}</dt>
        <dd class="stack-gap">
          <p>${t(
            'A profile is one tested combination of AI model, the program that runs it, and settings. Plumb has two and picks the one that fits your computer.',
            'Profil — birga sinab ko‘rilgan SI modeli, uni ishga tushiradigan dastur va sozlamalar to‘plami. Plumbda ikkita profil bor, kompyuteringizga mosini uning o‘zi tanlaydi.',
          )}</p>
          <ul class="quiet-list">
            <li>${factWhole(run.profile)}<span>${t(
              html`For one laptop model only: an Intel Core i5-1135G7 with ${run.machine.gpu} graphics. At launch it needs ${fact(gb(admission.host_bytes))} of free RAM and ${fact(gb(admission.device_bytes))} of free graphics memory. The recorded test used it.`,
              html`Faqat bitta noutbuk modeli uchun: Intel Core i5-1135G7 protsessori va ${run.machine.gpu} videokartasi. Ishga tushirish paytida ${fact(gb(admission.host_bytes))} bo‘sh operativ xotira va ${fact(gb(admission.device_bytes))} bo‘sh videoxotira kerak. Yozib olingan sinov shu profilda o‘tgan.`,
            )}</span></li>
            <li>${factWhole(cpu.id)}<span>${t(
              html`For any other 64-bit Windows computer with an Intel or AMD processor. It runs the same AI model on the processor alone, so no particular graphics card is needed. At launch it needs ${fact(gb(cpu.required_ram_bytes))} of free RAM. It has completed one real run, from source, on ${longDay(cpu.recorded_on)}, on the laptop Plumb is developed on: it passed a short check of the program that runs the model, then gave the same two answers as the recorded test in ${fact(cpu.review.model_requests)} requests to the model. It has not been tried on any other computer, and how fast it is there is not known.`,
              html`Intel yoki AMD protsessorli, 64 bitli Windows o‘rnatilgan boshqa har qanday kompyuter uchun. O‘sha SI modelini faqat protsessorda ishlatadi, shuning uchun ma’lum bir videokarta talab qilinmaydi. Ishga tushirish paytida ${fact(gb(cpu.required_ram_bytes))} bo‘sh operativ xotira kerak. Bir marta, manba kodidan ishga tushirilgan holda, haqiqiy sinovdan o‘tgan: ${longDay(cpu.recorded_on)} kuni Plumb ishlab chiqilayotgan noutbukda avval modelni ishga tushiradigan dasturning qisqa sinovidan o‘tdi, so‘ng modelga ${fact(cpu.review.model_requests)} ta so‘rov yuborib, yozib olingan sinovdagi ikki javobning o‘zini berdi. Boshqa hech bir kompyuterda sinab ko‘rilmagan, u yerda qanchalik tez ishlashi ham noma’lum.`,
            )}</span></li>
          </ul>
          <p>${t(
            'Plumb checks the memory before every start and refuses when there is less. Closing other programs helps. The requirement itself is never lowered.',
            'Plumb xotirani har safar boshlashdan oldin tekshiradi va kam bo‘lsa, ishni boshlamaydi. Boshqa dasturlarni yopish yordam beradi. Talabning o‘zi esa hech qachon kamaytirilmaydi.',
          )}</p>
        </dd></div>
      <div><dt>${t('The AI model', 'SI modeli')}</dt>
        <dd>${t(
          html`${model.family} by default. The recorded test and the one run of ${factWhole(cpu.id)} both used it. <span class="fact whole">doctor</span> also names the largest model on Plumb’s list that fits in the memory free right now, and <span class="fact whole">setup --install --model</span> installs one by name. That is a statement about memory only. The models have not been compared on the same cases, so Plumb prints <span lang="en">${fact(record.other_models_label)}</span> beside every other model, and the memory figure it gives for a larger one is an estimate. No larger model has been downloaded or run in this project.`,
          html`Asosiy model — ${model.family}. Yozib olingan sinov ham, ${factWhole(cpu.id)} profilining yagona sinovi ham shu modelda o‘tgan. <span class="fact whole">doctor</span> buyrug‘i Plumb ro‘yxatidagi modellardan hozir bo‘sh turgan xotiraga sig‘adigan eng kattasini ham ko‘rsatadi, <span class="fact whole">setup --install --model</span> esa modelni nomi bo‘yicha o‘rnatadi. Bu faqat xotira haqidagi gap. Modellar bir xil holatlarda solishtirilmagan, shuning uchun Plumb boshqa har bir model yoniga <span lang="en">${fact(record.other_models_label)}</span> («sifati asosiy model bilan hali taqqoslanmagan») deb yozadi, kattaroq model uchun ko‘rsatadigan xotira miqdori esa taxminiy. Bu loyihada kattaroq modellarning birortasi ham yuklab olinmagan va ishga tushirilmagan.`,
        )}</dd></div>
      <div><dt>${t('Disk and internet', 'Disk va internet')}</dt>
        <dd>${t(
          html`Internet once, during setup. The downloads come to ${fact(gb(downloads.cpu))}, or ${fact(gb(downloads.measured))} on the measured laptop model: the AI model ${fact(model.file)} from ${fact(model.repo)}, licence ${fact(model.license)}, the program that runs it, and a pattern scanner. They are the same with the download and from source. Plumb checks each file against a pinned fingerprint before using it.`,
          html`Internet faqat bir marta, o‘rnatish paytida kerak. Jami ${fact(gb(downloads.cpu))} yuklanadi, o‘lchangan noutbuk modelida esa ${fact(gb(downloads.measured))}: ${fact(model.repo)} dagi ${fact(model.file)} SI modeli (litsenziyasi ${fact(model.license)}), uni ishga tushiradigan dastur va andoza skaneri. Tayyor to‘plamda ham, manba kodidan o‘rnatilganda ham aynan shu fayllar yuklanadi. Plumb har bir faylni ishlatishdan oldin oldindan belgilangan barmoq izi bilan solishtiradi.`,
        )}</dd></div>
      <div><dt>${t('On other computers', 'Boshqa kompyuterlarda')}</dt>
        <dd>${t(
          html`Everything on this page, through the ${factWhole(cpu.id)} profile, when enough memory is free. That goes for the download and for the source alike. This is how Plumb is built to work there. Neither way has been tried on a second computer yet.`,
          html`Xotira yetarli bo‘lsa, ${factWhole(cpu.id)} profili orqali shu sahifadagi hamma narsa. Bu tayyor to‘plamga ham, manba kodiga ham birdek tegishli. Plumb u yerda shunday ishlaydigan qilib qurilgan, lekin bu ikki yo‘lning hech biri ikkinchi kompyuterda hali sinab ko‘rilmagan.`,
        )}</dd></div>
    </dl>`,
  });

  const recordedReview = html`<details class="more-detail">
    <summary>${t('What the review printed in the recorded test', 'Yozib olingan sinovda tekshiruv nima chiqargani')}</summary>
    ${reviewConsole(run)}
  </details>`;

  /**
   * One step of a guide: what it does, then what to type. The source steps and the package
   * steps are drawn the same way.
   * @param {import('../lib/guide.mjs').Step} step @param {unknown} [extra] shown under the commands
   */
  const stepBody = (step, extra = '') => html`<div>
        <p><strong>${step.title}</strong>${step.optional ? html` <span class="tag">${t('optional', 'ixtiyoriy')}</span>` : ''}</p>
        <p class="step-detail">${step.detail}</p>
        ${step.commands ? command(step.commands.join('\n')) : ''}
        ${step.otherwise ? html`<p class="step-detail">${step.otherwise}</p>${command((step.otherCommands ?? []).join('\n'))}` : ''}
        ${extra}
      </div>`;

  const source = band({
    id: 'source',
    heading: t('Install from source, step by step.', 'Manba kodidan o‘rnatish, qadam-baqadam.'),
    intro: html`<p>${t(
      'Open PowerShell and type each command in turn. Only two steps load the AI model: the optional check and the review.',
      'PowerShell’ni oching va buyruqlarni navbat bilan yozing. SI modeli faqat ikki qadamda yuklanadi: ixtiyoriy sinovda va tekshiruvda.',
    )}</p>`,
    body: html`<ol class="steps">
      ${steps.map(
        (step) => html`<li id="step-${step.id}">${stepBody(
          step,
          step.id === 'review'
            ? recordedReview
            : step.id === 'report'
              ? html`<figure class="report-figure is-inline">
          ${reportShot('finding', t('One finding in the saved report: Supported from the source, runtime check not tested, and what Plumb looked for', 'Saqlangan hisobotdagi bitta topilma: kod bo‘yicha tasdiqlangan, jonli sinov o‘tkazilmagan va Plumb nimalarni qidirgani'), [1152, 1040])}
          <figcaption class="small">${t(
            html`One finding in the report from the recorded test. A picture of the <a href="/saved-report/report.html">published report file</a>.`,
            html`Yozib olingan sinov hisobotidagi bitta topilma. <a href="/saved-report/report.html">E’lon qilingan hisobot faylining</a> rasmi.`,
          )}</figcaption>
        </figure>`
              : '',
        )}</li>`,
      )}
    </ol>`,
  });

  const packageBand = band({
    id: 'package',
    heading: site.download
      ? t('Use the Windows package.', 'Windows to‘plamidan foydalaning.')
      : t('Or start from the Windows package.', 'Yoki Windows to‘plamidan boshlang.'),
    intro: html`<p>${t(
      site.download
        ? html`After downloading the ZIP. Python, Node and the browser view are inside, so nothing else has to be installed first. The package has its own commands, which start with <span class="fact whole">.\\plumb.cmd</span>. Only two steps load the AI model: the optional check and the review.`
        : html`If you were sent the ZIP (${fact(mb(download.archive_bytes))}, ${fact(int(download.inventoried_files))} files). Python, Node and the browser view are inside, so nothing else has to be installed first. The package has its own commands, which start with <span class="fact whole">.\\plumb.cmd</span>. Only two steps load the AI model: the optional check and the review.`,
      site.download
        ? html`ZIP faylni yuklab olgandan keyin. Ichida Python, Node va brauzerdagi interfeys bor, shuning uchun oldindan boshqa hech narsa o‘rnatish shart emas. To‘plamning o‘z buyruqlari bor, ular <span class="fact whole">.\\plumb.cmd</span> bilan boshlanadi. SI modeli faqat ikki qadamda yuklanadi: ixtiyoriy sinovda va tekshiruvda.`
        : html`Agar sizga ZIP fayl (${fact(mb(download.archive_bytes))}, ${fact(int(download.inventoried_files))} ta fayl) yuborilgan bo‘lsa. Ichida Python, Node va brauzerdagi interfeys bor, shuning uchun oldindan boshqa hech narsa o‘rnatish shart emas. To‘plamning o‘z buyruqlari bor, ular <span class="fact whole">.\\plumb.cmd</span> bilan boshlanadi. SI modeli faqat ikki qadamda yuklanadi: ixtiyoriy sinovda va tekshiruvda.`,
    )}</p>`,
    body: html`<ol class="steps">
      <li><div>
        <p>${t(
          html`<strong>Extract the ZIP</strong> anywhere. Folder names with spaces are fine.`,
          html`<strong>ZIP faylni</strong> istalgan joyga chiqaring. Papka nomida bo‘sh joy bo‘lsa ham bo‘laveradi.`,
        )}</p>
      </div></li>
      <li><div>
        <p>${t(
          html`<strong>Double-click Start Plumb.cmd</strong> to open the browser view, or open PowerShell in the extracted folder and type the commands below there.`,
          html`Brauzerdagi interfeysni ochish uchun <strong>Start Plumb.cmd faylini ikki marta bosing</strong>. Yoki chiqarilgan papkada PowerShell’ni ochib, quyidagi buyruqlarni o‘sha yerda yozing.`,
        )}</p>
      </div></li>
      ${packageSteps.map((step) => html`<li>${stepBody(step)}</li>`)}
    </ol>
    <p class="small step-note">${t(
      html`Plumb keeps the model and its results in a data folder outside the project, by default <span class="fact">%LOCALAPPDATA%\\Plumb\\data</span>. Set <span class="fact">PLUMB_DATA_DIR</span> to use another disk. That folder must stay outside Plumb’s own folder and outside any project being reviewed.`,
      html`Plumb model va natijalarni loyihadan tashqaridagi ma’lumotlar papkasida saqlaydi, odatda bu <span class="fact">%LOCALAPPDATA%\\Plumb\\data</span>. Boshqa diskdan foydalanish uchun <span class="fact">PLUMB_DATA_DIR</span> o‘zgaruvchisini belgilang. Bu papka Plumbning o‘z papkasidan ham, tekshirilayotgan har qanday loyihadan ham tashqarida bo‘lishi kerak.`,
    )}</p>`,
  });

  const own = band({
    id: 'own',
    heading: t('Review your own project.', 'O‘z loyihangizni tekshiring.'),
    intro: html`<p>${t('Only review code you own or are allowed to test.', 'Faqat o‘zingizga tegishli yoki sinashga ruxsatingiz bor kodni tekshiring.')}</p>`,
    body: html`<div class="stack-gap">
      <p>${t(
        'Give Plumb the full path of the project folder, in quotes. It reads the files as text and never imports, installs or runs them.',
        'Plumbga loyiha papkasining to‘liq yo‘lini qo‘shtirnoq ichida bering. U fayllarni matn sifatida o‘qiydi, ularni hech qachon import qilmaydi, o‘rnatmaydi va ishga tushirmaydi.',
      )}</p>
      ${command(
        [
          "uv run plumb inspect '<full-path-to-your-project>'",
          "uv run plumb review '<full-path-to-your-project>' --limit 5",
          'uv run plumb resume <run-id> --limit 5',
        ].join('\n'),
      )}
      <p class="small">${t(
        'The first command maps the project without a model. The second asks up to five questions and prints a run ID. The third continues the same review later.',
        'Birinchi buyruq loyiha xaritasini modelsiz tuzadi. Ikkinchisi ko‘pi bilan beshta savol beradi va tekshiruv identifikatorini chiqaradi. Uchinchisi o‘sha tekshiruvni keyinroq davom ettiradi.',
      )}${site.download
        ? t(
            html` With the download, type <span class="fact whole">.\\plumb.cmd</span> in place of <span class="fact whole">uv run plumb</span>, in the extracted folder.`,
            html` Tayyor to‘plamda <span class="fact whole">uv run plumb</span> o‘rniga <span class="fact whole">.\\plumb.cmd</span> deb yozing va buyruqlarni chiqarilgan papkada bajaring.`,
          )
        : ''}</p>
      <ul class="limits">
        ${t(
          html`<li><strong>The limit counts questions, not model requests.</strong> Each question takes several requests. The recorded run needed ${fact(run.requests.answered)} requests for ${fact(run.question_limit)} questions.</li>
        <li><strong>Ctrl+C pauses at the next checkpoint.</strong> Resume continues from the same frozen copy, not from files you have changed since.</li>
        <li><strong>By default it looks for permission problems in FastAPI routes.</strong> If your project has none, for example because it has only Next.js code, Plumb says which kinds of check it does have and prints the exact option to use. Other kinds can be chosen with <span class="fact whole">--family injection</span>, <span class="fact whole">--family path_traversal</span> or <span class="fact whole">--family nextjs_exposure</span>. They have misses on record, so do not treat them as reliable coverage.</li>
        <li><strong>An empty result is not a clean bill of health.</strong> It means nothing in the chosen scope was reported.</li>`,
          html`<li><strong>Chegara model so‘rovlarini emas, savollarni sanaydi.</strong> Har bir savol bir necha so‘rov talab qiladi. Yozib olingan sinovda ${fact(run.question_limit)} ta savolga ${fact(run.requests.answered)} ta so‘rov ketgan.</li>
        <li><strong>Ctrl+C ishni keyingi nazorat nuqtasida to‘xtatadi.</strong> Davom ettirilganda tekshiruv o‘sha muzlatilgan nusxadan boshlanadi, keyin o‘zgartirgan fayllaringizdan emas.</li>
        <li><strong>Odatda u FastAPI manzillaridagi ruxsat muammolarini qidiradi.</strong> Loyihangizda bundaylari bo‘lmasa, masalan unda faqat Next.js kodi bo‘lsa, Plumb loyihada qaysi turdagi tekshiruvlar borligini aytadi va aynan qaysi parametrni yozish kerakligini ko‘rsatadi. Boshqa turlarni <span class="fact whole">--family injection</span>, <span class="fact whole">--family path_traversal</span> yoki <span class="fact whole">--family nextjs_exposure</span> bilan tanlash mumkin. Ularda aniqlanmay qolgan xatolar qayd etilgan, shuning uchun ularga to‘liq ishonmang.</li>
        <li><strong>Bo‘sh natija «hammasi joyida» degani emas.</strong> U faqat tanlangan qamrovda hech narsa topilmaganini bildiradi.</li>`,
        )}
      </ul>
    </div>`,
  });

  const todo = t('What to do', 'Nima qilish kerak');
  const says = t('What it reports', 'Nima deydi');
  const refusalsBand = band({
    id: 'refusals',
    heading: t('When Plumb refuses.', 'Plumb ishni rad etganda.'),
    intro: html`<p>${t(
      'A refusal is the tool working as intended. Each one names what is missing.',
      'Rad etish — vosita to‘g‘ri ishlayotganining belgisi. Har bir rad javobida nima yetishmayotgani aytiladi.',
    )}</p>`,
    body: html`<table class="plain stack">
      <caption class="sr-only">${t('What Plumb reports when it refuses, and what to do', 'Plumb rad etganda nima deydi va nima qilish kerak')}</caption>
      <thead><tr><th scope="col">${says}</th><th scope="col">${todo}</th></tr></thead>
      <tbody>
        ${refusals().map((entry) => html`<tr><th scope="row">${entry.says}</th><td data-label="${todo}">${entry.action}</td></tr>`)}
      </tbody>
    </table>
    <p class="more"><a href="/evidence#kinds">${t('What Supported, Rejected and Inconclusive mean', '«Tasdiqlandi», «Rad etildi» va «Noaniq» nimani anglatadi')}</a></p>`,
  });

  return page({
    path,
    title: t('Get Plumb', 'Plumbni o‘rnatish'),
    description: site.download
      ? t(
          'Download Plumb for Windows or install it from source: what the package holds and what has not been tried with it, what you need, every step in order, how to review your own project, and what Plumb refuses to do.',
          'Windows uchun Plumbni yuklab oling yoki manba kodidan o‘rnating: to‘plam ichida nima borligi va u bilan nima hali sinab ko‘rilmagani, nima kerakligi, barcha qadamlar tartib bilan, o‘z loyihangizni qanday tekshirish va Plumb nimani rad etishi.',
        )
      : t(
          'Why Plumb has no download button yet, what it needs, how to install it from source step by step or from the Windows package, how to review your own project, and what it refuses to do.',
          'Plumbni nega hozircha yuklab olib bo‘lmasligi, unga nima kerakligi, uni manba kodidan qadam-baqadam yoki Windows to‘plamidan qanday o‘rnatish, o‘z loyihangizni qanday tekshirish va u nimani rad etishi.',
        ),
    body: site.download
      ? html`${head}${downloadBand}${needs}${packageBand}${source}${own}${refusalsBand}`
      : html`${head}${today}${needs}${source}${packageBand}${own}${refusalsBand}`,
    context,
  });
}
