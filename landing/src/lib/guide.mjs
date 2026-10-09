// @ts-check
// How to install and run Plumb from source, written once. The install page shows it to
// people, the agent page turns it into a message for an AI coding agent, and the build writes
// it out as agent-install.md for agents that read web pages. Commands come from the README's
// documented commands and the recorded run; sizes come from the pinned downloads.

import { commandLine, gb, mb, minutes } from './format.mjs';
import { holds } from './holds.mjs';
import { lang, t } from './lang.mjs';

const PACKAGED_LAB = '.\\app\\labs\\tandir';

/**
 * @typedef {object} Step
 * @property {string} id
 * @property {string} title
 * @property {string} detail
 * @property {string} [agent]          the same step, said to an AI agent where it differs
 * @property {string[]} [commands]       one block of lines to type
 * @property {string} [otherwise]        a second case, said before `otherCommands`
 * @property {string[]} [otherCommands]
 * @property {boolean} [measuredOnly]    only on the measured laptop model
 * @property {boolean} [optional]
 */

/** The recorded review, as typed from a source checkout instead of the Windows package. */
export function reviewCommands(/** @type {any} */ run) {
  holds(run.command.includes(PACKAGED_LAB), 'the recorded command reviews the bundled practice app');
  const cacheOption = run.command.indexOf('--guard-cache');
  const args = run.command.filter((/** @type {string} */ _arg, /** @type {number} */ index) => index !== cacheOption && index !== cacheOption + 1);
  return {
    packaged: commandLine(args),
    source: commandLine(
      args.map((/** @type {string} */ arg) => (arg === PACKAGED_LAB ? 'labs/tandir' : arg)),
      'uv run plumb',
    ),
    lab: PACKAGED_LAB,
  };
}

/** The repository's folder name once cloned, such as "plumb". */
export const repositoryFolder = (/** @type {string} */ repository) => repository.replace(/\/$/, '').split('/').pop() ?? '';

/**
 * @param {any} record
 * @param {any} site
 * @returns {{ steps: Step[], downloadBytes: number }}
 */
