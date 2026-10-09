# Plumb review

Run: review-ee4171c3eebb409292621ba112eabc63; type: live; lifecycle: completed

Project: tandir; snapshot: 3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39

Created: 2026-10-08T15:50:40\.922283\+00:00

Coverage: 2 completed, 0 pending, 85 excluded, 0 unsupported, 87 total\.

Model: \{"id":"qwen3\.5-2b-q4\_k\_m","file\_sha256":"57a1085840f497d764a7fc5d346922dbde961efb54cc792ea81d694fd846a1d8","quantization":"Q4\_K\_M"\}

Toolchain: \{"llama\_cpp\_release":"v0\.5\.0","llama\_cpp\_build":"b11146","backend":"vulkan","opengrep\_version":"v1\.30\.0","opengrep\_rules\_sha256":"259cea250bd99049ed072dbcd648f0e41e204c090c80cae2a22f3bbac22da4c0","knowledge\_pack\_date":null\}

Started: 2026-10-08T15:50:46\.658283\+00:00

Finished: 2026-10-08T16:05:16\.566292\+00:00

## Limitations

Static support does not establish runtime reproduction\.

Only included snapshot files were reviewed; excluded and unsupported scope remains outside the review\.

Valid citations establish grounding, not the correctness of a security judgment\.

Exports omit source text\. Redaction covers known credential shapes and supplied secret values, not arbitrary secrets\.

Only selected families and recognized source forms are investigated\. Unsupported flows remain explicit gaps\.

Python resolution uses the static import fallback\. Dynamic dispatch and unsupported guards remain gaps\.

No target code was executed\. Runtime verification is unavailable; source-based severity does not establish runtime impact\.

Coverage counts discovered access sites, not every possible vulnerability or source file\.

Peer analysis covers the selected resources; excluded resources cannot establish their policies\.

Queue peer checks reuse validated exact-source/profile summaries only; uncached guards stay unknown until investigation\.

Opengrep supplied 15 cited pattern leads; 1 overlap the selected supported questions\. Other matches are not investigated by this queue\. Pattern matches are not findings\.

Supplementary observations are not challenged findings and do not affect coverage\.

Credential shapes may be placeholders; values are omitted and are not validated remotely\.

Configuration flags do not establish deployment exposure or exploitability\.

Advisory matches describe exact lockfile version exposure, not runtime exploitability\.

The dated advisory pack is a small curated subset, not a complete vulnerability database\.

Only npm package-lock/npm-shrinkwrap v2/v3 and uv\.lock v1 registry packages are supported\. pnpm, Yarn, requirements ranges, Git/path/workspace packages and other ecosystems are unknown\.

Lockfile citations cover the parsed file; no package scripts, imports or installs are run\.

0 known secret files were excluded from the snapshot and were not opened\.

Included unsupported lockfiles were not advisory-matched; dependency scope remains incomplete\.

fixed/api\.patch: excluded \(unsupported\)\.

fixed/web\.patch: excluded \(unsupported\)\.

F-01: Bounded static analysis; runtime verification not attempted

F-01: Runtime reachability is not established by static mounting

F-02: Bounded static analysis; runtime verification not attempted

F-02: Runtime reachability is not established by static mounting

## Capability accounting

Investigated requires passing evaluation slices for this engine, model and framework\. Current engine acceptance is unrun\. Historical scoped successes and broader misses below are retained; software fixtures, installed assets and parsing do not prove model accuracy\.

python \(language\): Parsed observed \(20/20\); Indexed partial \(18/20\); Investigated unverified; Runtime-testable unavailable\. Included source observations only\. Extraction/resolution gaps remain; no current model evaluation qualifies the framework or language as Investigated\.

typescript \(language\): Parsed observed \(12/12\); Indexed observed \(12/12\); Investigated unverified; Runtime-testable unavailable\. Included source observations only\. Extraction/resolution gaps remain; no current model evaluation qualifies the framework or language as Investigated\.

