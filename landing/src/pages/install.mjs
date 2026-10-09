// @ts-check
import { band, page } from '../components/layout.mjs';
import { command, fact, reportShot } from '../components/parts.mjs';
import { reviewConsole } from '../components/terminal.mjs';
import { day, gb, int, mb, shortHash } from '../lib/format.mjs';
import { guide, refusals, reviewCommands } from '../lib/guide.mjs';
import { holds } from '../lib/holds.mjs';
import { html } from '../lib/html.mjs';
import { t } from '../lib/lang.mjs';

export const path = '/install';

/** @param {import('../components/layout.mjs').PageContext} context */
export function render(context) {
  const { record, site } = context;
  const { run, model, package: pack } = record;
  const { admission } = run;
  const { steps, downloadBytes } = guide(record, site);
  const review = reviewCommands(run);

  holds(pack.clean_user_profile === false, 'a fresh Windows account has not been tested');
  holds(run.machine.cpu.includes('i5-1135G7') && run.machine.gpu.includes('MX350'), 'measured on an i5-1135G7 with MX350 graphics');

  const head = html`<header class="page-head">
  <div class="wrap">
    <h1>${t('Get Plumb', 'Plumbni o‘rnatish')}</h1>
    <p class="lede">${site.download
      ? t(
          'Plumb is a program you run on your own Windows computer. Download the ready-made package or install it from source. This page lists what you need, every command in order, and what you will see.',
          'Plumb o‘z Windows kompyuteringizda ishlaydigan dastur. Tayyor to‘plamni yuklab oling yoki manba kodidan o‘rnating. Bu sahifada nima kerakligi, barcha buyruqlar tartib bilan va natijada nimani ko‘rishingiz aytilgan.',
        )
      : t(
          'Plumb is a program you run on your own Windows computer. This page says why there is no download button yet, what you need, every command in order, and what you will see.',
          'Plumb o‘z Windows kompyuteringizda ishlaydigan dastur. Bu sahifada hozircha nega yuklab olish tugmasi yo‘qligi, nima kerakligi, barcha buyruqlar tartib bilan va natijada nimani ko‘rishingiz aytilgan.',
        )}</p>
  </div>
</header>`;

  const availability = site.repository && site.download
    ? t(
        html`<p class="condition"><strong>The source code and a Windows package are public.</strong> Get the code from <a href="${site.repository}">the repository</a>, or <a href="${site.download}">download the package</a> (${fact(mb(pack.archive_bytes))}, SHA-256 ${fact(`${shortHash(pack.archive_sha256)}…`)}).</p>`,
        html`<p class="condition"><strong>Manba kodi va Windows to‘plami ochiq.</strong> Kodni <a href="${site.repository}">repozitoriydan</a> oling yoki <a href="${site.download}">to‘plamni yuklab oling</a> (${fact(mb(pack.archive_bytes))}, SHA-256 ${fact(`${shortHash(pack.archive_sha256)}…`)}).</p>`,
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

  const { download } = record;
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
          html`<li><strong>It is the investigator from the recorded test.</strong> The package from that run was rebuilt to leave out ${fact(download.files_left_out)} launcher files that only worked on the build laptop, and two mentions of private names. Its ${fact(download.investigator_files_identical)} investigator files are byte for byte the same.</li>
        <li><strong>It has only been tried on the laptop it was built on.</strong> There, with developer tools removed from the path, it mapped the practice app, opened the recorded report and served its browser view. A fresh Windows account and other computers have not been tested.</li>
        <li><strong>The AI model is not inside.</strong> Setup downloads it (${fact(gb(model.size))}) from Hugging Face after showing you its size, source and licence. Full reviews start only on the measured laptop model.</li>
        <li><strong>Plumb is not a web service.</strong> It runs on your computer on purpose, so that your code stays with you.</li>`,
          html`<li><strong>Bu yozib olingan sinovdagi tekshiruvchining o‘zi.</strong> O‘sha sinovdagi to‘plam qayta yig‘ilib, faqat yig‘ilgan noutbukda ishlaydigan ${fact(download.files_left_out)} ta ishga tushirish fayli va ikki joydagi shaxsiy nomlar olib tashlangan. Tekshiruvchining ${fact(download.investigator_files_identical)} ta fayli baytma-bayt bir xil.</li>
        <li><strong>U faqat yig‘ilgan noutbukda sinab ko‘rilgan.</strong> U yerda, dasturchi vositalari olib tashlangan holda, sinov ilovasining xaritasini tuzdi, yozib olingan hisobotni ochdi va brauzerdagi interfeysini ishga tushirdi. Yangi Windows hisobi va boshqa kompyuterlarda sinab ko‘rilmagan.</li>
        <li><strong>SI modeli to‘plam ichida emas.</strong> O‘rnatuvchi uni (${fact(gb(model.size))}) hajmi, manbasi va litsenziyasini ko‘rsatgandan keyin Hugging Face’dan yuklab oladi. To‘liq tekshiruv faqat o‘lchangan noutbuk modelida ishga tushadi.</li>
        <li><strong>Plumb veb-xizmat emas.</strong> U ataylab sizning kompyuteringizda ishlaydi, shunda kodingiz o‘zingizda qoladi.</li>`,
        )}
      </ul>
      <div class="routes">
        <a class="route-card" href="#package"><span class="route-title">${t('After downloading', 'Yuklab olgandan keyin')}</span><span class="small">${t('Extract, set up the model, map the practice app.', 'Arxivdan chiqaring, modelni o‘rnating, sinov ilovasining xaritasini tuzing.')}</span></a>
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
          html`<li><strong>The ready-made package has only been tried where it was built.</strong> It is a ${fact(mb(pack.archive_bytes))} ZIP that worked on this one laptop, under the Windows account it was built with. A fresh Windows account has not been tested, and a download button would promise more than that.</li>
        <li><strong>The AI model is not inside it.</strong> It is a separate ${fact(gb(model.size))} file that setup downloads from Hugging Face, after showing you its size, source and licence.</li>
        <li><strong>Plumb is not a web service.</strong> Putting this website on a server does not make Plumb run there. It runs on your computer on purpose, so that your code stays with you.</li>`,
          html`<li><strong>Tayyor to‘plam faqat yig‘ilgan joyida sinalgan.</strong> Bu ${fact(mb(pack.archive_bytes))} hajmli ZIP fayl bitta noutbukda, u yig‘ilgan Windows hisobida ishlagan. Yangi Windows hisobida sinab ko‘rilmagan, yuklab olish tugmasi esa bundan ko‘prog‘ini va’da qilgan bo‘lardi.</li>
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
          'Windows, 64-bit, with PowerShell. No administrator rights, Docker or Windows Sandbox.',
          '64 bitli Windows va PowerShell. Administrator huquqlari, Docker yoki Windows Sandbox kerak emas.',
        )}</dd></div>
      <div><dt>${site.download ? t('Tools, for the source install', 'Dasturlar, manba kodidan o‘rnatish uchun') : t('Tools', 'Dasturlar')}</dt>
        <dd>${t(
          'Git, uv, Node.js 24 or newer, and pnpm. uv brings Python 3.12 with it.',
          'Git, uv, Node.js 24 yoki undan yangi versiyasi va pnpm. Python 3.12 ni uv o‘zi olib keladi.',
        )}</dd></div>
      <div><dt>${t('For reviews with the AI model', 'SI modeli bilan tekshiruv uchun')}</dt>
        <dd>${t(
          html`The one measured hardware profile, ${fact(run.profile)}: an Intel Core i5-1135G7 with ${run.machine.gpu} graphics, and at launch ${fact(gb(admission.host_bytes))} of free RAM and ${fact(gb(admission.device_bytes))} of free graphics memory. Plumb checks this before every start and refuses when there is less. More memory alone does not qualify another computer.`,
          html`O‘lchangan yagona qurilma profili, ${fact(run.profile)}: Intel Core i5-1135G7 protsessori va ${run.machine.gpu} videokartasi, ishga tushirish paytida esa ${fact(gb(admission.host_bytes))} bo‘sh operativ xotira va ${fact(gb(admission.device_bytes))} bo‘sh videoxotira. Plumb buni har safar boshlashdan oldin tekshiradi va kam bo‘lsa, ishni boshlamaydi. Xotira ko‘pligining o‘zi boshqa kompyuterga ruxsat bermaydi.`,
        )}</dd></div>
      <div><dt>${t('Disk and internet', 'Disk va internet')}</dt>
        <dd>${t(
          html`Internet once, during setup. On the measured laptop the downloads come to ${fact(gb(downloadBytes))}: the model ${fact(model.file)} from ${fact(model.repo)}, licence ${fact(model.license)}, and the program that runs it. Plumb checks each file against a pinned fingerprint before using it.`,
          html`Internet faqat bir marta, o‘rnatish paytida kerak. O‘lchangan noutbukda yuklanadigan fayllar jami ${fact(gb(downloadBytes))}: ${fact(model.repo)} dagi ${fact(model.file)} modeli (litsenziyasi ${fact(model.license)}) va uni ishga tushiradigan dastur. Plumb har bir faylni ishlatishdan oldin oldindan belgilangan barmoq izi bilan solishtiradi.`,
        )}</dd></div>
      <div><dt>${t('On other computers', 'Boshqa kompyuterlarda')}</dt>
        <dd>${t(
          'Mapping a project and opening saved reports, without the AI model. This is how Plumb is built to work there, but it has not been tried on a second computer yet.',
          'SI modelisiz loyiha xaritasini tuzish va saqlangan hisobotlarni ochish. Plumb u yerda shunday ishlaydigan qilib qurilgan, lekin ikkinchi kompyuterda hali sinab ko‘rilmagan.',
        )}</dd></div>
    </dl>`,
  });

  const recordedReview = html`<details class="more-detail">
    <summary>${t('What the review printed in the recorded test', 'Yozib olingan sinovda tekshiruv nima chiqargani')}</summary>
    ${reviewConsole(run)}
  </details>`;

  const source = band({
    id: 'source',
    heading: t('Install from source, step by step.', 'Manba kodidan o‘rnatish, qadam-baqadam.'),
    intro: html`<p>${t(
      'Open PowerShell and type each command in turn. Steps marked “measured laptop” work only on the one measured laptop model.',
      'PowerShell’ni oching va buyruqlarni navbat bilan yozing. «O‘lchangan noutbuk» deb belgilangan qadamlar faqat o‘lchab ko‘rilgan noutbuk modelida ishlaydi.',
    )}</p>`,
    body: html`<ol class="steps">
      ${steps.map(
        (step) => html`<li id="step-${step.id}"><div>
        <p><strong>${step.title}</strong>${step.measuredOnly ? html` <span class="tag">${t('measured laptop', 'o‘lchangan noutbuk')}</span>` : ''}${step.optional ? html` <span class="tag">${t('optional', 'ixtiyoriy')}</span>` : ''}</p>
        <p class="step-detail">${step.detail}</p>
        ${step.commands ? command(step.commands.join('\n')) : ''}
        ${step.otherwise ? html`<p class="step-detail">${step.otherwise}</p>${command((step.otherCommands ?? []).join('\n'))}` : ''}
        ${step.id === 'review' ? recordedReview : ''}
        ${step.id === 'report'
          ? html`<figure class="report-figure is-inline">
          ${reportShot('finding', t('One finding in the saved report: Supported from the source, runtime check not tested, and what Plumb looked for', 'Saqlangan hisobotdagi bitta topilma: kod bo‘yicha tasdiqlangan, jonli sinov o‘tkazilmagan va Plumb nimalarni qidirgani'), [1152, 1040])}
          <figcaption class="small">${t(
            html`One finding in the report from the recorded test. A picture of the <a href="/saved-report/report.html">published report file</a>.`,
            html`Yozib olingan sinov hisobotidagi bitta topilma. <a href="/saved-report/report.html">E’lon qilingan hisobot faylining</a> rasmi.`,
          )}</figcaption>
        </figure>`
          : ''}
      </div></li>`,
      )}
    </ol>`,
  });

  const packageSteps = band({
    id: 'package',
    heading: site.download
      ? t('Use the Windows package.', 'Windows to‘plamidan foydalaning.')
      : t('Or start from the Windows package.', 'Yoki Windows to‘plamidan boshlang.'),
    intro: html`<p>${t(
      site.download
        ? html`After downloading the ZIP. Python, Node and the browser view are inside, so nothing else has to be installed first. The model is still downloaded by setup.`
        : html`If you were sent the ZIP (${fact(mb(pack.archive_bytes))}, ${fact(int(pack.inventoried_files))} files). Python, Node and the browser view are inside, so nothing else has to be installed first. The model is still downloaded by setup.`,
      site.download
        ? html`ZIP faylni yuklab olgandan keyin. Ichida Python, Node va brauzerdagi interfeys bor, shuning uchun oldindan boshqa hech narsa o‘rnatish shart emas. Modelni baribir o‘rnatuvchi yuklab oladi.`
        : html`Agar sizga ZIP fayl (${fact(mb(pack.archive_bytes))}, ${fact(int(pack.inventoried_files))} ta fayl) yuborilgan bo‘lsa. Ichida Python, Node va brauzerdagi interfeys bor, shuning uchun oldindan boshqa hech narsa o‘rnatish shart emas. Modelni baribir o‘rnatuvchi yuklab oladi.`,
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
          html`<strong>Double-click Start Plumb.cmd</strong> to open the browser view, or open PowerShell in the extracted folder and use the commands below.`,
          html`Brauzerdagi interfeysni ochish uchun <strong>Start Plumb.cmd faylini ikki marta bosing</strong>. Yoki chiqarilgan papkada PowerShell’ni ochib, quyidagi buyruqlardan foydalaning.`,
        )}</p>
      </div></li>
      <li><div>
        <p>${t(
          html`<strong>The same steps as above</strong>, with <span class="fact whole">.\\plumb.cmd</span> in place of <span class="fact whole">uv run plumb</span>.`,
          html`<strong>Yuqoridagi qadamlarning o‘zi</strong>, faqat <span class="fact whole">uv run plumb</span> o‘rniga <span class="fact whole">.\\plumb.cmd</span> yoziladi.`,
        )}</p>
        ${command(
          [
            '.\\plumb.cmd setup',
            '.\\plumb.cmd setup --install --approve-large-downloads',
            `.\\plumb.cmd inspect ${review.lab}`,
            '.\\plumb.cmd doctor',
            review.packaged,
            '.\\plumb.cmd report <run-id> --open',
          ].join('\n'),
        )}
      </div></li>
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
      )}</p>
      <ul class="limits">
        ${t(
          html`<li><strong>The limit counts questions, not model requests.</strong> Each question takes several requests. The recorded run needed ${fact(run.requests.answered)} requests for ${fact(run.question_limit)} questions.</li>
        <li><strong>Ctrl+C pauses at the next checkpoint.</strong> Resume continues from the same frozen copy, not from files you have changed since.</li>
        <li><strong>By default it looks for permission problems in FastAPI routes.</strong> Other kinds can be chosen with <span class="fact whole">--family injection</span>, <span class="fact whole">--family path_traversal</span> or <span class="fact whole">--family nextjs_exposure</span>. They have misses on record, so do not treat them as reliable coverage.</li>
        <li><strong>An empty result is not a clean bill of health.</strong> It means nothing in the chosen scope was reported.</li>`,
          html`<li><strong>Chegara model so‘rovlarini emas, savollarni sanaydi.</strong> Har bir savol bir necha so‘rov talab qiladi. Yozib olingan sinovda ${fact(run.question_limit)} ta savolga ${fact(run.requests.answered)} ta so‘rov ketgan.</li>
        <li><strong>Ctrl+C ishni keyingi nazorat nuqtasida to‘xtatadi.</strong> Davom ettirilganda tekshiruv o‘sha muzlatilgan nusxadan boshlanadi, keyin o‘zgartirgan fayllaringizdan emas.</li>
        <li><strong>Odatda u FastAPI manzillaridagi ruxsat muammolarini qidiradi.</strong> Boshqa turlarni <span class="fact whole">--family injection</span>, <span class="fact whole">--family path_traversal</span> yoki <span class="fact whole">--family nextjs_exposure</span> bilan tanlash mumkin. Ularda aniqlanmay qolgan xatolar qayd etilgan, shuning uchun ularga to‘liq ishonmang.</li>
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
    description: t(
      'Why Plumb has no download button yet, what it needs, how to install it from source step by step or from the Windows package, how to review your own project, and what it refuses to do.',
      'Plumbni nega hozircha yuklab olib bo‘lmasligi, unga nima kerakligi, uni manba kodidan qadam-baqadam yoki Windows to‘plamidan qanday o‘rnatish, o‘z loyihangizni qanday tekshirish va u nimani rad etishi.',
    ),
    body: site.download
      ? html`${head}${downloadBand}${needs}${packageSteps}${source}${own}${refusalsBand}`
      : html`${head}${today}${needs}${source}${packageSteps}${own}${refusalsBand}`,
    context,
  });
}