export function guide(record, site) {
  const { run, model, runtime_download: runtime } = record;
  const review = reviewCommands(run);
  const downloadBytes = model.size + runtime.size;

  /** @type {Step} */
  const code = site.repository
    ? {
        id: 'code',
        title: t('Get the code.', 'Kodni oling.'),
        detail: t('This copies the source into a new folder and moves into it.', 'Bu buyruqlar manba kodini yangi papkaga ko‘chiradi va o‘sha papkaga o‘tadi.'),
        commands: [`git clone ${site.repository}`, `cd ${repositoryFolder(site.repository)}`],
      }
    : {
        id: 'code',
        title: t('Open the folder you were sent.', 'Sizga yuborilgan papkani oching.'),
        agent: 'The code is not public yet. Work in the folder the person gave you; if they have not given one, ask for it.',
        detail: t(
          'The code is not public yet. Unpack the copy you received, then open PowerShell inside that folder. Every command below runs from there.',
          'Kod hali ommaga ochilmagan. Sizga yuborilgan nusxani arxivdan chiqaring va shu papkada PowerShell’ni oching. Quyidagi barcha buyruqlar o‘sha yerdan bajariladi.',
        ),
      };

  /** @type {Step[]} */
  const steps = [
    code,
    {
      id: 'tools',
      title: t('Check the tools.', 'Kerakli dasturlarni tekshiring.'),
      detail: t(
        'Each command prints a version number. Node.js must be version 24 or newer. Plumb’s setup does not install these four, so install any that are missing from their official sites first. Python 3.12 is not on the list because uv fetches it by itself.',
        'Har bir buyruq versiya raqamini chiqaradi. Node.js 24 yoki undan yangi versiya bo‘lishi kerak. Plumb o‘rnatuvchisi bu to‘rt dasturni o‘rnatmaydi, shuning uchun yetishmaganini avval rasmiy saytidan o‘rnating. Python 3.12 ro‘yxatda yo‘q, chunki uni uv o‘zi yuklab oladi.',
      ),
      commands: ['git --version', 'uv --version', 'node --version', 'pnpm --version'],
      agent: 'Each command prints a version number; Node.js must be 24 or newer. If any tool is missing or too old, tell the person which one and stop. Do not install it yourself. Python 3.12 is not on the list because uv fetches it.',
    },
    {
      id: 'environment',
      title: t('Create Plumb’s environment.', 'Plumb muhitini yarating.'),
      detail: t(
        'Installs Plumb’s own Python packages inside its folder, at exactly the versions it was tested with.',
        'Plumbning Python paketlarini uning o‘z papkasiga, aynan sinovdan o‘tgan versiyalarda o‘rnatadi.',
      ),
      commands: ['uv sync --locked'],
    },
    {
      id: 'preview',
      title: t('Preview the setup.', 'O‘rnatishni oldindan ko‘ring.'),
      detail: t(
        'Lists what is ready and what is missing, with the size, source and licence of each download, and says whether this computer has a measured profile. It installs nothing.',
        'Nima tayyor va nima yetishmasligini, har bir yuklanadigan faylning hajmi, manbasi va litsenziyasini ko‘rsatadi hamda bu kompyuter uchun o‘lchangan profil bor-yo‘qligini aytadi. Hech narsa o‘rnatmaydi.',
      ),
      commands: ['uv run --locked plumb setup'],
    },
    {
      id: 'install',
      title: t('Install.', 'O‘rnating.'),
      detail: t(
        `On the measured laptop model this downloads the AI model (${gb(model.size)}) and the program that runs it (${mb(runtime.size)}). The last option is your approval: setup asks for it whenever the downloads add up to more than 500 MB.`,
        `O‘lchangan noutbuk modelida bu buyruq SI modelini (${gb(model.size)}) va uni ishga tushiradigan dasturni (${mb(runtime.size)}) yuklab oladi. Oxirgi parametr sizning roziligingizni bildiradi: yuklanadigan fayllar jami 500 MB dan oshsa, o‘rnatuvchi shuni talab qiladi.`,
      ),
      commands: ['uv run --locked plumb setup --install --approve-large-downloads'],
      agent: `Only if the preview names a measured profile. Show the person the downloads the preview listed (the model, ${gb(model.size)}, and the program that runs it, ${mb(runtime.size)}), and run this only after they agree. The last option records their approval; setup refuses downloads over 500 MB without it.`,
      otherwise: t(
        'On any other computer, install only what mapping needs. Setup refuses the full installation there, because no measured profile exists for that hardware.',
        'Boshqa har qanday kompyuterda faqat xarita tuzish uchun keraklisini o‘rnating. U yerda to‘liq o‘rnatishni o‘rnatuvchining o‘zi rad etadi, chunki bunday qurilma uchun o‘lchangan profil yo‘q.',
      ),
      otherCommands: ['uv run --locked plumb setup --install --inspect-only'],
    },
    {
      id: 'inspect',
      title: t('Map the practice app.', 'Sinov ilovasining xaritasini tuzing.'),
      detail: t(
        'Loads no model. Prints the files, frameworks and addresses Plumb found in the bundled practice app, and saves an overview.',
        'Model yuklanmaydi. Plumb ilova bilan birga kelgan sinov ilovasida topgan fayllar, freymvorklar va manzillarni chiqaradi hamda umumiy ko‘rinishni saqlaydi.',
      ),
      commands: ['uv run plumb inspect labs/tandir'],
    },
    {
      id: 'doctor',
      title: t('Check the machine.', 'Kompyuterni tekshiring.'),
      detail: t(
        'Reads the hardware, the installed files and the free memory, and changes nothing. If it says memory is short, close other programs and run it again.',
        'Qurilma, o‘rnatilgan fayllar va bo‘sh xotirani o‘qiydi, hech narsani o‘zgartirmaydi. Xotira yetmayotganini aytsa, boshqa dasturlarni yopib, qaytadan ishga tushiring.',
      ),
      commands: ['uv run plumb doctor'],
    },
    {
      id: 'review',
      title: t('Run the recorded review.', 'Yozib olingan tekshiruvni takrorlang.'),
      detail: t(
        `Only on the measured laptop model. It asks the AI model about the receipt and the invoice of the practice app and prints a run ID at the end. The recorded run took ${minutes(run.elapsed_seconds)}.`,
        `Faqat o‘lchangan noutbuk modelida. U SI modelidan sinov ilovasidagi chek va hisob-faktura haqida so‘raydi va oxirida tekshiruv identifikatorini chiqaradi. Yozib olingan sinov ${minutes(run.elapsed_seconds)} davom etgan.`,
      ),
      commands: [review.source],
      measuredOnly: true,
    },
    {
      id: 'report',
      title: t('Open the report.', 'Hisobotni oching.'),
      detail: t(
        'Put the run ID that was printed in place of <run-id>. The saved report opens in your browser. No model is loaded.',
        '<run-id> o‘rniga chiqarilgan identifikatorni yozing. Saqlangan hisobot brauzeringizda ochiladi. Model yuklanmaydi.',
      ),
      commands: ['uv run plumb report <run-id> --open'],
      measuredOnly: true,
    },
    {
      id: 'web',
      title: t('Optional: the browser view.', 'Ixtiyoriy: brauzerdagi interfeys.'),
      detail: t(
        'The same saved results in a browser window. From source it has to be built once first. It starts no model. Its final round of browser checks is still pending.',
        'Xuddi shu saqlangan natijalar brauzer oynasida. Manba kodidan ishlatilganda uni avval bir marta yig‘ib olish kerak. Model ishga tushmaydi. Brauzerdagi yakuniy tekshiruvlari hali tugallanmagan.',
      ),
      commands: ['pnpm --dir frontend install --frozen-lockfile --ignore-scripts', 'pnpm --dir frontend build', 'uv run plumb web'],
      optional: true,
    },
  ];
  return { steps, downloadBytes };
}

