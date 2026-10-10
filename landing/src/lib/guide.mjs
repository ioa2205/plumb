// @ts-check
// How to install and run Plumb, written once. The install page shows the steps to people,
// from source and with the Windows package; the agent page turns the source steps into a
// message for an AI coding agent, and the build writes them out as agent-install.md for agents
// that read web pages. Commands come from the README's documented commands and the recorded
// run; sizes come from the pinned downloads.

import { commandLine, gb, mb, minutes } from './format.mjs';
import { holds } from './holds.mjs';
import { lang, t } from './lang.mjs';

const PACKAGED_LAB = '.\\app\\labs\\tandir';
const SOURCE_LAB = 'labs/tandir';

/**
 * @typedef {object} Step
 * @property {string} id
 * @property {string} title
 * @property {string} detail
 * @property {string} [agent]          the same step, said to an AI agent where it differs
 * @property {string[]} [commands]       one block of lines to type
 * @property {string} [otherwise]        a second case, said before `otherCommands`
 * @property {string} [agentOtherwise]   that second case, said to an AI agent where it differs
 * @property {string[]} [otherCommands]
 * @property {boolean} [optional]
 */

/**
 * The recorded review, as the Windows package types it and as a source checkout types it.
 * The recorded command named the one profile that existed then. Both forms leave the option
 * out now, so Plumb picks the profile that fits the computer it is on.
 */
export function reviewCommands(/** @type {any} */ run) {
  holds(run.command.includes(PACKAGED_LAB), 'the recorded command reviews the bundled practice app');
  holds(run.command[run.command.indexOf('--profile') + 1] === run.profile, 'the recorded command names its profile');
  const without = (/** @type {string[]} */ args, /** @type {string} */ option) => {
    const at = args.indexOf(option);
    return at < 0 ? args : args.filter((_arg, index) => index !== at && index !== at + 1);
  };
  const args = without(without(run.command, '--guard-cache'), '--profile');
  return {
    packaged: commandLine(args),
    source: commandLine(args.map((/** @type {string} */ arg) => (arg === PACKAGED_LAB ? SOURCE_LAB : arg)), 'uv run plumb'),
    lab: PACKAGED_LAB,
  };
}

/** A source command as the Windows package types it: its own launcher and its bundled practice app. */
const packaged = (/** @type {string} */ line) =>
  line.replace(/^uv run (?:--locked )?plumb(?= )/, '.\\plumb.cmd').replace(SOURCE_LAB, PACKAGED_LAB);

/** The source steps that the Windows package repeats. The rest fetch the code and its tools, which the package carries. */
const PACKAGE_STEPS = ['preview', 'install', 'inspect', 'doctor', 'calibrate', 'review', 'report'];

/**
 * What setup downloads, in bytes: the AI model, the program that runs it for the chosen
 * profile, and the pattern scanner. It is the same for the Windows package and from source.
 * @param {any} record
 */
export function downloadSizes(record) {
  const { model, runtime_download: measuredRuntime, cpu_runtime_download: cpuRuntime, scanner_download: scanner } = record;
  return {
    cpu: model.size + cpuRuntime.size + scanner.size,
    measured: model.size + measuredRuntime.size + scanner.size,
  };
}

/** The repository's folder name once cloned, such as "plumb". */
export const repositoryFolder = (/** @type {string} */ repository) => repository.replace(/\/$/, '').split('/').pop() ?? '';

/**
 * @param {any} record
 * @param {any} site
 * @returns {{ steps: Step[], packageSteps: Step[], downloads: ReturnType<typeof downloadSizes> }}
 */
