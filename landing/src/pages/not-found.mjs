// @ts-check
import { page } from '../components/layout.mjs';
import { html } from '../lib/html.mjs';

export const path = '/404';
/** Kept out of the sitemap. */
export const listed = false;

/**
 * One page answers for every unknown address in either language, so it carries both.
 * @param {import('../components/layout.mjs').PageContext} context
 */
export function render(context) {
  return page({
    path,
    title: 'Page not found',
    description: 'There is no page at this address. The overview and the test run are linked from here.',
    index: false,
    body: html`<header class="page-head">
  <div class="wrap">
    <h1>There is no page at this address.</h1>
    <p class="lede">The link may be old, or the address may have been mistyped.</p>
    <p class="actions"><a class="btn btn-ink" href="/">Go to the overview</a><a class="btn" href="/recorded-run">See the test run</a></p>
    <p class="lede" lang="uz">Bu manzilda sahifa yo‘q. Havola eskirgan yoki manzil xato yozilgan bo‘lishi mumkin.</p>
    <p class="actions" lang="uz"><a class="btn" hreflang="uz" href="/uz">Bosh sahifaga o‘tish</a></p>
  </div>
</header>`,
    context,
  });
}