/** What Plumb says when it refuses, and what to do. Shared by the install page and the agent file. */
export function refusals() {
  return [
    {
      says: t('Files are missing or unverified', 'Fayllar yetishmaydi yoki tasdiqlanmagan'),
      action: t('Read the setup preview and install only the pinned files it lists.', 'O‘rnatishni oldindan ko‘ring va faqat u ko‘rsatgan, oldindan belgilangan fayllarni o‘rnating.'),
    },
    {
      says: t('No measured hardware profile', 'O‘lchangan qurilma profili yo‘q'),
      action: t(
        'Use inspect and saved reports. A review with the model needs a measured profile for this machine.',
        'inspect buyrug‘i va saqlangan hisobotlardan foydalaning. Model bilan tekshiruv uchun aynan shu kompyuterning o‘lchangan profili kerak.',
      ),
    },
    {
      says: t('Not enough RAM or graphics memory', 'Operativ xotira yoki videoxotira yetarli emas'),
      action: t(
        'Close other programs, run doctor again, then retry or resume. The threshold stays where it is.',
        'Boshqa dasturlarni yoping, doctor buyrug‘ini qayta ishga tushiring, so‘ng yana urinib ko‘ring yoki tekshiruvni davom ettiring. Talab qilinadigan xotira kamaytirilmaydi.',
      ),
    },
    {
      says: t('Not enough free disk space', 'Diskda bo‘sh joy yetarli emas'),
      action: t('Free space for the downloads the preview lists, then run setup again. Nothing was installed.', 'Oldindan ko‘rishda ko‘rsatilgan fayllar uchun joy bo‘shating va o‘rnatishni qayta boshlang. Hech narsa o‘rnatilmagan.'),
    },
    {
      says: t('No supported checks match', 'Mos keladigan tekshiruv topilmadi'),
      action: t(
        'Read the overview to see what Plumb recognised. An empty selection is not a safety verdict.',
        'Plumb nimani taniganini bilish uchun umumiy ko‘rinishni o‘qing. Bo‘sh natija «xavfsiz» degani emas.',
      ),
    },
    {
      says: t('A saved report is refused', 'Saqlangan hisobot ochilmadi'),
      action: t(
        'The file was changed, or was written by an older version. Keep it as it is and open it with the version that wrote it.',
        'Fayl o‘zgartirilgan yoki eskiroq versiyada yozilgan. Uni o‘zgartirmasdan saqlang va uni yozgan versiya bilan oching.',
      ),
    },
  ];
}

/** Rules an agent follows while installing. The same list is in the message and the file. */
export const AGENT_RULES = [
  'Never use administrator rights, and never change system settings, drivers or Windows features.',
  'Never run, install or import code from a project that Plumb reviews. Plumb only reads it, and so do you.',
  'Do not install Git, uv, Node.js or pnpm without asking me first.',
  'Keep Plumb’s data folder outside the Plumb folder and outside any project it reviews. The default location is correct.',
  'Ask me before any download larger than 500 MB.',
  'If a command fails or Plumb refuses, show me the exact message and stop. Do not work around a refusal or lower a limit.',
  'Do not start a review with the AI model unless I ask for one.',
];

/** The same rules, as the instructions file states them: about the person, not to them. */
export const AGENT_RULES_FOR_FILE = AGENT_RULES.map((rule) => rule.replace(/\bme\b/g, 'the person').replace(/\bI ask\b/g, 'the person asks'));

/**
 * The message a person pastes into an AI coding agent. It is in English, which coding agents
 * follow most reliably; on the Uzbek page it asks the agent to explain in Uzbek.
 * @param {any} record @param {any} site
 */