tsx \(language\): Parsed observed \(11/11\); Indexed observed \(11/11\); Investigated unverified; Runtime-testable unavailable\. Included source observations only\. Extraction/resolution gaps remain; no current model evaluation qualifies the framework or language as Investigated\.

javascript \(language\): Parsed unverified \(0/0\); Indexed unverified \(0/0\); Investigated unverified; Runtime-testable unavailable\. Included source observations only\. Extraction/resolution gaps remain; no current model evaluation qualifies the framework or language as Investigated\.

fastapi \(framework\): Parsed observed \(26/26\); Indexed observed \(26/26\); Investigated unverified; Runtime-testable unavailable\. Included source observations only\. Extraction/resolution gaps remain; no current model evaluation qualifies the framework or language as Investigated\.

nextjs \(framework\): Parsed observed \(13/13\); Indexed observed \(13/13\); Investigated unverified; Runtime-testable unavailable\. Included source observations only\. Extraction/resolution gaps remain; no current model evaluation qualifies the framework or language as Investigated\.

authorization \(family\): Parsed not\_applicable; Indexed not\_applicable; Investigated unverified; Runtime-testable unavailable\. Bounded software workflow exists\. Its current real-model development gate is open; historical receipt/invoice success does not qualify the full family\.

injection \(family\): Parsed not\_applicable; Indexed not\_applicable; Investigated unverified; Runtime-testable unavailable\. Bounded software workflow exists\. Its current real-model development gate is open; historical receipt/invoice success does not qualify the full family\.

path\_traversal \(family\): Parsed not\_applicable; Indexed not\_applicable; Investigated unverified; Runtime-testable unavailable\. Bounded software workflow exists\. Its current real-model development gate is open; historical receipt/invoice success does not qualify the full family\.

nextjs\_exposure \(family\): Parsed not\_applicable; Indexed not\_applicable; Investigated unverified; Runtime-testable unavailable\. Bounded software workflow exists\. Its current real-model development gate is open; historical receipt/invoice success does not qualify the full family\.

General runtime-testable support is unavailable: no isolated backend has passed acceptance \(ADR-0017\)\. The separate hash-pinned bundled Tandir receipt/invoice exception has recorded runtime proof; it permits no arbitrary source or proposed diff execution\.

Historical evidence: docs/results/2026-10-05-142716-m3\.6-challenge\.json \(SHA256 f33660549900ddbc713ddff4b3dccb9ea76090259854baacd7ba012d9b0e7e9a\)\. Historical FastAPI authorization slice: receipt Supported and invoice Rejected\. Predates the current engine; no general family qualification\.

Historical evidence: docs/results/2026-10-05-170400-m3\.10-families\.json \(SHA256 6186a63db7041d0fc62033f02c9847d979fd56ad46c873594aa4d3b11143cce8\)\. Historical remaining-family run records mostly Inconclusive judgments and an unmet breadth gate\. Software repairs need fresh acceptance\.

Historical evidence: docs/results/2026-10-05-m4\.2-receipt\.json \(SHA256 5c9be0fcdddf9b7ddd8e3a6bb75cb0cfa0fc9df728e74f262bd0984c6188c0ee\)\. Historical actual pinned bundled receipt attack and owner control\. This exception is not arbitrary-code isolation\.

Historical evidence: docs/results/2026-10-05-m4\.2-invoice\.json \(SHA256 092ee3b2dc249ed520257b1684819dcaff314ae98949b3b72074525671915f3e\)\. Historical actual pinned bundled invoice denial with owner control\. This exception is not general runtime-testable support\.

Historical evidence: docs/decisions/ADR-0017-unavailable-isolated-runners\.md \(SHA256 82755e14d83e73d9d1cd97beefca5922bd89f4096cc9920c0f76ca4fca5c4f7a\)\. Current environment decision: no available isolated backend; general replay and isolation acceptance remain blocked\.

## Supplementary security signals

6 observations; status partial; separate from findings and coverage\. Exposure is not exploitability\.

