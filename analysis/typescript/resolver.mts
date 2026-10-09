/** Trusted compiler helper. Target files exist only in the in-memory CompilerHost. */
import ts from "typescript";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { frameworkFacts, type ModuleFact } from "./nextjs_facts.mts";
import { accessFacts, type FunctionFacts } from "./access_facts.mts";
import { platformSource, platformCalls, type PlatformOperation } from "./platform_calls.mts";

const PIN = "6.0.3";
const ROOT = "/snapshot/";
const MAX_INPUT = 32 * 1024 * 1024;
const MAX_OUTPUT = 16 * 1024 * 1024;
const extensions = [".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs"];

type File = { path: string; text: string };
type SymbolRow = {
  id: string; path: string; name: string; kind: string;
  start_line: number; end_line: number; local_name: string;
};
type Input = { files: File[]; configs: File[]; symbols: SymbolRow[]; framework?: boolean; access?: boolean };
type Config = { directory: string; base: string; baseUrl: boolean; paths: Record<string, string[]> };
type Edge = {
  caller_id: string; target_id: string | null; callee: string; path: string;
  start_line: number; end_line: number; reference_line: number; column: number;
  status: "resolved" | "unresolved"; reason: string; kind: "call" | "reference";
  platform_operation?: PlatformOperation;
};
type Output = { version: string; platform_sha256: string; edges: Edge[]; issues: string[]; peak_rss_bytes: number; modules?: ModuleFact[]; functions?: FunctionFacts[] };

function sourcePath(name: string): string {
  if (!name || name.includes("\\") || name.includes(":") || name.startsWith("/") ||
      name.split("/").some(part => !part || part === "." || part === "..")) {
    throw new Error("Invalid snapshot-relative path");
  }
  return ROOT + name;
}

function within(base: string, value: string): string | undefined {
  if (value.includes("\\") || value.includes(":") || value.startsWith("/")) return;
  const joined = path.posix.normalize(path.posix.join(base, value));
  return joined.startsWith(ROOT) || joined === ROOT.slice(0, -1) ? joined : undefined;
}

