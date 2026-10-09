// @ts-check
import { page } from '../components/layout.mjs';
import { html, raw } from '../lib/html.mjs';
import { lang, t } from '../lib/lang.mjs';
import { LIMITS } from '../../server/message.mjs';

export const path = '/contact';

const arrow = raw('<svg class="arrow" viewBox="0 0 16 16" aria-hidden="true"><path d="M5 11 11 5M6 5h5v5"/></svg>');

/**
 * Contact details are kept in src/data/site.json and are never guessed. A release build
 * refuses to run while the list is empty. The form posts to /api/message, which passes the
 * message on and keeps nothing; without scripts it still works as an ordinary form.
 * @param {import('../components/layout.mjs').PageContext} context
 */
export function render(context) {
  const { site } = context;
  const channels = /** @type {{ label: string, value: string, href?: string }[]} */ (site.contact);
  const optional = html` <span class="optional">${t('optional', 'ixtiyoriy')}</span>`;

  const head = html`<header class="page-head">
  <div class="wrap">
    <h1>${t('Contact', 'Aloqa')}</h1>
    <p class="lede">${site.author
      ? t(html`Plumb is built by ${site.author}.`, html`Plumbni ${site.author} yaratgan.`)
      : t('Plumb is a one-person project.', 'Plumb bir kishilik loyiha.')} ${t(
      'Write with a question, to report a result that looks wrong, or to ask for help getting Plumb running.',
      'Savolingiz bo‘lsa, biror natija noto‘g‘ri tuyulsa yoki Plumbni ishga tushirishda yordam kerak bo‘lsa, yozing.',
    )}</p>
  </div>
</header>`;

  const form = html`<div class="sheet contact-form" id="write">
    <h2 id="write-h">${t('Send a message', 'Xabar yuboring')}</h2>
    <p class="small">${t(
      'It goes straight to my Telegram. You do not need a Telegram account, and you stay on this page.',
      'Xabar to‘g‘ridan-to‘g‘ri mening Telegramimga keladi. Buning uchun Telegram hisobingiz bo‘lishi shart emas va sahifani tark etmaysiz.',
    )}</p>
    <form class="form" method="post" action="/api/message" data-message-form
      data-sending="${t('Sending…', 'Yuborilmoqda…')}"
      data-sent="${t('Message sent. Thank you.', 'Xabar yuborildi. Rahmat.')}"
      data-preview="${t('Preview only: the message reached this computer’s test server and was not passed on to Telegram.', 'Faqat sinov rejimi: xabar shu kompyuterdagi sinov serveriga yetib bordi, lekin Telegramga uzatilmadi.')}"
      data-invalid="${t(`Write between ${LIMITS.messageMin} and ${LIMITS.messageMax} characters.`, `Xabar ${LIMITS.messageMin} dan ${LIMITS.messageMax} tagacha belgidan iborat bo‘lsin.`)}"
      data-limited="${t('Too many messages in a short time. Try again in a few minutes.', 'Qisqa vaqt ichida juda ko‘p xabar yuborildi. Bir necha daqiqadan so‘ng qayta urinib ko‘ring.')}"
      data-unavailable="${t('Messages cannot be sent from this page right now. Use one of the links beside it instead.', 'Hozir bu sahifadan xabar yuborib bo‘lmaydi. Yonidagi havolalardan biridan foydalaning.')}"
      data-failed="${t('The message was not sent. Try again, or use one of the links beside it.', 'Xabar yuborilmadi. Qayta urinib ko‘ring yoki yonidagi havolalardan biridan foydalaning.')}">
      <input type="hidden" name="lang" value="${lang()}">
      <p class="field">
        <label for="f-message">${t('Your message', 'Xabaringiz')}</label>
        <textarea id="f-message" name="message" rows="7" required minlength="${LIMITS.messageMin}" maxlength="${LIMITS.messageMax}"></textarea>
      </p>
      <div class="field-row">
        <p class="field">
          <label for="f-name">${t('Your name', 'Ismingiz')}${optional}</label>
          <input id="f-name" name="name" type="text" maxlength="${LIMITS.name}" autocomplete="name">
        </p>
        <p class="field">
          <label for="f-reply">${t('Where can I reply?', 'Javobni qayerga yozay?')}${optional}</label>
          <input id="f-reply" name="reply" type="text" maxlength="${LIMITS.reply}" autocomplete="email" aria-describedby="f-reply-hint">
        </p>
      </div>
      <p class="small" id="f-reply-hint">${t(
        'An email address, a Telegram name, or anything else I can answer to. Without it I cannot write back.',
        'Elektron pochta, Telegram foydalanuvchi nomi yoki men javob yoza oladigan boshqa manzil. Busiz sizga javob qaytara olmayman.',
      )}</p>
      <p class="hp" aria-hidden="true"><label>${t('Leave this field empty', 'Bu maydonni bo‘sh qoldiring')} <input name="website" type="text" tabindex="-1" autocomplete="off"></label></p>
      <div class="form-foot">
        <p class="form-actions">
          <button class="btn btn-ink" type="submit">${t('Send message', 'Xabarni yuborish')}</button>
          <span class="form-status" role="status" aria-live="polite" data-form-status></span>
        </p>
        <p class="small">${t(
          'Only your message and the two optional fields are sent. The site passes them on and keeps no copy.',
          'Faqat xabaringiz va ikkita ixtiyoriy maydon yuboriladi. Sayt ularni yetkazadi, lekin nusxasini saqlamaydi.',
        )}</p>
      </div>
    </form>
  </div>`;

  const reach = channels.length > 0
    ? html`<ul class="channels" id="reach">
        ${channels.map((channel) =>
          channel.href
            ? html`<li><a class="channel" href="${channel.href}" rel="me noopener"><span class="channel-name">${channel.label}</span><span class="channel-handle">${channel.value}</span>${arrow}</a></li>`
            : html`<li><span class="channel"><span class="channel-name">${channel.label}</span><span class="channel-handle">${channel.value}</span></span></li>`,
        )}
      </ul>`
    : html`<p class="condition" id="reach">${t(
        html`<strong>Contact details have not been added yet.</strong> This page is a preview. The site will not be published until they are in place.`,
        html`<strong>Aloqa ma’lumotlari hali qo‘shilmagan.</strong> Bu sahifa sinov ko‘rinishida. Ular qo‘shilmaguncha sayt e’lon qilinmaydi.`,
      )}</p>`;

  const side = html`<aside class="contact-side" aria-label="${t('Other ways to reach me', 'Bog‘lanishning boshqa yo‘llari')}">
    <h2 id="reach-h">${t('Or write directly', 'Yoki to‘g‘ridan-to‘g‘ri yozing')}</h2>
    ${reach}
    <h2 id="helps-h">${t('What helps in a message', 'Xabarga nimalarni yozish foydali')}</h2>
    <ul class="helps" id="helps">
      ${t(
        html`<li><strong>About a finding.</strong> The run ID and the finding number, for example F-01. Both are printed in every report.</li>
      <li><strong>About a refusal or an error.</strong> The message exactly as Plumb printed it. It names what was missing.</li>
      <li><strong>About your own code.</strong> Please do not send code you are not allowed to share. Describing the address and the check is usually enough.</li>`,
        html`<li><strong>Topilma haqida.</strong> Tekshiruv identifikatori va topilma raqami, masalan F-01. Ikkalasi ham har bir hisobotda ko‘rsatilgan.</li>
      <li><strong>Rad javobi yoki xato haqida.</strong> Plumb chiqargan xabarning aynan o‘zi: unda nima yetishmayotgani aytilgan.</li>
      <li><strong>O‘z kodingiz haqida.</strong> Ulashishga ruxsatingiz bo‘lmagan kodni yubormang. Odatda manzil va tekshiruvni so‘z bilan tasvirlash kifoya.</li>`,
      )}
    </ul>
  </aside>`;

  return page({
    path,
    title: t('Contact', 'Aloqa'),
    description: t(
      'Send a message about Plumb without leaving the site, or write directly on Telegram, LinkedIn or GitHub: ask a question, report a result that looks wrong, or get help running it.',
      'Saytdan chiqmasdan Plumb haqida xabar yuboring yoki Telegram, LinkedIn va GitHub orqali to‘g‘ridan-to‘g‘ri yozing: savol bering, noto‘g‘ri tuyulgan natija haqida yozing yoki ishga tushirishda yordam so‘rang.',
    ),
    body: html`${head}<section class="band band-last contact-band" aria-label="${t('Write to me', 'Menga yozing')}">
  <div class="wrap contact-grid">
    ${form}
    ${side}
  </div>
</section>`,
    context,
  });
}