Rule version supplementary-signals-1; advisory date 2026-10-07; source GitHub Advisory Database; pack SHA256 dbd50ca6e8506a8505bbd84689e206aca2ca96cbb285ea2688adad884ba8c74e

\{"id":"signal:cd573b20db266674a157ebaa12386c57","category":"secret","status":"observed","source":\{"snapshot\_id":"3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39","path":"api/tandir/schemas\.py","start\_line":8,"end\_line":8,"content\_sha256":"9d49eb734c7e15739d5db10673e947011f982185425823d29c0c5180b478aa9e"\},"rule\_id":"secret-credential-assignment","rule\_version":"supplementary-signals-1","summary":"Credential-shaped text detected: \[REDACTED\]\.","fingerprint":"0518d244e809b208cd001a8db3eaae30508558bb5515859d18c32f4d3db03ad7","ecosystem":null,"package":null,"version":null,"advisory\_id":null,"limitations":\["Observation only; no challenge or runtime verification was performed\."\]\}

\{"id":"signal:7446538f9466f1ea8681dd0edfad3c21","category":"secret","status":"observed","source":\{"snapshot\_id":"3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39","path":"api/tandir/security\.py","start\_line":16,"end\_line":16,"content\_sha256":"ad4a1e83183a7213f5ac2423b9d269785b6fda25df622b04585b6c80793aa458"\},"rule\_id":"secret-credential-assignment","rule\_version":"supplementary-signals-1","summary":"Credential-shaped text detected: \[REDACTED\]\.","fingerprint":"0518d244e809b208cd001a8db3eaae30508558bb5515859d18c32f4d3db03ad7","ecosystem":null,"package":null,"version":null,"advisory\_id":null,"limitations":\["Observation only; no challenge or runtime verification was performed\."\]\}

\{"id":"signal:fe9c0ec8922732c92f63a84b1004cadb","category":"secret","status":"observed","source":\{"snapshot\_id":"3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39","path":"api/tandir/security\.py","start\_line":22,"end\_line":22,"content\_sha256":"02e84957f9301238d1c9875fda50d68bd5de32a2999d32a94fd4420745732c31"\},"rule\_id":"secret-credential-assignment","rule\_version":"supplementary-signals-1","summary":"Credential-shaped text detected: \[REDACTED\]\.","fingerprint":"0518d244e809b208cd001a8db3eaae30508558bb5515859d18c32f4d3db03ad7","ecosystem":null,"package":null,"version":null,"advisory\_id":null,"limitations":\["Observation only; no challenge or runtime verification was performed\."\]\}

\{"id":"signal:3944987a4a02b62003693f21a7c31748","category":"dependency","status":"unknown","source":\{"snapshot\_id":"3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39","path":"api/uv\.lock","start\_line":1,"end\_line":360,"content\_sha256":"156763c38a4f44a9015bd05d03b17844d2c382e36d12353dd2b9473028645815"\},"rule\_id":"dependency-version-unknown","rule\_version":"supplementary-signals-1","summary":"Registry identity or exact resolved version is unknown; advisories were not matched\.","fingerprint":null,"ecosystem":"PyPI","package":"tandir-api","version":null,"advisory\_id":null,"limitations":\["Observation only; no challenge or runtime verification was performed\."\]\}

\{"id":"signal:5f99a6ea016bbc4b869204fe15c44aaa","category":"secret","status":"observed","source":\{"snapshot\_id":"3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39","path":"web/lib/sessions\.ts","start\_line":41,"end\_line":41,"content\_sha256":"fe1fd23bcd71b3e842a7c06f7ed1fbd837af2282662bd1605e5a098761bb71a4"\},"rule\_id":"secret-credential-assignment","rule\_version":"supplementary-signals-1","summary":"Credential-shaped text detected: \[REDACTED\]\.","fingerprint":"720d5a36129d2e08f15fa2830685fcb2db5b6375bdd1ffd71df7197157eec19c","ecosystem":null,"package":null,"version":null,"advisory\_id":null,"limitations":\["Observation only; no challenge or runtime verification was performed\."\]\}

