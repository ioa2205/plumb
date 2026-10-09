/** Symbolic input influence and database syntax. Never imports reviewed modules. */
import ts from "typescript";

type Parameter = { name: string; index: number; field: string };
type Call = { line: number; column: number; arguments: string[][]; keywords: Record<string, string[]> };
type Access = {
  resource: string; operation: "read" | "list" | "update" | "delete";
  data_layer: "prisma" | "drizzle"; key_inputs: string[]; key_expression: string;
  start_line: number; end_line: number; reason: string;
};
type Location = { path: string; start_line: number; end_line: number };
type SqlCall = { sql: string; bindings: string[][]; start_line: number; end_line: number; evidence: Location[] };
export type FunctionFacts = {
  symbol_id: string; parameters: Parameter[]; calls: Call[]; accesses: Access[]; sql_calls: SqlCall[];
};
type FunctionNode = ts.FunctionDeclaration | ts.ArrowFunction | ts.FunctionExpression | ts.MethodDeclaration;
function isFunction(node: ts.Node): node is FunctionNode {
  return ts.isFunctionDeclaration(node) || ts.isArrowFunction(node) || ts.isFunctionExpression(node) || ts.isMethodDeclaration(node);
}
function union(parts: string[][]): string[] { return [...new Set(parts.flat())].sort(); }
function unwrap(node: ts.Node): ts.Node {
  while (ts.isAsExpression(node) || ts.isSatisfiesExpression(node) || ts.isParenthesizedExpression(node) || ts.isAwaitExpression(node)) node = node.expression;
  return node;
}