export function agentMessage(record, site) {
  const { run } = record;
  holds(run.machine.cpu.includes('i5-1135G7') && run.machine.gpu.includes('MX350'), 'the measured profile is the i5-1135G7 with MX350 graphics');
  const lines = [
    'Install Plumb on this Windows computer and run its first checks. Plumb is a local security reviewer that reads source code with a small offline AI model.',
    ...(site.url ? ['', `Full instructions for agents: ${site.url}/agent-install.md`] : []),
    '',
    'Steps:',
    site.repository
      ? `1. Clone ${site.repository} into a new folder and work inside it.`
      : '1. The Plumb source code is in this folder: <PASTE THE FOLDER PATH HERE>. Work inside it.',
    '2. Check that git, uv, Node.js 24 or newer, and pnpm are installed (run each with --version). If any is missing, tell me what to install and stop.',
    '3. Run: uv sync --locked',
    '4. Run: uv run --locked plumb setup',
    '   This only previews. Summarise it for me.',
    '5. If the preview says this hardware has no measured review profile, run:',
    '   uv run --locked plumb setup --install --inspect-only',
    '   Otherwise, list the downloads it shows (size, source, licence) and ask me before running:',
    '   uv run --locked plumb setup --install --approve-large-downloads',
    '6. Run: uv run plumb inspect labs/tandir',
    '7. Run: uv run plumb doctor',
    '8. Tell me in plain words what worked, what did not, and whether this computer can run a full review with the AI model.',
    '',
    'Rules:',
    ...AGENT_RULES.map((rule) => `- ${rule}`),
    ...(lang() === 'uz' ? ['- Explain everything to me in Uzbek.'] : []),
  ];
  return lines.join('\n');
}

/**
 * The plain instructions file for agents, always in English.
 * @param {any} record @param {any} site
 */
export function agentFile(record, site) {
  const { steps, downloadBytes } = guide(record, site);
  const { run } = record;
  holds(run.machine.cpu.includes('i5-1135G7'), 'the measured profile is the i5-1135G7');
  const fence = (/** @type {string[]} */ commands) => ['```powershell', ...commands, '```'];
  const body = steps.flatMap((step, index) => [
    `### ${index + 1}. ${step.title.replace(/\.$/, '')}${step.measuredOnly ? ' (measured laptop only)' : ''}`,
    '',
    step.agent ?? step.detail,
    '',
    ...(step.commands ? [...fence(step.commands), ''] : []),
    ...(step.otherwise ? [step.otherwise, '', ...fence(step.otherCommands ?? []), ''] : []),
  ]);
  const link = (/** @type {string} */ path) => (site.url ? `${site.url}${path}` : path);
  return [
    '# Installing Plumb: instructions for AI coding agents',
    '',
    'Plumb is a local security reviewer. It reads a web app’s source code on this computer with a small offline AI model, and reports places where one user can reach another user’s data, citing the exact lines. It is a working prototype for Windows.',
    '',
    'Work through the steps in order and explain each result to the person in plain words. Stop and ask the person wherever these instructions say so.',
    '',
    '## Rules',
    '',
    ...AGENT_RULES_FOR_FILE.map((rule) => `- ${rule}`),
    '',
    '## Before you start',
    '',
    '- 64-bit Windows, and PowerShell.',
    '- Git, uv, Node.js 24 or newer, and pnpm. Plumb’s setup does not install them. uv provides Python 3.12.',
    `- For a full review: the measured hardware profile \`${run.profile}\` (an Intel Core i5-1135G7 with ${run.machine.gpu} graphics), and ${gb(downloadBytes)} of free disk space for the downloads. On any other computer only source mapping is available, and that path has not yet been tried on a second computer.`,
    site.repository ? `- The code: ${site.repository}` : '- The code: not public yet. The person must give you the folder they received.',
    '',
    '## Steps',
    '',
    ...body,
    '## If Plumb refuses',
    '',
    ...refusals().map((entry) => `- **${entry.says}.** ${entry.action}`),
    '',
    '## What to report at the end',
    '',
    '- Which steps passed and which failed, with the exact message of any failure.',
    '- Whether this computer has a measured review profile, as the setup preview or doctor states it.',
    '- What `inspect` found in the practice app: files, frameworks and addresses.',
    '',
    ...(site.url ? [`More: ${link('/')} · step-by-step page for people: ${link('/install')} · contact: ${link('/contact')}`, ''] : []),
  ].join('\n');
}