\{"id":"signal:683cea0c405f3a3805728669eb239329","category":"secret","status":"observed","source":\{"snapshot\_id":"3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39","path":"web/lib/sessions\.ts","start\_line":56,"end\_line":56,"content\_sha256":"1601081f8c02f5248e3351654f79631c61861ada6d74a58d14f2288136d7e7b1"\},"rule\_id":"secret-credential-assignment","rule\_version":"supplementary-signals-1","summary":"Credential-shaped text detected: \[REDACTED\]\.","fingerprint":"9f42776f1c78866d9735709309e7c3232ef2fa59897a997d097f19756c50935b","ecosystem":null,"package":null,"version":null,"advisory\_id":null,"limitations":\["Observation only; no challenge or runtime verification was performed\."\]\}

## F-01

F-01: Order access: owner check

Peer deviation persists after three independent acquittal searches

Finding ID: finding:8a434935f7a4a50882a36a5a; family: authorization; CWE-639, CWE-862

Conclusion: supported

Runtime verification: not\_attempted

Severity: medium\. Source-impact v1: Potential unauthorized read of principal/tenant-scoped records through a declared HTTP route\. The data class is inferred from executable peer restrictions, not resource names; personal/payment contents and broader compromise are not established\. Evidence: E01, E06, E07, E08, E09, E05, E10, E11, E12, E13, E14, E15, E16, E17, E18, E19, E20, E21, E22, E23, E24, E25, E26, E27, E28, E29, E30, E31\. Deployment reachability, attacker prerequisites and runtime impact remain unverified\.

Evidence strength: partial

Disposition: open

F-01/E01 \(evidence\): api/tandir/routers/orders\.py:82-91; snapshot 3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39; content SHA256 5ff9ba2570c716f217a5aaba1a82eb67c4c4c854a199c1859836c3775481607e\. Code inspected during the acquittal search

F-01/E02 \(evidence\): api/tandir/security\.py:42-50; snapshot 3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39; content SHA256 480e8365f167b6f1fce108f42607dc76ff5d2630b7087914d7fae66840ba4266\. Code inspected during the acquittal search

F-01/E03 \(evidence\): api/tandir/schemas\.py:60-76; snapshot 3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39; content SHA256 aa7fd42fd67e92db6669a24495ab92bda3c22d0ccc29c0540d4a1094cf400a59\. Code inspected during the acquittal search

F-01/E04 \(evidence\): api/tandir/security\.py:35-39; snapshot 3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39; content SHA256 3a30b12d1f537b31fe30641caddfa0f1ce68c865ddbe2f58291588880a838997\. Code inspected during the acquittal search

F-01/E05 \(guard\): api/tandir/security\.py:45-46; snapshot 3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39; content SHA256 24567e8c3ce26089f49940402c80aa40b4fb7472bd78c2638f83243fcfb5c8ee\. Executable guard

F-01/E06 \(evidence\): api/tandir/routers/orders\.py:88-88; snapshot 3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39; content SHA256 5cea5be4556edc3522e358fe52f3e10e978b38bcf2bbec8e285681ed24b27f68\. Source used to assess potential impact

F-01/E07 \(evidence\): api/tandir/services/orders\.py:29-29; snapshot 3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39; content SHA256 5cea5be4556edc3522e358fe52f3e10e978b38bcf2bbec8e285681ed24b27f68\. Source used to assess potential impact

F-01/E08 \(evidence\): api/tandir/services/orders\.py:30-31; snapshot 3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39; content SHA256 baccb70d4adc2938e15d08c1bfb7744611187ad2fe7db77fc1d335223e272d03\. Source used to assess potential impact

F-01/E09 \(evidence\): api/tandir/services/orders\.py:26-26; snapshot 3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39; content SHA256 10063b59ed78cbcc7d212412fd079a8e673543a6235e5b0ce3bd43a944b088fb\. Source used to assess potential impact

F-01/E10 \(evidence\): api/tandir/routers/courier\.py:28-28; snapshot 3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39; content SHA256 aa1972acf81efaa418b22b7e4bc9549ce4a83fdf9594c5971c1fd15a891d458c\. Source used to assess potential impact

