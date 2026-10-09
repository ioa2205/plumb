// @ts-check
// Where the message form lands when scripts are off and the message was passed on.
import { page } from '../components/layout.mjs';
import { html } from '../lib/html.mjs';
import { t } from '../lib/lang.mjs';

export const path = '/contact/sent';
/** Kept out of the sitemap. */
export const listed = false;

/** @param {import('../components/layout.mjs').PageContext} context */
export function render(context) {
  return page({
    path,
    title: t('Message sent', 'Xabar yuborildi'),
    description: t(
      'Your message about Plumb was passed on. This page confirms it and links back to the rest of the site.',
      'Plumb haqidagi xabaringiz yetkazildi. Bu sahifa buni tasdiqlaydi va saytning qolgan qismiga qaytaradi.',
    ),
    index: false,
    body: html`<header class="page-head">
  <div class="wrap">
    <h1>${t('Message sent.', 'Xabar yuborildi.')}</h1>
    <p class="lede">${t(
      'Thank you. If you left a way to reply, I will write back.',
      'Rahmat. Javob uchun manzil qoldirgan bo‘lsangiz, javob yozaman.',
    )}</p>
    <p class="actions"><a class="btn btn-ink" href="/">${t('Go to the overview', 'Bosh sahifaga o‘tish')}</a><a class="btn" href="/contact">${t('Back to contact', 'Aloqa sahifasiga qaytish')}</a></p>
  </div>
</header>`,
    context,
  });
}
