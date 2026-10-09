// @ts-check
import { bobEnd, glyph } from '../components/glyphs.mjs';
import { band, page } from '../components/layout.mjs';
import { command, exhibit, fact, probeTable, stamp, verdict } from '../components/parts.mjs';
import { peerClaim, peerExclusions, peerTable } from '../components/peer.mjs';
import { commandLine, day, gb, int, kb, longDay, minutes, seconds, shortHash, time } from '../lib/format.mjs';
import { holds } from '../lib/holds.mjs';
import { html } from '../lib/html.mjs';
import { lang, t } from '../lib/lang.mjs';

export const path = '/recorded-run';

const reportKind = (/** @type {string} */ name) =>
  ({
    'report.html': t('for reading in a browser', 'brauzerda o‘qish uchun'),
    'report.md': t('plain text for a pull request or ticket', 'pull request yoki vazifa kartasiga qo‘shish uchun oddiy matn'),
    'report.json': t('the full record, for other programs', 'to‘liq yozuv, boshqa dasturlar uchun'),
    'report.sarif': t('the format code-scanning tools exchange', 'kod skanerlari o‘zaro almashadigan standart format'),
  })[name];

// Found, not found, or not something source code can settle.
const SEARCH_GLYPH = { found: 'dot', not_found: 'ring', unsupported: 'half' };

/** What Plumb searched for before reporting, with the report's own note for each item. */
function searches(/** @type {any} */ finding) {
  return html`<ul class="checks" lang="en">
    ${finding.searches.map(
      (/** @type {any} */ search) => html`<li${search.status === 'found' ? html` class="found"` : ''}>
        ${glyph(/** @type {any} */ (SEARCH_GLYPH[/** @type {keyof typeof SEARCH_GLYPH} */ (search.status)]))}
        <span><strong>${search.item}.</strong> <span class="res">${search.note}.</span></span>
      </li>`,
    )}
  </ul>`;
}

/** The code ranges every search of a finding covered. */
function searchedPlaces(/** @type {any} */ finding) {
  const [first, ...others] = finding.searches;
  holds(
    others.every((/** @type {any} */ search) => search.places.join() === first.places.join()),
    'every search covered the same code',
  );
  return html`<p class="small">${t('Code searched', 'Qidirilgan kod')}: ${first.places.map((/** @type {string} */ place, /** @type {number} */ index) => html`${index ? ', ' : ''}${fact(place)}`)}</p>`;
}

/** "CWE-639, CWE-862": the weakness classes the report assigns. */
const cweList = (/** @type {any} */ finding) => finding.cwe.map((/** @type {number} */ id) => `CWE-${id}`).join(', ');

/** One row per judgment: the seed that shuffled the evidence, and what the model answered. */
function judgments(/** @type {any} */ finding) {
  const answerWords = t('Recorded answer', 'Yozib olingan javob');
  const readWords = t('Read as', 'Qanday talqin qilindi');
  const ruleWords = t('Rule violations', 'Qoida buzilishlari');
  return html`<table class="plain stack judgments">
    <caption class="sr-only">${t(`The three judgments recorded for ${finding.display_id}`, `${finding.display_id} uchun yozib olingan uchta baho`)}</caption>
    <thead><tr><th scope="col">Seed</th><th scope="col">${answerWords}</th><th scope="col">${readWords}</th><th scope="col">${ruleWords}</th></tr></thead>
    <tbody>
      ${finding.judgments.map((/** @type {any} */ sample) => {
        const answer = sample.answer.guards
          ? sample.answer.guards.map((/** @type {any} */ guard) => `${guard.kind}: ${guard.object} = ${guard.subject}`).join('; ')
          : sample.answer.reason;
        return html`<tr><th scope="row"><span class="judgment-label">Seed </span>${fact(sample.seed)}</th><td data-label="${answerWords}">${fact(answer)}</td><td data-label="${readWords}">${fact(sample.interpretation)}</td><td data-label="${ruleWords}">${fact(sample.violations)}</td></tr>`;
      })}
    </tbody>
  </table>`;
}

