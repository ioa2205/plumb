// @ts-check
// Where the message form lands when scripts are off and the message could not be passed on.
import { page } from '../components/layout.mjs';
import { html } from '../lib/html.mjs';
import { t } from '../lib/lang.mjs';

export const path = '/contact/not-sent';
/** Kept out of the sitemap. */
export const listed = false;

/** @param {import('../components/layout.mjs').PageContext} context */
export function render(context) {
  return page({
    path,
    title: t('Message not sent', 'Xabar yuborilmadi'),
    description: t(
      'Your message about Plumb could not be passed on. This page says so and links back to the contact page.',
      'Plumb haqidagi xabaringizni yetkazib bo‘lmadi. Bu sahifa shuni bildiradi va aloqa sahifasiga qaytaradi.',
    ),
    index: false,
    body: html`<header class="page-head">
  <div class="wrap">
    <h1>${t('The message was not sent.', 'Xabar yuborilmadi.')}</h1>
    <p class="lede">${t(
      'Nothing was delivered. Go back and try again, or use one of the direct links on the contact page.',
      'Hech narsa yetkazilmadi. Orqaga qaytib, yana urinib ko‘ring yoki aloqa sahifasidagi havolalardan foydalaning.',
    )}</p>
    <p class="actions"><a class="btn btn-ink" href="/contact">${t('Back to contact', 'Aloqa sahifasiga qaytish')}</a></p>
  </div>
</header>`,
    context,
  });
}