F-01/E11 \(evidence\): api/tandir/routers/courier\.py:26-26; snapshot 3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39; content SHA256 582a5ada38761b5ea9906ce17ee076545da2afa94e277a19e344eaf988af2b00\. Source used to assess potential impact

F-01/E12 \(evidence\): api/tandir/routers/courier\.py:12-12; snapshot 3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39; content SHA256 3b715d8a677848f8797f58282b0bd6f9daac499a44199a0c93129f70fc925e1a\. Source used to assess potential impact

F-01/E13 \(evidence\): api/tandir/security\.py:54-54; snapshot 3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39; content SHA256 09ce18b9d5b54b82eef3ae8d473fa9a5f9311825c6da065048000cd9ef3dced6\. Source used to assess potential impact

F-01/E14 \(evidence\): api/tandir/security\.py:55-56; snapshot 3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39; content SHA256 fbb571e89442fdf4896f4c4a74b1b541950a2a01aa8d61bced58662ae566ec60\. Source used to assess potential impact

F-01/E15 \(evidence\): api/tandir/routers/orders\.py:74-76; snapshot 3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39; content SHA256 dc7d724560f1740a6d32f78d23ef5174c83efbfefa48ee20d7bd8e29eb48ef2d\. Source used to assess potential impact

F-01/E16 \(evidence\): api/tandir/routers/orders\.py:71-71; snapshot 3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39; content SHA256 10063b59ed78cbcc7d212412fd079a8e673543a6235e5b0ce3bd43a944b088fb\. Source used to assess potential impact

F-01/E17 \(evidence\): api/tandir/routers/orders\.py:110-110; snapshot 3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39; content SHA256 5cea5be4556edc3522e358fe52f3e10e978b38bcf2bbec8e285681ed24b27f68\. Source used to assess potential impact

F-01/E18 \(evidence\): api/tandir/routers/orders\.py:111-112; snapshot 3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39; content SHA256 baccb70d4adc2938e15d08c1bfb7744611187ad2fe7db77fc1d335223e272d03\. Source used to assess potential impact

F-01/E19 \(evidence\): api/tandir/routers/orders\.py:107-107; snapshot 3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39; content SHA256 10063b59ed78cbcc7d212412fd079a8e673543a6235e5b0ce3bd43a944b088fb\. Source used to assess potential impact

F-01/E20 \(evidence\): api/tandir/services/orders\.py:11-13; snapshot 3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39; content SHA256 dc7d724560f1740a6d32f78d23ef5174c83efbfefa48ee20d7bd8e29eb48ef2d\. Source used to assess potential impact

F-01/E21 \(evidence\): api/tandir/routers/orders\.py:172-172; snapshot 3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39; content SHA256 10063b59ed78cbcc7d212412fd079a8e673543a6235e5b0ce3bd43a944b088fb\. Source used to assess potential impact

F-01/E22 \(evidence\): api/tandir/routers/courier\.py:38-38; snapshot 3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39; content SHA256 5cea5be4556edc3522e358fe52f3e10e978b38bcf2bbec8e285681ed24b27f68\. Source used to assess potential impact

F-01/E23 \(evidence\): api/tandir/routers/courier\.py:39-40; snapshot 3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39; content SHA256 6de004926f27b988baa029967ce01287807b832a748a36abbe7c26bf2835b665\. Source used to assess potential impact

F-01/E24 \(evidence\): api/tandir/routers/courier\.py:35-35; snapshot 3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39; content SHA256 a4799d7b2bf0654089ba4bff1f2ade3d94df502c173bafda44c7c992e3fe41e6\. Source used to assess potential impact

F-01/E25 \(evidence\): api/tandir/routers/orders\.py:139-139; snapshot 3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39; content SHA256 5cea5be4556edc3522e358fe52f3e10e978b38bcf2bbec8e285681ed24b27f68\. Source used to assess potential impact

