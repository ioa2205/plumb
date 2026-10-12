// @ts-check
import { holds } from './holds.mjs';
import { t } from './lang.mjs';

/** What any other website needs before Plumb may test it, and that none has been tested. @param {any} download */
export function externalLimits(download) {
  holds(download.features.external_testing_enabled === false &&
    download.features.external_scope_and_qualification_required === true &&
    download.external_website_tested === false,
  'external website tests still require qualification and an approved scope and plan');
  return t(
    'Testing another website requires a network boundary check on this computer and your approved scope and plan. No external website has been tested.',
    'Boshqa saytni sinash uchun shu kompyuterda tarmoq chegarasi tekshiruvi hamda siz tasdiqlagan qamrov va reja kerak. Tashqi sayt sinab ko‘rilmagan.',
  );
}

/** The legacy collector and the new scoped adapter have separate boundaries. @param {any} download */
export function websiteLimits(download) {
  return t(
    `The recorded Tandir requests stay on this computer. ${externalLimits(download)}`,
    `Yozib olingan Tandir so‘rovlari faqat shu kompyuterda bajariladi. ${externalLimits(download)}`,
  );
}