/** @param {import('../components/layout.mjs').PageContext} context */
export function render(context) {
  const { record } = context;
  const { run, excerpts, runtime, model } = record;
  const [receipt, invoice] = run.findings;
  const { peer, overview, coverage, admission, initial_refusal: refusal } = run;
  const requestsFor = (/** @type {string} */ id) =>
    run.requests.by_finding.find((/** @type {any} */ entry) => entry.finding === id).kinds;
  const total = (/** @type {Record<string, number>} */ kinds) => Object.values(kinds).reduce((a, b) => a + b, 0);
  const receiptRequests = requestsFor(receipt.display_id);
  const invoiceRequests = requestsFor(invoice.display_id);
  const step = (/** @type {any} */ probe, /** @type {string} */ role) =>
    probe.steps.find((/** @type {any} */ entry) => entry.role === role);

  holds(receipt.conclusion === 'supported' && invoice.conclusion === 'rejected', 'receipt supported, invoice rejected');
  holds(run.requests.answered === run.requests.started, 'every request was answered');
  holds(run.exit === 0 && !run.budget_stop && run.memory_abort === null && run.forced_stops === 0, 'the run ended normally');
  holds(refusal.available_bytes < admission.host_bytes && refusal.model_loaded === false, 'the first attempt was refused');
  holds(admission.available_bytes >= admission.host_bytes, 'the run was admitted with enough memory');
  holds(receipt.judgments.every((/** @type {any} */ sample) => sample.interpretation === 'none_found'), 'three times it found none');
  holds(invoice.judgments.every((/** @type {any} */ sample) => sample.interpretation === 'scoped_elsewhere'), 'three times it named the ownership check');
  holds([receipt, invoice].every((finding) => finding.judgments.every((/** @type {any} */ sample) => sample.violations === 0)), 'no rule violations');
  holds(run.proposal.status === 'refused', 'the fix proposal was refused');
  holds(run.target_code_executed === false, 'app code executed: no');
  holds(invoice.guards.some((/** @type {any} */ guard) => guard.kind === 'owner' && guard.mechanism === 'query_filter'), 'the invoice guard is a query filter');
  holds(step(runtime.receipt, 'attack').status === 200 && step(runtime.receipt, 'attack').marker_present, 'Bob received Alice’s receipt');
  holds(step(runtime.invoice, 'attack').status === 404 && !step(runtime.invoice, 'attack').marker_present, 'Bob was refused the invoice');
  holds(step(runtime.replay.after, 'attack').status === 404 && step(runtime.replay.after, 'control').status === 200, 'after the fix Bob is refused and Alice still succeeds');
  holds(runtime.replay.review_id !== run.id, 'the runtime records belong to a different saved review');

  const roleCount = peer.rows.filter((/** @type {any} */ row) => !row.excluded && row.applied.includes('role')).length;
  const ownerGuard = invoice.guards.find((/** @type {any} */ guard) => guard.kind === 'owner');
  const severity = receipt.severity_rationale.replace(/ Evidence: [^.]*\./, '');
  const from = (/** @type {string} */ what) => t(`From ${what}`, `${what} faylidan`);

  const head = html`<header class="page-head">
  <div class="wrap">
    <h1>${t('The recorded test run', 'Yozib olingan sinov')}</h1>
    <p class="lede">${t(
      html`On ${longDay(run.started_at)} Plumb reviewed two routes of a practice app on an ordinary laptop and saved what it did. This page follows those saved files in order. Nothing here is re-enacted.`,
      html`${longDay(run.started_at)} kuni Plumb oddiy noutbukda sinov ilovasining ikki manzilini tekshirdi va qilgan ishini saqlab qo‘ydi. Bu sahifa o‘sha saqlangan fayllarni tartib bilan ko‘rsatadi. Hech narsa qaytadan sahnalashtirilmagan.`,
    )}</p>
  </div>
</header>`;

  const glance = band({
    id: 'glance',
    heading: t('The run at a glance.', 'Sinov bir qarashda.'),
    intro: html`<ul class="reading">
      <li>${t('A pale sheet holds material from the saved files.', 'Och rangli varaqlarda saqlangan fayllardan olingan ma’lumotlar berilgan.')}</li>
      <li>${t(
        html`Values set ${fact('like this')} are copied from those files by a script when the site is built. They are not typed by hand.`,
        html`${fact('Mana shunday')} shriftda yozilgan qiymatlarni sayt yig‘ilayotganda skript o‘sha fayllardan ko‘chiradi. Ular qo‘lda yozilmagan.`,
      )}</li>
      <li>${t(
        html`<span class="unproven">Blue</span> marks what has not been proven. Here that is one thing: nothing was tested by running the app.`,
        html`<span class="unproven">Ko‘k rang</span> isbotlanmagan narsani bildiradi. Bu sahifada bunday narsa bitta: ilova ishga tushirilib sinalmagan.`,
      )}</li>
      ${lang() === 'uz' ? html`<li>Hisobotdan olingan matnlar ingliz tilida qoldirilgan: tarjima qilinsa, ular asl nusxa bo‘lmay qoladi.</li>` : ''}
    </ul>`,
    body: html`<div class="sheet">
      ${stamp(t('From the run record and report.json', 'Tekshiruv yozuvi va report.json faylidan'))}
      <dl class="facts">
        <div><dt>${t('Run', 'Tekshiruv')}</dt><dd>${run.id}</dd></div>
        <div><dt>${t('When', 'Qachon')}</dt><dd>${t(
          `${day(run.started_at)}, ${time(run.started_at)} to ${time(run.finished_at)} UTC`,
          `${day(run.started_at)}, ${time(run.started_at)} dan ${time(run.finished_at)} gacha (UTC)`,
        )}</dd></div>
        <div><dt>Model</dt><dd>${model.family} · ${model.quantization} · ${gb(model.size)}</dd></div>
        <div><dt>${t('Runtime', 'Modelni ishga tushiruvchi dastur')}</dt><dd>llama.cpp ${run.toolchain.llama_cpp_release} · ${run.toolchain.backend} · ${t('profile', 'profil')} ${run.profile}</dd></div>
        <div><dt>${t('Requests to the model', 'Modelga so‘rovlar')}</dt><dd>${t(
          `${run.requests.answered} answered of ${run.requests.started}`,
          `${run.requests.started} tadan ${run.requests.answered} tasiga javob olindi`,
        )}</dd></div>
        <div><dt>${t('Tokens', 'Tokenlar')}</dt><dd>${t(
          `${int(run.prompt_tokens)} read · ${int(run.completion_tokens)} written`,
          `${int(run.prompt_tokens)} ta o‘qildi · ${int(run.completion_tokens)} ta yozildi`,
        )}</dd></div>
        <div><dt>${t('Wall time', 'Ketgan vaqt')}</dt><dd>${seconds(run.elapsed_seconds)} s (${minutes(run.elapsed_seconds)})</dd></div>
        <div><dt>${t('Scope', 'Qamrov')}</dt><dd>${t(
          `${coverage.completed} of ${coverage.total} access checks · ${coverage.excluded} excluded · ${coverage.pending} pending`,
          `${coverage.total} joydan ${coverage.completed} tasi · ${coverage.excluded} tasi qamrovdan tashqari · ${coverage.pending} tasi kutilmoqda`,
        )}</dd></div>
        <div><dt>${t('Source conclusions', 'Koddan chiqarilgan xulosalar')}</dt><dd>${receipt.display_id} ${receipt.conclusion} · ${invoice.display_id} ${invoice.conclusion}</dd></div>
        <div><dt>${t('App code executed', 'Ilova kodi ishga tushirilganmi')}</dt><dd>${t('no', 'yo‘q')}</dd></div>
      </dl>
    </div>`,
  });

  const steps = band({
    id: 'steps',
    heading: t('What happened, in order.', 'Nima bo‘ldi: qadam-baqadam.'),
    intro: html`<p>${t(
      'From the command to the saved report. The line is the chain of evidence, and the result hangs from it.',
      'Buyruqdan saqlangan hisobotgacha. Chiziq — dalillar zanjiri, natija esa shoqul toshidek uning uchida osilib turadi.',
    )}</p>`,
    body: html`<ol class="plumbline">
      <li>
        <h3>${t('The command', 'Buyruq')}</h3>
        <p>${t(
          'One command started the review. In words: review the practice app, look only at how orders are reached, only at these two routes, only for permission problems, and ask at most two questions.',
          'Tekshiruvni bitta buyruq boshladi. Oddiy so‘z bilan aytganda: sinov ilovasini tekshir, faqat buyurtmalarga murojaat qilinadigan joylarga qara, faqat shu ikki manzilni ol, faqat ruxsatga oid muammolarni qidir va ko‘pi bilan ikkita savol ber.',
        )}</p>
        <div class="step-sheet">${command(commandLine(run.command))}</div>
        <p class="small step-note">${t(
          html`Folder paths are shortened. The last option pointed at a new, empty cache, so no answer from an earlier run could be reused. What was hoped for was written down before the run: receipt supported, invoice rejected, stop after ${fact(run.declared_stop.answers)} answers or ${fact(int(run.declared_stop.seconds))} seconds.`,
          html`Papka yo‘llari qisqartirilgan. Oxirgi parametr yangi, bo‘sh keshni ko‘rsatgan, shuning uchun avvalgi tekshiruvlardagi javoblardan foydalanib bo‘lmagan. Kutilgan natija tekshiruvdan oldin yozib qo‘yilgan: chek tasdiqlanadi, hisob-faktura rad etiladi, ${fact(run.declared_stop.answers)} ta javob yoki ${fact(int(run.declared_stop.seconds))} soniyadan keyin ish to‘xtatiladi.`,
        )}</p>
      </li>
      <li>
        <h3>${t('The memory check', 'Xotira tekshiruvi')}</h3>
        <p>${t(
          html`The first attempt did not start. The laptop had ${fact(gb(refusal.available_bytes))} of memory free and this model needs ${fact(gb(admission.host_bytes))}. Plumb refused, and no model was loaded. After other programs were closed, it was admitted with ${fact(gb(admission.available_bytes))} available. The requirement was not lowered.`,
          html`Birinchi urinishda ish boshlanmadi. Noutbukda ${fact(gb(refusal.available_bytes))} bo‘sh xotira bor edi, bu modelga esa ${fact(gb(admission.host_bytes))} kerak. Plumb ishni rad etdi va model yuklanmadi. Boshqa dasturlar yopilgach, ${fact(gb(admission.available_bytes))} bo‘sh xotira bilan ishga ruxsat berildi. Talab kamaytirilmadi.`,
        )}</p>
        <p class="small step-note">${t('The refusal, as recorded:', 'Rad javobi, yozib olinganidek:')} <span lang="en">${fact(refusal.message)}</span></p>
      </li>
      <li>
        <h3>${t('Mapping the app', 'Ilova xaritasini tuzish')}</h3>
        ${t(
          html`<p>Plumb froze ${fact(overview.included_files)} files into a snapshot and read them as text: ${fact(overview.python)} Python, ${fact(overview.typescript)} TypeScript and ${fact(overview.tsx)} TSX. It found ${fact(overview.fastapi_entries)} FastAPI routes, ${fact(overview.nextjs_entries)} Next.js entries and ${fact(overview.access_paths)} places where data is reached.</p>
        <p>A pattern scanner (Opengrep) added ${fact(overview.pattern_leads)} leads, ${fact(overview.pattern_leads_in_scope)} of them inside the chosen scope. A lead is a reason to ask a question. It is never reported as a finding by itself.</p>`,
          html`<p>Plumb ${fact(overview.included_files)} ta fayldan nusxa olib, ularni matn sifatida o‘qidi: ${fact(overview.python)} ta Python, ${fact(overview.typescript)} ta TypeScript va ${fact(overview.tsx)} ta TSX. U ${fact(overview.fastapi_entries)} ta FastAPI manzili, ${fact(overview.nextjs_entries)} ta Next.js kirish nuqtasi va ma’lumot yuklanadigan ${fact(overview.access_paths)} ta joy topdi.</p>
        <p>Andoza skaneri (Opengrep) ${fact(overview.pattern_leads)} ta ishora qo‘shdi, ulardan ${fact(overview.pattern_leads_in_scope)} tasi tanlangan qamrov ichida. Ishora faqat savol berishga sabab bo‘ladi, u hech qachon o‘z-o‘zidan topilma sifatida ko‘rsatilmaydi.</p>`,
        )}
        <div class="sheet step-sheet">
          ${stamp(t('From questions.json · why the receipt question was asked', 'questions.json faylidan · chek haqidagi savol nega berilgan'))}
          <ul class="quiet-list" lang="en">${receipt.priority_reasons.map((/** @type {string} */ reason) => html`<li>${reason}</li>`)}</ul>
        </div>
      </li>
      <li id="peer-check">
        <h3>${t('The peer check', 'O‘xshash joylar bilan solishtirish')}</h3>
        <p>${t(
          'Plumb compared every place that loads an order. It did not need a rule saying orders are private. The code itself showed the habit, and one route that breaks it.',
          'Plumb buyurtma yuklanadigan barcha joylarni bir-biri bilan solishtirdi. Buning uchun «buyurtmalar shaxsiy» degan qoida kerak bo‘lmadi: odatni ham, uni buzgan yagona manzilni ham kodning o‘zi ko‘rsatdi.',
        )}</p>
        <div class="sheet step-sheet">
          ${stamp(t('From report.json · peer comparison', 'report.json faylidan · o‘xshash joylar bilan solishtirish'))}
          <p class="peer-claim">${peerClaim(peer)}</p>
          ${peerTable(peer)}
          <p class="small peer-foot">${t(
            html`A gap is flagged only when at least ${fact(peer.min_peers)} peers exist and ${fact(`${peer.min_share * 100}%`)} of them apply the check. Here ${fact(peer.deviation.peers_applying)} of ${fact(peer.deviation.peers_total)} do. The staff role column is shown but not flagged: only ${fact(roleCount)} routes apply it, so its absence elsewhere is not a lead.`,
            html`Kamchilik faqat kamida ${fact(peer.min_peers)} ta o‘xshash joy bo‘lib, ularning ${fact(`${peer.min_share * 100}%`)} qismida tekshiruv bo‘lsagina belgilanadi. Bu yerda ${fact(peer.deviation.peers_total)} tadan ${fact(peer.deviation.peers_applying)} tasida bor. «Xodim roli» ustuni ko‘rsatilgan, lekin belgilanmagan: bu tekshiruv faqat ${fact(roleCount)} ta manzilda bor, shuning uchun boshqa joylarda yo‘qligi shubha uyg‘otmaydi.`,
          )}</p>
          <h4>${t('Left out of the comparison', 'Solishtirishga kiritilmaganlar')}</h4>
          ${peerExclusions(peer)}
          <h4>${t('The report’s own cautions', 'Hisobotning o‘z ogohlantirishlari')}</h4>
          <ul class="quiet-list small" lang="en">${peer.limitations.map((/** @type {string} */ line) => html`<li>${line}</li>`)}</ul>
        </div>
      </li>
      <li id="f-01">
        <h3>${receipt.display_id}: ${t('the receipt route', 'chek manzili')}</h3>
        <p>${t(
          'The peer check only raised a suspicion. Plumb then tried to clear the route. It searched for anything that would make the missing check acceptable, and asked the model three times whether the code contains an intended exception.',
          'Solishtirish faqat shubha uyg‘otdi. Keyin Plumb bu manzilni oqlashga urindi: tekshiruv yo‘qligini oqlaydigan har qanday narsani qidirdi va modeldan uch marta «bu yerda ataylab qilingan istisno bormi?» deb so‘radi.',
        )}</p>
        <div class="sheet step-sheet">
          ${stamp(html`${from('report.json')} · ${receipt.display_id} · ${cweList(receipt)}`)}
          ${verdict(receipt)}
          ${exhibit(excerpts.receipt_handler, {
            gloss: t(
              'The route. The marked line loads the order by its number alone.',
              'Manzil kodi. Belgilangan qator buyurtmani faqat raqami bo‘yicha yuklaydi.',
            ),
            mark: 'access',
          })}
          ${exhibit(excerpts.signed_in, {
            gloss: t(
              'The one check the route does have: the caller must be signed in. It says nothing about whose order it is.',
              'Bu manzildagi yagona tekshiruv: so‘rovchi tizimga kirgan bo‘lishi kerak. Buyurtma kimniki ekani bilan u qiziqmaydi.',
            ),
            mark: 'guard',
          })}
          <h4>${t('What Plumb looked for before reporting it', 'Xato deb ko‘rsatishdan oldin Plumb nimalarni qidirdi')}</h4>
          ${searches(receipt)}
          ${searchedPlaces(receipt)}
          <h4>${t('Three judgments', 'Uchta baho')}</h4>
          ${judgments(receipt)}
          <p class="small">${t(
            html`Each time the evidence was given in a different order, and each time the model answered that it found no intended exception. With all three agreeing and nothing found to clear it, the gap was recorded as ${fact(receipt.conclusion)}.`,
            html`Har safar dalillar boshqa tartibda berildi va har safar model ataylab qilingan istisno topmaganini aytdi. Uchala javob bir xil chiqqani va shubhani yo‘qqa chiqaradigan hech narsa topilmagani uchun kamchilik ${fact(receipt.conclusion)} deb qayd etildi.`,
          )}</p>
          <h4>${t('How serious, in the report’s words', 'Qanchalik jiddiy: hisobotning o‘z so‘zlari bilan')}</h4>
          <p class="small" lang="en">${severity}</p>
        </div>
        <p class="small step-note">${t(
          html`This finding took ${fact(total(receiptRequests))} of the ${fact(run.requests.answered)} requests: ${fact(receiptRequests.guard_summary)} to summarise the checks on the peer routes, ${fact(receiptRequests.gather)} to gather code, ${fact(receiptRequests.intentional_exception)} judgments and ${fact(receiptRequests.fix_sketch)} attempt at a fix.`,
          html`Bu topilmaga ${fact(run.requests.answered)} ta so‘rovdan ${fact(total(receiptRequests))} tasi ketdi: ${fact(receiptRequests.guard_summary)} tasi o‘xshash joylardagi tekshiruvlarni umumlashtirishga, ${fact(receiptRequests.gather)} tasi kod yig‘ishga, ${fact(receiptRequests.intentional_exception)} tasi baholashga va ${fact(receiptRequests.fix_sketch)} tasi tuzatish taklifiga.`,
        )}</p>
        <p class="small step-note">${t(
          html`<strong>The fix attempt failed.</strong> Plumb asked the model for a corrected version of the route. The validator ${fact(run.proposal.status)} it: ${fact(run.proposal.reason)} The report offers no fix for this finding.`,
          html`<strong>Tuzatishga urinish muvaffaqiyatsiz bo‘ldi.</strong> Plumb modeldan manzil kodining tuzatilgan variantini so‘radi. Tekshiruvchi dastur uni rad etdi (${fact(run.proposal.status)}): <span lang="en">${fact(run.proposal.reason)}</span> Hisobotda bu topilma uchun tuzatish taklif qilinmagan.`,
        )}</p>
      </li>
      <li id="f-02">
        <h3>${invoice.display_id}: ${t('the invoice route', 'hisob-faktura manzili')}</h3>
        <p>${t(
          'The invoice route was questioned in the same way, because from the outside it looks the same. This time the search found something.',
          'Hisob-faktura manzili ham xuddi shunday tekshirildi, chunki tashqaridan u chek manzilidan farq qilmaydi. Bu safar qidiruv natija berdi.',
        )}</p>
        <div class="sheet step-sheet">
          ${stamp(html`${from('report.json')} · ${invoice.display_id} · ${cweList(invoice)}`)}
          ${verdict(invoice)}
          ${exhibit(excerpts.invoice_handler, {
            gloss: t(
              'The route. It does not load the order itself. It calls a helper.',
              'Manzil kodi. U buyurtmani o‘zi yuklamaydi, yordamchi funksiyani chaqiradi.',
            ),
          })}
          ${exhibit(excerpts.invoice_helper, {
            gloss: t(
              'The helper, in another file. The marked lines are the protection the report cites.',
              'Boshqa fayldagi yordamchi funksiya. Belgilangan qatorlar — hisobotda ko‘rsatilgan himoya.',
            ),
            mark: 'guard',
          })}
          <h4>${t('What Plumb looked for', 'Plumb nimalarni qidirdi')}</h4>
          ${searches(invoice)}
          ${searchedPlaces(invoice)}
          <h4>${t('Three judgments', 'Uchta baho')}</h4>
          ${judgments(invoice)}
          <p class="small">${t(
            html`Three times the model named an ownership check between the caller and the order’s customer. Ordinary code then confirmed the cited lines: ${fact(ownerGuard.canonical)} at ${fact(ownerGuard.where)}, a ${fact(ownerGuard.mechanism)}. The lead was recorded as ${fact(invoice.conclusion)}.`,
            html`Model uch marta ham so‘rovchi buyurtma mijozining o‘zi ekanini tekshiradigan kodni ko‘rsatdi. So‘ng oddiy dastur ko‘rsatilgan qatorlarni tasdiqladi: ${fact(ownerGuard.canonical)}, joyi ${fact(ownerGuard.where)}, turi ${fact(ownerGuard.mechanism)}. Shubha ${fact(invoice.conclusion)} deb qayd etildi.`,
          )}</p>
        </div>
        <p class="small step-note">${t(
          html`This took the other ${fact(total(invoiceRequests))} requests: ${fact(invoiceRequests.gather)} to gather code and ${fact(invoiceRequests.guard_summary)} judgments.`,
          html`Bunga qolgan ${fact(total(invoiceRequests))} ta so‘rov ketdi: ${fact(invoiceRequests.gather)} tasi kod yig‘ishga va ${fact(invoiceRequests.guard_summary)} tasi baholashga.`,
        )}</p>
      </li>
      <li class="bob-end" id="saved">
        ${bobEnd}
        <h3>${t('What was saved', 'Nima saqlandi')}</h3>
        <p>${t(
          'Four report files, in different formats for different readers. These are the files exactly as Plumb wrote them. Their SHA-256 fingerprints match the ones in the run record.',
          'Turli o‘quvchilar uchun turli formatdagi to‘rtta hisobot fayli. Bular Plumb yozgan fayllarning aynan o‘zi. Ularning SHA-256 barmoq izlari tekshiruv yozuvidagilar bilan mos keladi.',
        )}</p>
        <div class="sheet step-sheet">
          ${stamp(t('Published byte for byte', 'Baytma-bayt, o‘zgarishsiz e’lon qilingan'))}
          <ul class="files">
            ${run.saved_reports.map(
              (/** @type {any} */ file) => html`<li>
                <a href="/saved-report/${file.name}">${file.name}</a>
                <span class="small">${reportKind(file.name)} · ${kb(file.bytes)}</span>
                <span class="hash">sha256 ${file.sha256}</span>
              </li>`,
            )}
          </ul>
        </div>
        <p class="small step-note">${t(
          html`Reading the saved result back with ${fact(`plumb report ${shortHash(run.id, 15)}…`)} took ${fact(`${seconds(run.report_read.elapsed_seconds)} s`)}, loaded no model and left the files unchanged. How the HTML report looks in a browser was not part of what was checked.`,
          html`Saqlangan natijani ${fact(`plumb report ${shortHash(run.id, 15)}…`)} buyrug‘i bilan qayta o‘qish ${fact(`${seconds(run.report_read.elapsed_seconds)} s`)} davom etdi, model yuklanmadi va fayllar o‘zgarmadi. HTML hisobotning brauzerdagi ko‘rinishi tekshiruvga kirmagan.`,
        )}</p>
      </li>
    </ol>`,
  });

  const runtimeSection = band({
    id: 'runtime',
    heading: t('Separately: what happened when requests were really sent.', 'Alohida: so‘rovlar haqiqatan yuborilganda nima bo‘ldi.'),
    intro: html`<p>${t(
      'A source finding says what the code allows. A runtime check shows what the running app does. Plumb records them under separate labels and does not turn one into the other.',
      'Koddan chiqarilgan xulosa kod nimaga yo‘l qo‘yishini aytadi. Jonli sinov esa ishlab turgan ilova aslida nima qilishini ko‘rsatadi. Plumb ularni alohida belgilar bilan qayd etadi va birini ikkinchisiga aylantirmaydi.',
    )}</p>`,
    body: html`<div class="stack-gap">
      ${t(
        html`<p>Everything above comes from reading code. The run on ${day(run.started_at)} sent no requests, and both of its findings carry the label <span class="unproven">runtime check: not attempted</span>.</p>
      <p>The results below come from different, earlier tests. A fixed script started the practice app on the same laptop and sent real requests as two made-up customers, Alice and Bob. Alice places an order. Bob then asks for it, and Alice asks for it herself. They belong to another saved review, ${fact(`${runtime.replay.review_id.slice(0, 15)}…`)}, and they cover this practice app only.</p>`,
        html`<p>Yuqoridagi hamma narsa kodni o‘qishdan kelib chiqqan. ${day(run.started_at)} kungi tekshiruv birorta ham so‘rov yubormagan va uning ikkala topilmasida <span class="unproven">jonli sinov: o‘tkazilmagan</span> belgisi turibdi.</p>
      <p>Quyidagi natijalar boshqa, avvalroq o‘tkazilgan sinovlardan olingan. Qat’iy belgilangan skript sinov ilovasini shu noutbukning o‘zida ishga tushirdi va ikki to‘qima mijoz — Alice va Bob nomidan haqiqiy so‘rovlar yubordi. Avval Alice buyurtma beradi. So‘ng Bob o‘sha buyurtmani so‘raydi, Alice ham o‘z buyurtmasini so‘raydi. Bu sinovlar boshqa saqlangan tekshiruvga (${fact(`${runtime.replay.review_id.slice(0, 15)}…`)}) tegishli va faqat shu sinov ilovasini qamraydi.</p>`,
      )}
      <div class="sheet">
        ${stamp(t(`Runtime records · ${day(runtime.receipt.at)} · no model involved`, `Jonli sinov yozuvlari · ${day(runtime.receipt.at)} · model ishtirok etmagan`))}
        ${probeTable([
          { label: t('Receipt route', 'Chek manzili'), steps: runtime.receipt.steps, outcome: runtime.receipt.outcome },
          { label: t('Invoice route', 'Hisob-faktura manzili'), steps: runtime.invoice.steps, outcome: runtime.invoice.outcome },
        ])}
      </div>
      <div class="sheet">
        ${stamp(t(
          `Runtime record · ${day(runtime.replay.at)} · the receipt route before and after one reviewed fix`,
          `Jonli sinov yozuvi · ${day(runtime.replay.at)} · chek manzili bitta ko‘rib chiqilgan tuzatishdan oldin va keyin`,
        ))}
        ${probeTable([
          { label: t('As written', 'Asl holida'), steps: runtime.replay.before.steps, outcome: runtime.replay.before.outcome },
          { label: t('With the fix', 'Tuzatish bilan'), steps: runtime.replay.after.steps, outcome: runtime.replay.after.outcome },
        ])}
      </div>
      <p class="small">${t(
        'The fix was one reviewed change to the practice app, tried in throwaway copies. Plumb cannot do this for other projects. It has no isolated place to run them, so it does not run them.',
        'Tuzatish sinov ilovasiga kiritilgan, oldindan ko‘rib chiqilgan bitta o‘zgarish edi va u vaqtinchalik nusxalarda sinab ko‘rildi. Plumb boshqa loyihalar bilan buni qila olmaydi: ularni ishga tushirish uchun ajratilgan muhit yo‘q, shuning uchun ularni ishga tushirmaydi.',
      )}</p>
    </div>`,
  });

  const notShown = band({
    id: 'not-shown',
    heading: t('What this run does not show.', 'Bu sinov nimani ko‘rsatmaydi.'),
    body: html`<ul class="limits">
      ${t(
        html`<li><strong>Coverage.</strong> ${fact(coverage.completed)} of ${fact(coverage.total)} access checks were reviewed. The other ${fact(coverage.excluded)} were outside the scope chosen for this run.</li>
      <li><strong>Accuracy.</strong> Two correct answers are not a success rate. The two routes were chosen before the run, and they were also used while Plumb was being built. A result on familiar cases says less than a result on unseen code.</li>
      <li><strong>Other apps.</strong> Tandir was written for this project. Nothing here was measured on code from anywhere else.</li>
      <li><strong>Sound reasoning.</strong> Every citation in the report resolves to real code. That shows the model pointed at the right lines. It does not prove the judgment.</li>
      <li><strong>Speed.</strong> ${fact(minutes(run.elapsed_seconds))} is one run on one laptop. It is not a benchmark.</li>`,
        html`<li><strong>Qamrov.</strong> Ma’lumot yuklanadigan ${fact(coverage.total)} ta joydan ${fact(coverage.completed)} tasi ko‘rib chiqildi. Qolgan ${fact(coverage.excluded)} tasi bu sinov uchun tanlangan qamrovdan tashqarida edi.</li>
      <li><strong>Aniqlik.</strong> Ikkita to‘g‘ri javobdan muvaffaqiyat foizi chiqmaydi. Bu ikki manzil sinovdan oldin tanlab olingan va Plumb ishlab chiqilayotganda ham ishlatilgan. Tanish holatdagi natija hali ko‘rilmagan koddagi natijachalik ko‘p narsa aytmaydi.</li>
      <li><strong>Boshqa ilovalar.</strong> Tandir shu loyiha uchun yozilgan. Boshqa joydan olingan kodda hech narsa o‘lchanmagan.</li>
      <li><strong>To‘g‘ri mulohaza.</strong> Hisobotdagi har bir havola haqiqiy kodga olib boradi. Bu model to‘g‘ri qatorlarni ko‘rsatganini bildiradi, xolos, bahoning o‘zi to‘g‘ri ekanini isbotlamaydi.</li>
      <li><strong>Tezlik.</strong> ${fact(minutes(run.elapsed_seconds))} bitta noutbukdagi bitta ishga tushirish natijasi. Bu tezlik o‘lchovi emas.</li>`,
      )}
    </ul>
    <details class="more-detail">
      <summary>${t(`The report’s own list of limitations (${run.limitations.length})`, `Hisobotning o‘z cheklovlar ro‘yxati (${run.limitations.length})`)}</summary>
      <ul lang="en">${run.limitations.map((/** @type {string} */ line) => html`<li>${line}</li>`)}</ul>
    </details>
    <p class="more"><a href="/evidence">${t('Strengths and limits of the whole project', 'Butun loyihaning imkoniyat va cheklovlari')}</a></p>`,
  });

  return page({
    path,
    title: t('The recorded test run', 'Yozib olingan sinov'),
    description: t(
      `A step-by-step walkthrough of a saved Plumb review from ${longDay(run.started_at)}: the receipt route reported, the protected invoice route cleared, and the report files as saved.`,
      `${longDay(run.started_at)} kuni saqlangan Plumb tekshiruvining qadam-baqadam bayoni: chek manzili xato deb topilgan, himoyalangan hisob-faktura manzili oqlangan, hisobot fayllari esa saqlanganidek berilgan.`,
    ),
    body: html`${head}${glance}${steps}${runtimeSection}${notShown}`,
    context,
  });
}