F-01/E26 \(evidence\): api/tandir/services/orders\.py:20-21; snapshot 3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39; content SHA256 773b4ead011b0954b391f69dbda6396df7e732a0fea43875942136ba4bf31e2f\. Source used to assess potential impact

F-01/E27 \(evidence\): api/tandir/routers/orders\.py:136-136; snapshot 3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39; content SHA256 10063b59ed78cbcc7d212412fd079a8e673543a6235e5b0ce3bd43a944b088fb\. Source used to assess potential impact

F-01/E28 \(evidence\): api/tandir/routers/orders\.py:142-142; snapshot 3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39; content SHA256 ddd78011f84a8d14511ecda70b96ca036793f1429fb45555eaf12d04ce0ff85b\. Source used to assess potential impact

F-01/E29 \(evidence\): api/tandir/routers/orders\.py:31-31; snapshot 3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39; content SHA256 3b3b1766599127f3f7d25109d39fcff6dc5eb36df3c0715bd44c15e6a4da69af\. Source used to assess potential impact

F-01/E30 \(evidence\): api/tandir/routers/orders\.py:29-29; snapshot 3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39; content SHA256 f85c510c7310e2cb3b37e5f7e5bee268603aed3d29727b2854d16c6b12c59de1\. Source used to assess potential impact

F-01/E31 \(evidence\): api/tandir/routers/orders\.py:97-97; snapshot 3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39; content SHA256 10063b59ed78cbcc7d212412fd079a8e673543a6235e5b0ce3bd43a944b088fb\. Source used to assess potential impact

Challenge: A query filter scoped to the principal — not found; searched api/tandir/routers/orders\.py:82-91; api/tandir/security\.py:42-50; api/tandir/schemas\.py:60-76; api/tandir/security\.py:35-39 \(not\_found: Not found in the cited code searched; this is bounded negative evidence\)\.

Challenge: An equivalent guard in the handler, router, dependency or DAL — not found; searched api/tandir/routers/orders\.py:82-91; api/tandir/security\.py:42-50; api/tandir/schemas\.py:60-76; api/tandir/security\.py:35-39 \(not\_found: Not found in the cited code searched; this is bounded negative evidence\)\.

Challenge: An admin-only entry point — not found; searched api/tandir/routers/orders\.py:82-91; api/tandir/security\.py:42-50; api/tandir/schemas\.py:60-76; api/tandir/security\.py:35-39 \(not\_found: Not found in the cited code searched; this is bounded negative evidence\)\.

Challenge: A resource public by executable policy — not found; searched api/tandir/routers/orders\.py:82-91; api/tandir/security\.py:42-50; api/tandir/schemas\.py:60-76; api/tandir/security\.py:35-39 \(not\_found: Not found in the cited code searched; this is bounded negative evidence\)\.

Challenge: An unreachable route — not found; searched api/tandir/routers/orders\.py:82-91; api/tandir/security\.py:42-50; api/tandir/schemas\.py:60-76; api/tandir/security\.py:35-39 \(unsupported: Runtime reachability is not established by static mounting\)\.

Gap: Bounded static analysis; runtime verification not attempted

Unknown: Runtime reachability is not established by static mounting

Peer group: peers:632413dc67490d5dd0cde3fd

Questions: question:access:ffb0ea24ed0b07eb3940e2d4

## F-02

F-02: Order access: owner check

Three judgments cite executable protection on the access path

Finding ID: finding:c8e84a74edcc9b9f78438d67; family: authorization; CWE-639, CWE-862

Conclusion: rejected

Runtime verification: not\_attempted

Severity: unknown\. Not rated: the investigation is rejected\.

Evidence strength: partial

Disposition: open

F-02/E01 \(evidence\): api/tandir/routers/orders\.py:94-101; snapshot 3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39; content SHA256 1082adcb6f2c04ed23ca08bfc8e01776fcc33175bed0e07d316f42d89992a627\. Code inspected during the acquittal search

