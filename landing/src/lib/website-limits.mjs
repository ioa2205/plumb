// @ts-check
import { holds } from './holds.mjs';
import { t } from './lang.mjs';

/** The legacy collector and the new scoped adapter have separate boundaries. @param {any} download */
export function websiteLimits(download) {
  holds(download.features.external_testing_enabled === false &&
    download.features.external_scope_and_qualification_required === true &&
    download.external_website_tested === false,
  'external website tests still require qualification and an approved scope and plan');
  return t(
    'The recorded Tandir requests stay on this computer. Testing another website requires a network boundary check on this computer and your approved scope and plan. No external website has been tested.',
    'Yozib olingan Tandir so‘rovlari faqat shu kompyuterda bajariladi. Boshqa saytni sinash uchun shu kompyuterda tarmoq chegarasi tekshiruvi hamda siz tasdiqlagan qamrov va reja kerak. Tashqi sayt sinab ko‘rilmagan.',
  );
}