export function guide(record, site) {
  const { run, model, runtime_download: runtime, cpu_runtime_download: cpuRuntime, scanner_download: scanner, cpu_profile: cpu, download } = record;
  const review = reviewCommands(run);
  const check = cpu.first_use_check;
  holds(cpu.id === 'cpu-8k' && run.profile === 'mx350-vulkan-8k', 'the two profiles are mx350-vulkan-8k and cpu-8k');
  holds(check.answers === 3 && check.leak_pairs === 10, 'the first-use check asks three questions and sends ten pairs of requests');
  holds(
    download.investigator_same_as_source && download.source_files_checked > 0 && download.has_cpu_profile && download.has_calibrate_command && download.knows_pattern_scanner,
    'the Windows package takes the same steps as the source, with its own launcher',
  );

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
        'Lists what is ready and what is missing, with the size, source and licence of each download, and names the review profile this computer would use. It installs nothing.',
        'Nima tayyor va nima yetishmasligini, har bir yuklanadigan faylning hajmi, manbasi va litsenziyasini ko‘rsatadi hamda bu kompyuterda qaysi tekshiruv profili ishlatilishini aytadi. Hech narsa o‘rnatmaydi.',
      ),
      commands: ['uv run --locked plumb setup'],
    },
    {
      id: 'install',
      title: t('Install.', 'O‘rnating.'),
      detail: t(
        `Downloads the AI model (${gb(model.size)}), the program that runs it (${mb(cpuRuntime.size)}, or ${mb(runtime.size)} on the measured laptop model) and the pattern scanner (${mb(scanner.size)}), which helps Plumb decide which questions to ask first. The last option is your approval: setup asks for it whenever the downloads add up to more than 500 MB.`,
        `SI modelini (${gb(model.size)}), uni ishga tushiradigan dasturni (${mb(cpuRuntime.size)}, o‘lchangan noutbuk modelida ${mb(runtime.size)}) va andoza skanerini (${mb(scanner.size)}) yuklab oladi. Skaner Plumbga qaysi savolni birinchi berishni tanlashda yordam beradi. Oxirgi parametr sizning roziligingizni bildiradi: yuklanadigan fayllar jami 500 MB dan oshsa, o‘rnatuvchi shuni talab qiladi.`,
      ),
      commands: ['uv run --locked plumb setup --install --approve-large-downloads'],
      agent: `Show the person the downloads the preview listed (the AI model, ${gb(model.size)}; the program that runs it, ${mb(cpuRuntime.size)} or ${mb(runtime.size)} depending on the profile; the pattern scanner, ${mb(scanner.size)}), and run this only after they agree. The last option records their approval; setup refuses downloads over 500 MB without it.`,
      otherwise: t(
        'If you only want to map projects, with no AI model and no large download, install just what mapping needs instead.',
        'Faqat loyiha xaritasini tuzmoqchi bo‘lsangiz, buning o‘rniga faqat xarita uchun keraklisini o‘rnating: SI modeli ham, katta fayllar ham yuklanmaydi.',
      ),
      agentOtherwise: 'If the person does not agree to the downloads, or the preview says AI review is not available on this system, install only what mapping needs instead. It downloads no AI model.',
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
        'Reads the hardware, the installed files and the free memory, and changes nothing. It names the profile this computer would use and says whether enough memory is free for it. It also names the default AI model and the largest one that fits in the memory free right now. If memory is short, close other programs and run it again.',
        'Qurilma, o‘rnatilgan fayllar va bo‘sh xotirani o‘qiydi, hech narsani o‘zgartirmaydi. Bu kompyuterda qaysi profil ishlatilishini va unga xotira yetish-yetmasligini aytadi. Shuningdek asosiy SI modelini va hozir bo‘sh turgan xotiraga sig‘adigan eng katta modelni ko‘rsatadi. Xotira yetmasa, boshqa dasturlarni yopib, qaytadan ishga tushiring.',
      ),
      commands: ['uv run plumb doctor'],
    },
    {
      id: 'calibrate',
      title: t('Optional: check the program that runs the model.', 'Ixtiyoriy: modelni ishga tushiradigan dasturni sinab ko‘ring.'),
      detail: t(
        `With the ${cpu.id} profile, the first review on a computer begins with this check by itself, so this command is only for running it ahead of time. It loads the AI model, asks ${check.answers} test questions, and sends ${check.leak_pairs} pairs of requests to make sure nothing from one request shows up in the next. A pass is saved for this computer. It shows that the program works here. It does not grade the model’s answers. On the measured laptop model the measured profile needs no such check, and the command says so.`,
        `${cpu.id} profilida kompyuterdagi birinchi tekshiruv o‘z-o‘zidan shu sinov bilan boshlanadi, shuning uchun bu buyruq sinovni oldindan o‘tkazib olish uchungina kerak. U SI modelini yuklaydi, ${check.answers} ta sinov savoli beradi va bir so‘rovdagi ma’lumot keyingisiga o‘tib qolmasligiga ishonch hosil qilish uchun ${check.leak_pairs} juft so‘rov yuboradi. Sinovdan o‘tilsa, natija shu kompyuter uchun saqlab qo‘yiladi. Sinov dastur shu yerda ishlashini ko‘rsatadi, model javoblarining to‘g‘riligini esa baholamaydi. O‘lchangan noutbuk modelida o‘lchangan profilga bunday sinov kerak emas, buyruqning o‘zi shuni aytadi.`,
      ),
      agent: `Skip this step unless the person asks for it: it loads the AI model. With the ${cpu.id} profile the first review runs the same check by itself (${check.answers} test questions and ${check.leak_pairs} pairs of requests that look for one answer leaking into the next). It shows that the model runner works on this computer; it does not grade the model’s answers.`,
      commands: ['uv run plumb calibrate'],
      optional: true,
    },
    {
      id: 'review',
      title: t('Run the recorded review.', 'Yozib olingan tekshiruvni takrorlang.'),
      detail: t(
        `Asks the AI model about the receipt and the invoice of the practice app and prints a run ID at the end. Plumb picks the profile for this computer: ${run.profile} on the measured laptop model, ${cpu.id} on any other. With ${cpu.id}, the first review on a computer begins with the short check from the step before, unless that check has already passed there. On the measured laptop model the recorded run took ${minutes(run.elapsed_seconds)}. How long it takes on another computer is not known.`,
        `SI modelidan sinov ilovasidagi chek va hisob-faktura haqida so‘raydi va oxirida tekshiruv identifikatorini chiqaradi. Profilni Plumb shu kompyuterga qarab o‘zi tanlaydi: o‘lchangan noutbuk modelida ${run.profile}, boshqa har qanday kompyuterda ${cpu.id}. ${cpu.id} profilida kompyuterdagi birinchi tekshiruv oldingi qadamdagi qisqa sinov bilan boshlanadi; u yerda bu sinovdan allaqachon o‘tilgan bo‘lsa, sinov takrorlanmaydi. O‘lchangan noutbuk modelida yozib olingan sinov ${minutes(run.elapsed_seconds)} davom etgan. Boshqa kompyuterda qancha vaqt ketishi noma’lum.`,
      ),
      agent: `Only if the person asks for a review: it loads the AI model. It asks about the receipt and the invoice of the practice app and prints a run ID at the end. Plumb picks the profile for this computer: ${run.profile} on the measured laptop model, ${cpu.id} on any other. With ${cpu.id}, the first review on a computer begins with the check from the step before, unless that check has already passed there. On the measured laptop model the recorded run took ${minutes(run.elapsed_seconds)}; how long it takes on another computer is not known.`,
      commands: [review.source],
    },
    {
      id: 'report',
      title: t('Open the report.', 'Hisobotni oching.'),
      detail: t(
        'Put the run ID that was printed in place of <run-id>. The saved report opens in your browser. No model is loaded.',
        '<run-id> o‘rniga chiqarilgan identifikatorni yozing. Saqlangan hisobot brauzeringizda ochiladi. Model yuklanmaydi.',
      ),
      commands: ['uv run plumb report <run-id> --open'],
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
  const packageSteps = steps
    .filter((step) => PACKAGE_STEPS.includes(step.id))
    .map((step) => ({ ...step, commands: step.commands?.map(packaged), otherCommands: step.otherCommands?.map(packaged) }));
  holds(
    packageSteps.find((step) => step.id === 'review')?.commands?.[0] === review.packaged,
    'the package review command is the recorded one, with the profile left for Plumb to pick',
  );
  return { steps, packageSteps, downloads: downloadSizes(record) };
}