F-02/E02 \(evidence\): api/tandir/services/orders\.py:10-16; snapshot 3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39; content SHA256 3d1e9f676d301b4d76a7b85f980f6e1ff9c79a882b8bdbc321efec586e65ce1e\. Code inspected during the acquittal search

F-02/E03 \(evidence\): api/tandir/security\.py:42-50; snapshot 3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39; content SHA256 480e8365f167b6f1fce108f42607dc76ff5d2630b7087914d7fae66840ba4266\. Code inspected during the acquittal search

F-02/E04 \(evidence\): api/tandir/schemas\.py:82-85; snapshot 3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39; content SHA256 e38c4baa040a86b98526f9611ff041f68782ca9c0f268016037d440ae48eaf8e\. Code inspected during the acquittal search

F-02/E05 \(evidence\): api/tandir/security\.py:35-39; snapshot 3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39; content SHA256 3a30b12d1f537b31fe30641caddfa0f1ce68c865ddbe2f58291588880a838997\. Code inspected during the acquittal search

F-02/E06 \(guard\): api/tandir/security\.py:45-46; snapshot 3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39; content SHA256 24567e8c3ce26089f49940402c80aa40b4fb7472bd78c2638f83243fcfb5c8ee\. Executable guard

F-02/E07 \(guard\): api/tandir/services/orders\.py:11-13; snapshot 3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39; content SHA256 dc7d724560f1740a6d32f78d23ef5174c83efbfefa48ee20d7bd8e29eb48ef2d\. Executable guard

Challenge: A query filter scoped to the principal — found; searched api/tandir/routers/orders\.py:94-101; api/tandir/services/orders\.py:10-16; api/tandir/security\.py:42-50; api/tandir/schemas\.py:82-85; api/tandir/security\.py:35-39 \(found: Executable protection found on this access path\); F-02/E07\.

Challenge: An equivalent guard in the handler, router, dependency or DAL — not found; searched api/tandir/routers/orders\.py:94-101; api/tandir/services/orders\.py:10-16; api/tandir/security\.py:42-50; api/tandir/schemas\.py:82-85; api/tandir/security\.py:35-39 \(not\_found: Not found in the cited code searched; this is bounded negative evidence\)\.

Challenge: An admin-only entry point — not found; searched api/tandir/routers/orders\.py:94-101; api/tandir/services/orders\.py:10-16; api/tandir/security\.py:42-50; api/tandir/schemas\.py:82-85; api/tandir/security\.py:35-39 \(not\_found: Not found in the cited code searched; this is bounded negative evidence\)\.

Challenge: A resource public by executable policy — not found; searched api/tandir/routers/orders\.py:94-101; api/tandir/services/orders\.py:10-16; api/tandir/security\.py:42-50; api/tandir/schemas\.py:82-85; api/tandir/security\.py:35-39 \(not\_found: Not found in the cited code searched; this is bounded negative evidence\)\.

Challenge: An unreachable route — not found; searched api/tandir/routers/orders\.py:94-101; api/tandir/services/orders\.py:10-16; api/tandir/security\.py:42-50; api/tandir/schemas\.py:82-85; api/tandir/security\.py:35-39 \(unsupported: Runtime reachability is not established by static mounting\)\.

Gap: Bounded static analysis; runtime verification not attempted

Unknown: Runtime reachability is not established by static mounting

Peer group: peers:632413dc67490d5dd0cde3fd

Questions: question:access:f55c0f3a2d93e70d18a86db7

## Fix proposal proposal:061749560dd5819a316ed9b1

\{"id":"proposal:061749560dd5819a316ed9b1","finding\_id":"finding:8a434935f7a4a50882a36a5a","snapshot\_id":"3af5575a0bd6732b6302493a13be20bc7aaa56c8abe4c79e8da5571351944b39","status":"refused","reason":"Proposed code has invalid syntax; preserve indentation and punctuation\.","change":null,"probe\_status":"unavailable","probe\_reason":"No validated change/probe mapping was produced; verification unavailable\.","probe\_spec":null,"adapter\_manifest\_sha256":null\}