export function accessFacts(program: ts.Program, checker: ts.TypeChecker,
  declarationId: (declaration: ts.Declaration) => string | null, root: string): FunctionFacts[] {
  const output: FunctionFacts[] = [];
  function location(node: ts.Node): Location {
    const source = node.getSourceFile();
    if (!source.fileName.startsWith(root)) throw new Error("SQL source is outside the snapshot");
    return { path: source.fileName.slice(root.length),
      start_line: source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1,
      end_line: source.getLineAndCharacterOfPosition(node.getEnd() - 1).line + 1 };
  }
  function declarations(node: ts.Node): readonly ts.Declaration[] {
    let symbol = checker.getSymbolAtLocation(node);
    if (symbol && symbol.flags & ts.SymbolFlags.Alias) symbol = checker.getAliasedSymbol(symbol);
    return symbol?.declarations ?? [];
  }
  function origin(node: ts.Node, depth = 0): string | null {
    if (depth > 16) return null;
    node = unwrap(node);
    if (ts.isPropertyAccessExpression(node)) return origin(node.expression, depth + 1);
    if (ts.isCallExpression(node) || ts.isNewExpression(node)) return origin(node.expression, depth + 1);
    const direct = checker.getSymbolAtLocation(node)?.declarations ?? [];
    for (const decl of direct) {
      for (let parent: ts.Node | undefined = decl; parent; parent = parent.parent) {
        if (ts.isImportDeclaration(parent) && ts.isStringLiteral(parent.moduleSpecifier)) {
          const specifier = parent.moduleSpecifier.text;
          if (!specifier.startsWith(".") && !specifier.startsWith("@/")) return specifier;
          break;
        }
      }
    }
    for (const decl of declarations(node)) {
      if (ts.isVariableDeclaration(decl) && decl.initializer) {
        const result = origin(decl.initializer, depth + 1);
        if (result) return result;
      }
    }
    return null;
  }
  function sqlText(node: ts.Node, seen = new Set<ts.Node>()): { text: string; evidence: Location[] } | null {
    node = unwrap(node);
    if (seen.has(node) || seen.size > 32) return null;
    const next = new Set(seen).add(node);
    if (ts.isStringLiteralLike(node)) return { text: node.text, evidence: [location(node)] };
    if (ts.isTemplateExpression(node)) {
      let text = node.head.text;
      const evidence = [location(node)];
      for (const part of node.templateSpans) {
        const value = sqlText(part.expression, next);
        text += (value?.text ?? "__dynamic__") + part.literal.text;
        evidence.push(...value?.evidence ?? []);
      }
      return { text, evidence };
    }
    if (ts.isIdentifier(node)) {
      const defs = declarations(node);
      if (defs.length === 1 && ts.isVariableDeclaration(defs[0]!) && defs[0].initializer &&
          ts.isVariableDeclarationList(defs[0].parent) && defs[0].parent.flags & ts.NodeFlags.Const) {
        const value = sqlText(defs[0].initializer, next);
        return value ? { text: value.text, evidence: [location(defs[0]), ...value.evidence] } : null;
      }
    }
    if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.PlusToken) {
      const left = sqlText(node.left, next), right = sqlText(node.right, next);
      return left !== null && right !== null ?
        { text: left.text + right.text, evidence: [...left.evidence, ...right.evidence] } : null;
    }
    return null;
  }
  function sqlWrapper(node: ts.Expression): boolean {
    const defs = declarations(node);
    if (defs.length !== 1) return false;
    const decl = defs[0]!;
    if (!isFunction(decl) || !decl.body) return false;
    const source = decl.getSourceFile();
    const hasDriver = source.statements.some(s => ts.isImportDeclaration(s) && ts.isStringLiteral(s.moduleSpecifier) &&
      ["node:sqlite", "better-sqlite3", "sqlite3", "pg", "mysql2"].includes(s.moduleSpecifier.text));
    let prepare = false;
    function visit(n: ts.Node): void {
      if (ts.isCallExpression(n) && ts.isPropertyAccessExpression(n.expression) &&
          ["prepare", "query", "execute"].includes(n.expression.name.text)) prepare = true;
      ts.forEachChild(n, visit);
    }
    visit(decl.body);
    return hasDriver && prepare;
  }
  for (const source of program.getSourceFiles()) {
    function collect(node: ts.Node): void {
      if (isFunction(node) && node.body) {
        let id = declarationId(node);
        if (!id && ts.isCallExpression(node.parent) && ts.isVariableDeclaration(node.parent.parent)) id = declarationId(node.parent.parent);
        if (id) summarize(node, id);
      }
      ts.forEachChild(node, collect);
    }
    function summarize(fn: FunctionNode, id: string): void {
      const fact: FunctionFacts = { symbol_id: id, parameters: [], calls: [], accesses: [], sql_calls: [] };
      const env = new Map<string, string[]>();
      fn.parameters.forEach((parameter, index) => {
        if (ts.isIdentifier(parameter.name)) {
          fact.parameters.push({ name: parameter.name.text, index, field: "" });
          env.set(parameter.name.text, [`p${index}`]);
        } else if (ts.isObjectBindingPattern(parameter.name)) {
          for (const item of parameter.name.elements) {
            if (ts.isIdentifier(item.name)) {
              const field = item.propertyName?.getText(source) ?? item.name.text;
              fact.parameters.push({ name: item.name.text, index, field });
              env.set(item.name.text, [`p${index}.${field}`]);
            }
          }
        }
      });
      function inputs(node: ts.Node | undefined): string[] {
        if (!node) return [];
        node = unwrap(node);
        if (ts.isIdentifier(node)) return env.get(node.text) ?? ["?"];
        if (ts.isLiteralExpression(node) || [ts.SyntaxKind.TrueKeyword, ts.SyntaxKind.FalseKeyword, ts.SyntaxKind.NullKeyword].includes(node.kind)) return [];
        if (ts.isPropertyAccessExpression(node)) return inputs(node.expression).map(token => token.startsWith("p") ? `${token}.${node.name.text}` : token);
        if (ts.isPropertyAssignment(node)) return inputs(node.initializer);
        if (ts.isCallExpression(node)) {
          const args = node.arguments.map(inputs);
          if (ts.isPropertyAccessExpression(node.expression)) args.push(inputs(node.expression.expression));
          return union(args).length ? union(args) : ["?"];
        }
        const parts: string[][] = [];
        ts.forEachChild(node, n => { parts.push(inputs(n)); });
        return union(parts);
      }
      const nodes: ts.Node[] = [];
      function walk(n: ts.Node): void {
        if (isFunction(n) && n !== fn) return;
        nodes.push(n); ts.forEachChild(n, walk);
      }
      walk(fn.body!);
      for (let iteration = 0; iteration < 16; iteration++) {
        let changed = false;
        for (const n of nodes) {
          if (ts.isVariableDeclaration(n) && n.initializer) {
            const value = inputs(n.initializer);
            const names = ts.isIdentifier(n.name) ? [n.name.text] :
              ts.isObjectBindingPattern(n.name) || ts.isArrayBindingPattern(n.name) ? n.name.elements.flatMap(e => ts.isBindingElement(e) ? [e.name.getText(source)] : []) : [];
            for (const name of names) {
              const before = env.get(name) ?? [], after = union([before, value]);
              if (before.join("\0") !== after.join("\0")) { env.set(name, after); changed = true; }
            }
          }
          if (ts.isBinaryExpression(n) && n.operatorToken.kind === ts.SyntaxKind.EqualsToken && ts.isIdentifier(n.left)) {
            const before = env.get(n.left.text) ?? [], after = union([before, inputs(n.right)]);
            if (before.join("\0") !== after.join("\0")) { env.set(n.left.text, after); changed = true; }
          }
        }
        if (!changed) break;
      }
      for (const node of nodes) {
        if (!ts.isCallExpression(node) && !ts.isNewExpression(node)) continue;
        const expr = node.expression;
        const token = ts.isPropertyAccessExpression(expr) ? expr.name : expr;
        const position = source.getLineAndCharacterOfPosition(token.getStart(source));
        const args = [...node.arguments ?? []];
        fact.calls.push({ line: position.line + 1, column: position.character,
          arguments: args.map(inputs), keywords: {} });
        const location = { start_line: source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1,
          end_line: source.getLineAndCharacterOfPosition(node.getEnd() - 1).line + 1 };
        const sql = args[0] ? sqlText(args[0]) : null;
        const driver = origin(expr);
        if (sql !== null && (sqlWrapper(expr) || (ts.isPropertyAccessExpression(expr) &&
            ["prepare", "query", "execute"].includes(expr.name.text) &&
            ["node:sqlite", "better-sqlite3", "sqlite3", "pg", "mysql2"].includes(driver ?? "")))) {
          let bindings = args.slice(1).map(inputs);
          if (ts.isPropertyAccessExpression(expr) && expr.name.text === "prepare" &&
              ts.isPropertyAccessExpression(node.parent) && ts.isCallExpression(node.parent.parent)) {
            bindings = [...node.parent.parent.arguments].map(inputs);
          }
          fact.sql_calls.push({ sql: sql.text, evidence: sql.evidence, bindings, ...location });
        }
        if (!ts.isPropertyAccessExpression(expr)) continue;
        const method = expr.name.text;
        if (driver === "@prisma/client" && ts.isPropertyAccessExpression(expr.expression) &&
            ["findUnique", "findFirst", "findMany", "update", "delete"].includes(method)) {
          const arg = args[0];
          if (!arg || !ts.isObjectLiteralExpression(arg)) continue;
          const where = arg.properties.find(p => ts.isPropertyAssignment(p) && p.name.getText(source) === "where");
          if (!where || !ts.isPropertyAssignment(where) || !ts.isObjectLiteralExpression(where.initializer)) continue;
          const keys = where.initializer.properties.filter((p): p is ts.PropertyAssignment | ts.ShorthandPropertyAssignment =>
            (ts.isPropertyAssignment(p) || ts.isShorthandPropertyAssignment(p)) && /^(id|\w+Id|\w+_id)$/.test(p.name.getText(source)));
          if (!keys.length) continue;
          const primary = keys.filter(k => k.name.getText(source) === "id");
          const selected = primary.length ? primary : keys;
          fact.accesses.push({ resource: expr.expression.name.text,
            operation: method === "update" ? "update" : method === "delete" ? "delete" : method === "findMany" ? "list" : "read",
            data_layer: "prisma", key_inputs: union(selected.map(p => inputs(ts.isPropertyAssignment(p) ? p.initializer : p.name))),
            key_expression: where.initializer.getText(source), ...location,
            reason: "Prisma client origin and literal where key; possible input influence" });
        }
        if (driver?.startsWith("drizzle-orm") && method === "where") {
          let table: ts.Expression | undefined;
          let chain: ts.Node = expr.expression;
          while (ts.isCallExpression(chain) && ts.isPropertyAccessExpression(chain.expression)) {
            if (chain.expression.name.text === "from") table = chain.arguments[0];
            chain = chain.expression.expression;
          }
          const keys: ts.Expression[] = [];
          function predicates(n: ts.Node): void {
            if (ts.isCallExpression(n) && origin(n.expression)?.startsWith("drizzle-orm") &&
                n.arguments.length === 2 && ts.isPropertyAccessExpression(n.arguments[0]!) &&
                /^(id|\w+Id|\w+_id)$/.test(n.arguments[0].name.text)) keys.push(n.arguments[1]!);
            ts.forEachChild(n, predicates);
          }
          args.forEach(predicates);
          if (table && keys.length) fact.accesses.push({ resource: table.getText(source), operation: "read",
            data_layer: "drizzle", key_inputs: union(keys.map(inputs)), key_expression: args.map(a => a.getText(source)).join(", "),
            ...location, reason: "Drizzle client origin and keyed predicate syntax; possible input influence" });
        }
      }
      output.push(fact);
    }
    collect(source);
  }
  return output;
}