/** What Plumb says when it refuses, and what to do. Shared by the install page and the agent file. */
export function refusals() {
  return [
    {
      says: t('Files are missing or unverified', 'Fayllar yetishmaydi yoki tasdiqlanmagan'),
      action: t('Read the setup preview and install only the pinned files it lists.', 'O‘rnatishni oldindan ko‘ring va faqat u ko‘rsatgan, oldindan belgilangan fayllarni o‘rnating.'),
    },
    {
      says: t('No review profile for this computer', 'Bu kompyuter uchun tekshiruv profili yo‘q'),
      action: t(
        'A review with the AI model needs 64-bit Windows on an Intel or AMD processor. On any other system, install with the --inspect-only option instead: mapping with inspect and saved reports work without a profile.',
        'SI modeli bilan tekshiruv uchun Intel yoki AMD protsessorli kompyuterda 64 bitli Windows kerak. Boshqa tizimlarda buning o‘rniga --inspect-only parametri bilan o‘rnating: inspect buyrug‘i va saqlangan hisobotlar profilsiz ham ishlaydi.',
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
      says: t('The program that runs the model failed its first-use check', 'Modelni ishga tushiradigan dastur dastlabki sinovdan o‘tmadi'),
      action: t(
        'Reviews with that profile stay off on this computer until the check passes. Run calibrate to try again. Mapping and saved reports still work.',
        'Sinovdan o‘tmaguncha shu kompyuterda bu profil bilan tekshiruv o‘chiq turadi. Qayta urinish uchun calibrate buyrug‘ini ishga tushiring. Xarita tuzish va saqlangan hisobotlar avvalgidek ishlaydi.',
      ),
    },
    {
      says: t('Not enough free disk space', 'Diskda bo‘sh joy yetarli emas'),
      action: t('Free space for the downloads the preview lists, then run setup again. Nothing was installed.', 'Oldindan ko‘rishda ko‘rsatilgan fayllar uchun joy bo‘shating va o‘rnatishni qayta boshlang. Hech narsa o‘rnatilmagan.'),
    },
    {
      says: t('No supported checks match', 'Mos keladigan tekshiruv topilmadi'),
      action: t(
        'Plumb names the kinds of check your project does have and the exact option to use, for example --family nextjs_exposure for a project with only Next.js code. If it names none, read the overview to see what it recognised. An empty selection is not a safety verdict.',
        'Plumb loyihangizda qaysi turdagi tekshiruvlar borligini va aynan qaysi parametrni yozish kerakligini aytadi, masalan faqat Next.js kodi bor loyiha uchun --family nextjs_exposure. Hech birini aytmasa, Plumb nimani taniganini bilish uchun umumiy ko‘rinishni o‘qing. Bo‘sh natija «xavfsiz» degani emas.',
      ),
    },
    {
      says: t('A saved report is refused', 'Saqlangan hisobot ochilmadi'),
      action: t(
        'The file was changed, or was written by an older version. Keep it as it is and open it with the version that wrote it.',
        'Fayl o‘zgartirilgan yoki eskiroq versiyada yozilgan. Uni o‘zgartirmasdan saqlang va uni yozgan versiya bilan oching.',
      ),
    },
    {
      says: t('This system is not supported yet', 'Bu tizim hozircha qo‘llab-quvvatlanmaydi'),
      action: t(
        'Plumb runs on 64-bit Windows 10 or 11 only for now. From source, every command on macOS or Linux prints this one sentence and stops.',
        'Plumb hozircha faqat 64 bitli Windows 10 yoki 11 da ishlaydi. Manba kodidan o‘rnatilgan bo‘lsa, macOS yoki Linuxda har bir buyruq shu bitta jumlani chiqarib, to‘xtaydi.',
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
  'Do not start a review with the AI model, or run plumb calibrate, unless I ask: both load the model.',
];

/** The same rules, as the instructions file states them: about the person, not to them. */
export const AGENT_RULES_FOR_FILE = AGENT_RULES.map((rule) => rule.replace(/\bme\b/g, 'the person').replace(/\bI ask\b/g, 'the person asks'));

/**
 * The message a person pastes into an AI coding agent. It is in English, which coding agents
 * follow most reliably; on the Uzbek page it asks the agent to explain in Uzbek.
 * @param {any} record @param {any} site
 */
export function agentMessage(record, site) {
  holds(record.cpu_profile.review.lifecycle === 'completed', 'a review can start through a second profile on other 64-bit Windows computers');
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
    '   This only previews. Tell me which review profile it names for this computer, and list the downloads it shows (size, source, licence).',
    '5. Ask me before running:',
    '   uv run --locked plumb setup --install --approve-large-downloads',
    '   If I say no, or the preview says AI review is not available on this system, run this instead. It downloads no AI model:',
    '   uv run --locked plumb setup --install --inspect-only',
    '6. Run: uv run plumb inspect labs/tandir',
    '7. Run: uv run plumb doctor',
    '8. Tell me in plain words what worked, what did not, which profile doctor names, and whether enough memory is free for a full review with the AI model.',
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
  const { steps, downloads } = guide(record, site);
  const { run, cpu_profile: cpu } = record;
  holds(run.machine.cpu.includes('i5-1135G7'), 'the measured profile is the i5-1135G7');
  holds(cpu.review.lifecycle === 'completed' && cpu.same_computer_as_recorded_run, 'cpu-8k has completed one real run, on the development laptop');
  const fence = (/** @type {string[]} */ commands) => ['```powershell', ...commands, '```'];
  const body = steps.flatMap((step, index) => [
    `### ${index + 1}. ${step.title.replace(/\.$/, '')}`,
    '',
    step.agent ?? step.detail,
    '',
    ...(step.commands ? [...fence(step.commands), ''] : []),
    ...(step.otherwise ? [step.agentOtherwise ?? step.otherwise, '', ...fence(step.otherCommands ?? []), ''] : []),
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
    '- Windows 10 or 11, 64-bit, and PowerShell. On macOS or Linux every `plumb` command prints one sentence saying the system is not supported yet, and stops.',
    '- Git, uv, Node.js 24 or newer, and pnpm. Plumb’s setup does not install them. uv provides Python 3.12.',
    `- For a full review: ${gb(Math.max(downloads.cpu, downloads.measured))} of free disk space for the downloads, and enough free memory for the profile Plumb picks. That is \`${run.profile}\` on an Intel Core i5-1135G7 laptop with ${run.machine.gpu} graphics, and \`${cpu.id}\` on any other 64-bit Windows computer with an x64 processor: the same AI model on the processor alone, needing ${gb(cpu.required_ram_bytes)} of free RAM. \`${cpu.id}\` has completed one real run, on the laptop Plumb is developed on. It has not been tried on a second computer, and how fast it is there is not known.`,
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
    '- Which review profile the setup preview or doctor names for this computer, and whether doctor says enough memory is free for it.',
    '- What `inspect` found in the practice app: files, frameworks and addresses.',
    '',
    ...(site.url ? [`More: ${link('/')} · step-by-step page for people: ${link('/install')} · contact: ${link('/contact')}`, ''] : []),
  ].join('\n');
}
