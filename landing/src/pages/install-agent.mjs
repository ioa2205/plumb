// @ts-check
import { band, page } from '../components/layout.mjs';
import { command, copyBlock, fact } from '../components/parts.mjs';
import { gb, minutes } from '../lib/format.mjs';
import { AGENT_RULES, agentMessage, guide } from '../lib/guide.mjs';
import { html } from '../lib/html.mjs';
import { t } from '../lib/lang.mjs';

export const path = '/install/agent';

/** The file agents can read on their own; it is written in English, once, by the build. */
export const AGENT_FILE = '/agent-install.md';

/** @param {import('../components/layout.mjs').PageContext} context */
export function render(context) {
  const { record, site } = context;
  const { run } = record;
  const { steps, downloadBytes } = guide(record, site);
  const step = (/** @type {string} */ id) => /** @type {import('../lib/guide.mjs').Step} */ (steps.find((entry) => entry.id === id));

  const head = html`<header class="page-head">
  <div class="wrap">
    <h1>${t('Install Plumb with an AI agent', 'Plumbni SI agent yordamida o‘rnatish')}</h1>
    <p class="lede">${t(
      'Claude Code, Codex and similar coding agents can do the installation for you. Paste one message into the agent. It types the commands, explains what it sees, and asks you before anything large is downloaded.',
      'Claude Code, Codex va shunga o‘xshash dasturlash agentlari o‘rnatishni siz uchun bajara oladi. Agentga bitta xabar yuboring. U buyruqlarni o‘zi yozadi, natijani tushuntirib beradi va katta hajmdagi faylni yuklab olishdan oldin sizdan ruxsat so‘raydi.',
    )}</p>
  </div>
</header>`;

  const before = band({
    id: 'before',
    heading: t('Before you start.', 'Boshlashdan oldin.'),
    body: html`<ol class="steps">
      <li><div><p>${t(
        html`<strong>An AI coding agent that can run commands on this computer</strong>, such as Claude Code or Codex. Start it in an empty folder, or in the Plumb folder if you already have one.`,
        html`<strong>Shu kompyuterda buyruqlarni bajara oladigan SI dasturlash agenti</strong>, masalan Claude Code yoki Codex. Uni bo‘sh papkada yoki, agar Plumb papkasi allaqachon bo‘lsa, o‘sha papkada ishga tushiring.`,
      )}</p></div></li>
      <li><div><p>${site.repository
        ? t(
            html`<strong>Nothing to download by hand.</strong> The agent fetches the code from <a href="${site.repository}">the repository</a>.`,
            html`<strong>Qo‘lda hech narsa yuklab olish shart emas.</strong> Agent kodni <a href="${site.repository}">repozitoriydan</a> o‘zi oladi.`,
          )
        : t(
            html`<strong>The Plumb folder.</strong> The code is not public yet, so the agent cannot fetch it. <a href="/contact">Ask for a copy</a>, unpack it, and put the folder’s path into the message below.`,
            html`<strong>Plumb papkasi.</strong> Kod hali ommaga ochilmagan, shuning uchun agent uni o‘zi yuklab ololmaydi. <a href="/contact">Nusxa so‘rang</a>, uni arxivdan chiqaring va papka yo‘lini quyidagi xabarga qo‘ying.`,
          )}</p></div></li>
      <li><div><p>${t(
        html`<strong>Room for the downloads.</strong> On the measured laptop model setup downloads ${fact(gb(downloadBytes))}. Elsewhere it downloads no model.`,
        html`<strong>Yuklanadigan fayllar uchun joy.</strong> O‘lchangan noutbuk modelida o‘rnatuvchi ${fact(gb(downloadBytes))} yuklab oladi. Boshqa kompyuterlarda model yuklanmaydi.`,
      )}</p></div></li>
    </ol>`,
  });

  const message = band({
    id: 'message',
    heading: t('The message to paste.', 'Agentga yuboriladigan xabar.'),
    intro: html`<p>${t(
      'It is in English, which coding agents follow most reliably. The agent will still explain everything in plain words.',
      'Xabar ingliz tilida, chunki dasturlash agentlari inglizcha ko‘rsatmalarni eng aniq bajaradi. Oxirgi qatorda agentdan hammasini sizga o‘zbek tilida tushuntirish so‘ralgan.',
    )}</p>`,
    body: html`<div class="stack-gap">
      ${copyBlock(agentMessage(record, site), t('Message for the agent', 'Agent uchun xabar'))}
      ${site.repository
        ? ''
        : html`<p class="condition">${t(
            html`Replace <span class="fact whole">&lt;PASTE THE FOLDER PATH HERE&gt;</span> with the full path of the Plumb folder you unpacked, for example by dragging the folder into the agent’s window.`,
            html`<span class="fact whole">&lt;PASTE THE FOLDER PATH HERE&gt;</span> o‘rniga arxivdan chiqarilgan Plumb papkasining to‘liq yo‘lini yozing. Masalan, papkani agent oynasiga sudrab olib kelsangiz bo‘ladi.`,
          )}</p>`}
    </div>`,
  });

  const does = band({
    id: 'does',
    heading: t('What the agent will do.', 'Agent nima qiladi.'),
    intro: html`<p>${t(
      html`The same steps as the <a href="/install#source">install page</a>. Nothing it runs needs administrator rights.`,
      html`<a href="/install#source">O‘rnatish sahifasidagi</a> qadamlarning o‘zi. U bajaradigan buyruqlarning hech biri administrator huquqini talab qilmaydi.`,
    )}</p>`,
    body: html`<ol class="steps">
      ${['code', 'tools', 'environment', 'preview', 'install', 'inspect', 'doctor'].map((id) => {
        const entry = step(id);
        return html`<li><div>
          <p><strong>${entry.title}</strong></p>
          <p class="step-detail">${entry.detail}</p>
          ${entry.commands ? command(entry.commands.join('\n')) : ''}
          ${entry.otherwise ? html`<p class="step-detail">${entry.otherwise}</p>${command((entry.otherCommands ?? []).join('\n'))}` : ''}
        </div></li>`;
      })}
      <li><div><p>${t(
        html`<strong>It tells you the result.</strong> What worked, what did not, and whether this computer can run a full review with the AI model.`,
        html`<strong>Natijani aytadi.</strong> Nima ishladi, nima ishlamadi va bu kompyuter SI modeli bilan to‘liq tekshiruvni bajara oladimi.`,
      )}</p></div></li>
    </ol>`,
  });

  const stops = band({
    id: 'stops',
    heading: t('Where it stops and asks you.', 'Qayerda to‘xtab, sizdan so‘raydi.'),
    body: html`<ul class="limits">
      ${t(
        html`<li><strong>Before the large download.</strong> On the measured laptop it shows you the list of downloads first. Plumb itself refuses to start them without the approval option.</li>
      <li><strong>When a tool is missing.</strong> It tells you which one to install. It does not install Git, uv, Node.js or pnpm on its own.</li>
      <li><strong>When something fails or Plumb refuses.</strong> It shows you the exact message instead of working around it.</li>
      <li><strong>Before a review with the AI model.</strong> It does not start one unless you ask. On the measured laptop the recorded two-question review took ${fact(minutes(run.elapsed_seconds))}.</li>`,
        html`<li><strong>Katta faylni yuklab olishdan oldin.</strong> O‘lchangan noutbukda u avval yuklanadigan fayllar ro‘yxatini ko‘rsatadi. Roziligingizni bildiruvchi parametrsiz Plumbning o‘zi ularni yuklashni boshlamaydi.</li>
      <li><strong>Biror dastur yetishmasa.</strong> Qaysi birini o‘rnatish kerakligini aytadi. Git, uv, Node.js yoki pnpm ni o‘zboshimchalik bilan o‘rnatmaydi.</li>
      <li><strong>Biror narsa ishlamasa yoki Plumb rad etsa.</strong> Muammoni chetlab o‘tishga urinmaydi, xabarning aynan o‘zini sizga ko‘rsatadi.</li>
      <li><strong>SI modeli bilan tekshiruvdan oldin.</strong> Siz so‘ramaguningizcha uni boshlamaydi. O‘lchangan noutbukda ikki savolli yozib olingan tekshiruv ${fact(minutes(run.elapsed_seconds))} davom etgan.</li>`,
      )}
    </ul>
    <details class="more-detail">
      <summary>${t('The rules in the message', 'Xabardagi qoidalar')}</summary>
      <ul lang="en">${AGENT_RULES.map((rule) => html`<li>${rule}</li>`)}</ul>
    </details>`,
  });

  const file = band({
    id: 'file',
    heading: t('For agents that read web pages.', 'Veb-sahifani o‘qiy oladigan agentlar uchun.'),
    body: html`<div class="stack-gap">
      <p>${t(
        html`The same instructions, with what to report at the end, are in a plain text file: <a hreflang="en" href="${AGENT_FILE}">${AGENT_FILE.slice(1)}</a>. An agent with web access can be told to follow it.`,
        html`Xuddi shu ko‘rsatmalar, oxirida nimani aytib berish kerakligi bilan birga, oddiy matnli faylda ham bor: <a hreflang="en" href="${AGENT_FILE}">${AGENT_FILE.slice(1)}</a>. Internetga kira oladigan agentga shu faylga amal qilishni aytish mumkin.`,
      )}</p>
      ${site.url ? command(`Follow ${site.url}${AGENT_FILE} to install Plumb on this computer.`) : ''}
      <p class="small">${t(
        html`If something goes wrong, the <a href="/install#refusals">install page</a> lists what each refusal means. You can also <a href="/contact">write to me</a> with the exact message.`,
        html`Biror narsa noto‘g‘ri ketsa, <a href="/install#refusals">o‘rnatish sahifasida</a> har bir rad javobi nimani anglatishi yozilgan. Xabarning aynan o‘zini <a href="/contact">menga yuborishingiz</a> ham mumkin.`,
      )}</p>
      <p class="small">${t(
        html`Measured on the profile ${fact(run.profile)}. On other computers the agent can set up source mapping only, and that path has not yet been tried on a second computer.`,
        html`${fact(run.profile)} profilida o‘lchangan. Boshqa kompyuterlarda agent faqat kod xaritasini tuzish imkoniyatini o‘rnata oladi, bu yo‘l esa ikkinchi kompyuterda hali sinab ko‘rilmagan.`,
      )}</p>
    </div>`,
  });

  return page({
    path,
    title: t('Install Plumb with an AI agent', 'Plumbni SI agent yordamida o‘rnatish'),
    description: t(
      'One message to paste into Claude Code, Codex or a similar coding agent so it installs Plumb, checks the computer and maps the practice app, stopping to ask before large downloads.',
      'Claude Code, Codex yoki shunga o‘xshash dasturlash agentiga yuboriladigan bitta xabar: agent Plumbni o‘rnatadi, kompyuterni tekshiradi va sinov ilovasining xaritasini tuzadi, katta yuklab olishlardan oldin esa ruxsat so‘raydi.',
    ),
    body: html`${head}${before}${message}${does}${stops}${file}`,
    context,
  });
}