export function analyze(input: Input): Output {
  if (ts.version !== PIN) throw new Error(`Expected TypeScript ${PIN}`);
  const platform = platformSource();
  const sources = new Map<string, ts.SourceFile>();
  const issues: string[] = [];
  for (const file of input.files) {
    const name = sourcePath(file.path);
    if (!extensions.some(ext => name.endsWith(ext))) throw new Error("Non-source input");
    if (sources.has(name)) throw new Error("Duplicate source path");
    sources.set(name, ts.createSourceFile(name, file.text, ts.ScriptTarget.Latest, true));
  }
  const configs: Config[] = [];
  for (const file of input.configs) {
    const name = sourcePath(file.path);
    const parsed = ts.parseConfigFileTextToJson(name, file.text);
    if (parsed.error || !parsed.config || typeof parsed.config !== "object") {
      issues.push(`${file.path}: invalid configuration; aliases unavailable`);
      continue;
    }
    // Only these data fields are read. No config loader, extends, plugins,
    // typeRoots, types, project references, package scripts, or emit is used.
    const directory = path.posix.dirname(name);
    const options = parsed.config.compilerOptions ?? {};
    if (parsed.config.extends) issues.push(`${file.path}: inherited configuration is not loaded`);
    const base = typeof options.baseUrl === "string" ? within(directory, options.baseUrl) : directory;
    if (!base) {
      issues.push(`${file.path}: baseUrl leaves the snapshot`);
      continue;
    }
    const mappings: Record<string, string[]> = Object.create(null);
    for (const [key, targets] of Object.entries(options.paths ?? {})) {
      if (typeof key === "string" && Array.isArray(targets) &&
          key.split("*").length <= 2 && targets.every(t => typeof t === "string")) {
        mappings[key] = targets;
      }
    }
    configs.push({ directory, base, baseUrl: typeof options.baseUrl === "string", paths: mappings });
  }
  configs.sort((a, b) => b.directory.length - a.directory.length);

  function candidate(base: string | undefined): string | undefined {
    if (!base) return;
    const substitutions = base.endsWith(".js") ? [base.slice(0, -3) + ".ts", base.slice(0, -3) + ".tsx"] :
      /\.[cm]js$/.test(base) ? [base.replace(/js$/, "ts")] : [];
    const choices = [...substitutions, base, ...extensions.map(ext => base + ext),
      ...extensions.map(ext => `${base}/index${ext}`)];
    return choices.find(p => sources.has(p));
  }
  function resolve(specifier: string, importer: string): ts.ResolvedModule | undefined {
    let resolved: string | undefined;
    if (specifier.startsWith(".")) resolved = candidate(within(path.posix.dirname(importer), specifier));
    else {
      const config = configs.find(c => importer.startsWith(c.directory + "/"));
      if (config) {
        // Exact path keys precede the most specific matching wildcard prefix.
        const patterns = Object.keys(config.paths).sort((a, b) =>
          Number(a.includes("*")) - Number(b.includes("*")) ||
          b.split("*")[0]!.length - a.split("*")[0]!.length);
        for (const pattern of patterns) {
          const [prefix, suffix] = pattern.split("*");
          const match = suffix === undefined ? specifier === pattern :
            specifier.startsWith(prefix!) && specifier.endsWith(suffix) &&
            specifier.length >= prefix!.length + suffix.length;
          if (!match) continue;
          const middle = suffix === undefined ? "" :
            specifier.slice(prefix!.length, specifier.length - suffix.length);
          for (const target of config.paths[pattern]!) {
            resolved = candidate(within(config.base, target.replace("*", middle)));
            if (resolved) break;
          }
          break;
        }
        if (!resolved && config.baseUrl) resolved = candidate(within(config.base, specifier));
      }
    }
    return resolved ? { resolvedFileName: resolved, isExternalLibraryImport: false } : undefined;
  }

  const options: ts.CompilerOptions = {
    target: ts.ScriptTarget.ESNext, module: ts.ModuleKind.ESNext,
    moduleResolution: ts.ModuleResolutionKind.Bundler, jsx: ts.JsxEmit.Preserve,
    strict: true, noLib: true, noEmit: true, allowJs: true, checkJs: true,
    skipLibCheck: true, types: [],
  };
  const host: ts.CompilerHost = {
    getSourceFile: name => name === platform.source.fileName ? platform.source : sources.get(name),
    getDefaultLibFileName: () => "/no-library.d.ts",
    writeFile: () => { throw new Error("Emit is disabled"); },
    getCurrentDirectory: () => ROOT.slice(0, -1),
    getDirectories: () => [],
    fileExists: name => sources.has(name),
    readFile: name => sources.get(name)?.text,
    directoryExists: name => [...sources.keys()].some(p => p.startsWith(name + "/")),
    getCanonicalFileName: name => name,
    useCaseSensitiveFileNames: () => true,
    getNewLine: () => "\n",
    resolveModuleNames: (names, containing) => names.map(name => resolve(name, containing)),
  };
  const program = ts.createProgram([...sources.keys(), platform.source.fileName], options, host);
  const checker = program.getTypeChecker();
  const platformOperation = platformCalls(program, checker, platform.source);
  const rows = new Map<string, SymbolRow[]>();
  const callable = new Set(["function", "method", "class", "component"]);
  for (const row of input.symbols) {
    const key = sourcePath(row.path);
    if (!sources.has(key)) throw new Error("Symbol outside source snapshot");
    rows.set(key, [...rows.get(key) ?? [], row]);
  }

  function declarationRow(declaration: ts.Declaration): SymbolRow | undefined {
    let node: ts.Node = declaration;
    if (ts.isExportAssignment(node) &&
        (ts.isArrowFunction(node.expression) || ts.isFunctionExpression(node.expression))) {
      node = node.expression;
    }
    if ((ts.isArrowFunction(node) || ts.isFunctionExpression(node)) && ts.isVariableDeclaration(node.parent)) {
      node = node.parent;
    }
    if ((ts.isArrowFunction(node) || ts.isFunctionExpression(node)) && ts.isExportAssignment(node.parent)) {
      const source = node.getSourceFile();
      const line = source.getLineAndCharacterOfPosition(node.parent.getStart(source)).line + 1;
      const matches = (rows.get(source.fileName) ?? []).filter(row => row.name === "default" && row.start_line === line);
      return matches.length === 1 ? matches[0] : undefined;
    }
    if (!ts.isFunctionDeclaration(node) && !ts.isMethodDeclaration(node) &&
        !ts.isClassDeclaration(node) && !ts.isVariableDeclaration(node)) return;
    const file = node.getSourceFile();
    if (!sources.has(file.fileName)) return;
    const name = node.name?.getText(file) ?? "default";
    const line = file.getLineAndCharacterOfPosition(node.getStart(file)).line + 1;
    const matches = (rows.get(file.fileName) ?? []).filter(row =>
      callable.has(row.kind) && row.name === name && row.start_line <= line && row.end_line >= line);
    return matches.length === 1 ? matches[0] : undefined;
  }

  function targets(expression: ts.Expression): SymbolRow[] {
    const token = ts.isPropertyAccessExpression(expression) ? expression.name : expression;
    let symbol = checker.getSymbolAtLocation(token);
    if (!symbol) return [];
    if (symbol.flags & ts.SymbolFlags.Alias) symbol = checker.getAliasedSymbol(symbol);
    const declarations = symbol.declarations ?? [];
    const found = new Map<string, SymbolRow>();
    for (const declaration of declarations) {
      const row = declarationRow(declaration);
      if (!row) return []; // unknown constituent: don't turn a partial union into a unique edge
      found.set(row.id, row);
    }
    return [...found.values()];
  }

  const edges: Edge[] = [];
  for (const source of sources.values()) {
    const fileRows = rows.get(source.fileName) ?? [];
    const module = fileRows.find(row => row.kind === "module");
    if (!module) throw new Error("Missing module symbol");
    for (const diagnostic of program.getSyntacticDiagnostics(source)) {
      issues.push(`${source.fileName.slice(ROOT.length)}: ${ts.flattenDiagnosticMessageText(diagnostic.messageText, " ")}`);
    }
    function record(expression: ts.Expression, kind: "call" | "reference"): void {
      const start = source.getLineAndCharacterOfPosition(expression.getStart(source));
      const end = source.getLineAndCharacterOfPosition(expression.getEnd() - 1);
      const token = ts.isPropertyAccessExpression(expression) ? expression.name : expression;
      const position = source.getLineAndCharacterOfPosition(token.getStart(source));
      let caller = module!;
      let inFunction = false;
      for (let parent = expression.parent; parent; parent = parent.parent) {
        if (ts.isFunctionDeclaration(parent) || ts.isMethodDeclaration(parent) ||
            ts.isArrowFunction(parent) || ts.isFunctionExpression(parent)) {
          inFunction = true;
          const row = declarationRow(parent);
          if (row) { caller = row; break; }
        }
        if (inFunction && ts.isVariableDeclaration(parent)) {
          const row = declarationRow(parent);
          if (row) { caller = row; break; }
        }
      }
      const targetRows = targets(expression);
      const target = targetRows.length === 1 ? targetRows[0] : undefined;
      const operation = kind === "call" && !target ? platformOperation(expression) : undefined;
      edges.push({ caller_id: caller.id, target_id: target?.id ?? null,
        callee: expression.getText(source), path: source.fileName.slice(ROOT.length),
        start_line: start.line + 1, end_line: end.line + 1,
        reference_line: position.line + 1, column: position.character,
        kind, status: target ? "resolved" : "unresolved",
        ...(operation ? { platform_operation: operation } : {}),
        reason: target ? "Unique snapshot declaration from TypeScript compiler" :
          targetRows.length > 1 ? "Multiple possible declarations" : "External, dynamic or unknown callable" });
    }
    function visit(node: ts.Node): void {
      if (ts.isCallExpression(node) || ts.isNewExpression(node)) record(node.expression, "call");
      // A Server Action passed to JSX is a reference, not a direct call. The
      // Next.js adapter classifies the exported action as an entry point later.
      if (ts.isJsxExpression(node) && node.expression &&
          (ts.isIdentifier(node.expression) || ts.isPropertyAccessExpression(node.expression))) {
        const attribute = ts.isJsxAttribute(node.parent) ? node.parent.name.getText(source) : "";
        if (targets(node.expression).length || ["action", "formAction"].includes(attribute)) {
          record(node.expression, "reference");
        }
      }
      ts.forEachChild(node, visit);
    }
    visit(source);
  }
  const functions = input.access || input.framework ? accessFacts(program, checker,
    declaration => declarationRow(declaration)?.id ?? null, ROOT) : undefined;
  const modules = input.framework ? frameworkFacts(program, checker,
    declaration => declarationRow(declaration)?.id ?? null,
    (specifier, importer) => resolve(specifier, importer)?.resolvedFileName.slice(ROOT.length) ?? null,
    expression => targets(expression).map(row => row.id), ROOT, functions ?? []) : undefined;
  return { version: ts.version, platform_sha256: platform.identity, edges, issues, peak_rss_bytes: process.resourceUsage().maxRSS * 1024,
    ...(modules ? { modules } : {}), ...(functions ? { functions } : {}) };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const chunks: Buffer[] = [];
  let bytes = 0;
  for await (const chunk of process.stdin) {
    bytes += chunk.length;
    if (bytes > MAX_INPUT) throw new Error("Input budget exceeded");
    chunks.push(chunk);
  }
  try {
    const output = JSON.stringify(analyze(JSON.parse(Buffer.concat(chunks).toString("utf8"))));
    if (Buffer.byteLength(output) > MAX_OUTPUT) throw new Error("Output budget exceeded");
    process.stdout.write(output);
  } catch (error) {
    process.stderr.write(error instanceof Error ? error.message : "TypeScript resolution failed");
    process.exitCode = 1;
  }
}
