/** Bounded structural projection over compiler symbols. No target evaluation. */
import ts from "typescript";
import type { FunctionFacts } from "./access_facts.mts";
import { arrayProvenance } from "./array_provenance.mts";

type Location = { path: string; start_line: number; end_line: number };
type Origin = Location & { symbol_id: string; resource: string; query_resource: string };
type Leaf = { origin: Origin; field: string; evidence: Location[] };
type Column = { field: string; resource: string };
type Value = { leaves: Leaf[]; members?: Map<string, Value>; record?: Origin;
  element?: Value; bindings?: ts.Symbol[];
  columns?: Map<string, Column>; unknowns: string[]; evidence: Location[] };
export type SerializationFact = Location & { owner_symbol_id: string; kind: "props" | "return";
  targets: string[]; fields: (Leaf & { output: string })[]; unknowns: string[];
  boundary_evidence: Location[] };
type Fn = ts.FunctionDeclaration | ts.FunctionExpression | ts.ArrowFunction;
const empty = (): Value => ({ leaves: [], unknowns: [], evidence: [] });
const unknown = (reason: string): Value => ({ ...empty(), unknowns: [reason] });
const unwrap = (node: ts.Expression): ts.Expression => {
  while (ts.isAsExpression(node) || ts.isSatisfiesExpression(node) ||
    ts.isParenthesizedExpression(node) || ts.isAwaitExpression(node) || ts.isNonNullExpression(node)) node = node.expression;
  return node;
};

export function serializationFacts(program: ts.Program, checker: ts.TypeChecker,
  declarationId: (node: ts.Declaration) => string | null,
  targets: (node: ts.Expression) => string[], summaries: FunctionFacts[], root: string,
  clientBinding: (node: ts.Expression) => { evidence: Location[]; unknowns: string[] }): SerializationFact[] {
  const output: SerializationFact[] = [];
  const arrays = arrayProvenance(program, checker, root);
  const queries = new Map<string, { origin: Origin; columns?: Map<string, Column>; evidence: Location[]; sql?: boolean }>();
  const location = (node: ts.Node): Location => {
    const source = node.getSourceFile();
    return { path: source.fileName.slice(root.length),
      start_line: source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1,
      end_line: source.getLineAndCharacterOfPosition(node.getEnd() - 1).line + 1 };
  };
  const key = (id: string, line: number, end: number): string => `${id}:${line}:${end}`;
  function projection(sql: string): { table: string; columns?: Map<string, Column> } | undefined {
    // Named tables and explicit columns only. Aliases, subqueries, set operations,
    // comments, duplicate output keys and computed projections are not guessed.
    if (sql.includes("__dynamic__") || /[()'"`;]|--|\/\*|\b(?:UNION|INTERSECT|EXCEPT)\b/i.test(sql)) return;
    const match = /^\s*SELECT\s+([\s\S]+?)\s+FROM\s+([A-Za-z_]\w*)\b([\s\S]*)$/i.exec(sql);
    if (!match) return;
    const table = match[2]!, tables = new Map([[table.toLowerCase(), table]]);
    let tail = match[3]!;
    // Keep ON expressions bounded to plain predicates; their meaning is not a guard.
    for (let count = 0; /^\s+(?:(?:INNER|LEFT|RIGHT|FULL)(?:\s+OUTER)?\s+)?JOIN\b/i.test(tail); count++) {
      if (count >= 16) return;
      const join = /^\s+(?:(?:INNER|LEFT|RIGHT|FULL)(?:\s+OUTER)?\s+)?JOIN\s+([A-Za-z_]\w*)\s+ON\s+([\s\S]+?)(?=\s+(?:(?:(?:INNER|LEFT|RIGHT|FULL)(?:\s+OUTER)?\s+)?JOIN|WHERE|ORDER\s+BY|LIMIT|OFFSET)\b|$)/i.exec(tail);
      if (!join || tables.has(join[1]!.toLowerCase()) || !/^[A-Za-z0-9_\s.?=<>!+:-]+$/.test(join[2]!)) return;
      tables.set(join[1]!.toLowerCase(), join[1]!);
      tail = tail.slice(join[0].length);
    }
    if (tail.trim() && !/^\s+(?:WHERE|ORDER\s+BY|LIMIT|OFFSET)\b/i.test(tail)) return;
    if (/\bJOIN\b/i.test(tail)) return;
    const columns = new Map<string, Column>(), pieces = match[1]!.split(",");
    if (pieces.length > 256) return;
    for (const column of pieces) {
      const item = /^\s*(?:([A-Za-z_]\w*)\.)?([A-Za-z_]\w*|\*)(?:\s+AS\s+([A-Za-z_]\w*))?\s*$/i.exec(column);
      if (!item || (!item[1] && tables.size > 1)) return;
      const resource = item[1] ? tables.get(item[1].toLowerCase()) : table;
      if (!resource) return;
      if (item[2] === "*") return pieces.length === 1 && resource === table && !item[3] ? { table } : undefined;
      const name = item[3] ?? item[2]!;
      if ([...columns.keys()].some(k => k.toLowerCase() === name.toLowerCase())) return;
      columns.set(name, { field: item[2]!, resource });
    }
    return { table, columns };
  }
  for (const fn of summaries) {
    for (const access of fn.accesses) queries.set(key(fn.symbol_id, access.start_line, access.end_line),
      { origin: { symbol_id: fn.symbol_id, path: "", start_line: access.start_line, end_line: access.end_line,
        resource: access.resource, query_resource: access.resource }, evidence: [] });
    for (const sql of fn.sql_calls) {
      const parsed = projection(sql.sql);
      if (!parsed) continue;
      queries.set(key(fn.symbol_id, sql.start_line, sql.end_line), { origin: { symbol_id: fn.symbol_id,
        path: "", start_line: sql.start_line, end_line: sql.end_line,
        resource: parsed.table, query_resource: parsed.table }, columns: parsed.columns, evidence: sql.evidence, sql: true });
    }
  }
  function symbol(node: ts.Node): ts.Symbol | undefined { return checker.getSymbolAtLocation(node); }
  function defs(node: ts.Node): readonly ts.Declaration[] {
    let bound = symbol(node);
    if (bound && bound.flags & ts.SymbolFlags.Alias) bound = checker.getAliasedSymbol(bound);
    return bound?.declarations ?? [];
  }
  function owner(node: ts.Node): Fn | undefined {
    for (let parent = node.parent; parent; parent = parent.parent) {
      if (ts.isFunctionDeclaration(parent) || ts.isFunctionExpression(parent) || ts.isArrowFunction(parent)) return parent;
    }
    return;
  }
  function identity(fn: Fn): string | null {
    return declarationId(fn) ?? (ts.isVariableDeclaration(fn.parent) ? declarationId(fn.parent) : null);
  }
  function trace(value: Value, node: ts.Node): Value { return { ...value, evidence: [...value.evidence, location(node)] }; }
  function inherit(value: Value, parent: Value): Value {
    return { ...value, evidence: [...parent.evidence, ...value.evidence],
      unknowns: [...parent.unknowns, ...value.unknowns] };
  }
  function flatten(value: Value, prefix: string, prior: Location[] = []): (Leaf & { output: string })[] {
    const evidence = [...prior, ...value.evidence];
    if (value.element) return flatten(value.element, `${prefix}[]`, evidence);
    if (value.members) return [...value.members].flatMap(([name, item]) => flatten(item, prefix ? `${prefix}.${name}` : name, evidence));
    if (value.record) {
      const names = value.columns ?? new Map([["*", { field: "*", resource: value.record.resource }]]);
      return [...names].map(([name, column]) => ({ origin: { ...value.record!, resource: column.resource }, field: column.field,
        output: prefix ? `${prefix}.${name}` : name, evidence }));
    }
    return value.leaves.map(leaf => ({ ...leaf, output: prefix, evidence: [...leaf.evidence, ...evidence] }));
  }
  function denial(stmt: ts.IfStatement): boolean {
    if (stmt.elseStatement) return false;
    const body = ts.isBlock(stmt.thenStatement) ? stmt.thenStatement.statements : [stmt.thenStatement];
    return body.length === 1 && (ts.isThrowStatement(body[0]!) ||
      (ts.isExpressionStatement(body[0]!) && ts.isCallExpression(body[0].expression) &&
       (symbol(body[0].expression.expression)?.declarations ?? []).some(d => {
         if (!ts.isImportSpecifier(d) || !["notFound", "redirect"].includes((d.propertyName ?? d.name).text)) return false;
         for (let p: ts.Node | undefined = d; p; p = p.parent) {
           if (ts.isImportDeclaration(p) && ts.isStringLiteral(p.moduleSpecifier)) return p.moduleSpecifier.text === "next/navigation";
         } return false;
       })) || (ts.isReturnStatement(body[0]!) && !!body[0].expression &&
        /\{\s*status:\s*[45]\d\d\s*\}/.test(body[0].expression.getText())));
  }
  function evaluate(fn: Fn, args: Value[], stop?: ts.Node, depth = 0, seen = new Set<Fn>()): Value {
    if (depth > 4 || seen.has(fn) || !fn.body || fn.parameters.some(p => p.dotDotDotToken || p.initializer)) return unknown("Helper binding/depth unresolved");
    const env = new Map<ts.Symbol, Value>();
    fn.parameters.forEach((p, i) => {
      const value = args[i] ?? unknown("External parameter");
      if (ts.isIdentifier(p.name)) { const s = symbol(p.name); if (s) env.set(s, value); }
      else if (ts.isObjectBindingPattern(p.name)) for (const item of p.name.elements) {
        const s = symbol(item.name); if (s) env.set(s, unknown("Destructured external parameter"));
      }
    });
    const next = new Set(seen).add(fn);
    function expression(raw: ts.Expression): Value {
      const node = unwrap(raw);
      if (ts.isIdentifier(node)) return env.get(symbol(node)!) ?? unknown("Unbound value");
      if (ts.isLiteralExpression(node) || [ts.SyntaxKind.TrueKeyword, ts.SyntaxKind.FalseKeyword, ts.SyntaxKind.NullKeyword].includes(node.kind)) return empty();
      if (ts.isPropertyAccessExpression(node)) {
        const base = expression(node.expression);
        if (base.element) return unknown("Array member projection unresolved");
        if (base.members) {
          const value = base.members.get(node.name.text) ?? empty();
          return trace(inherit(value, base), node);
        }
        if (base.record) {
          const column = base.columns ? base.columns.get(node.name.text) : { field: node.name.text, resource: base.record.resource };
          if (!column) return unknown("Field is absent from the known query projection");
          return { ...empty(), unknowns: [...base.unknowns], leaves: [{ origin: { ...base.record, resource: column.resource }, field: column.field,
            evidence: [...base.evidence, location(node)] }] };
        }
        return unknown("Property receiver unresolved");
      }
      if (ts.isObjectLiteralExpression(node)) {
        const members = new Map<string, Value>(), unknowns: string[] = [];
        for (const property of node.properties) {
          if (ts.isSpreadAssignment(property)) {
            const spread = expression(property.expression);
            if (spread.members) for (const [name, value] of spread.members) members.set(name, trace(inherit(value, spread), property));
            else if (spread.record && spread.columns) for (const [name, column] of spread.columns)
              members.set(name, { ...empty(), unknowns: [...spread.unknowns], leaves: [{ origin: { ...spread.record, resource: column.resource }, field: column.field,
                evidence: [...spread.evidence, location(property)] }] });
            else { members.clear(); unknowns.push("Dynamic or whole-record object spread unresolved"); }
            unknowns.push(...spread.unknowns);
          } else if ((ts.isPropertyAssignment(property) || ts.isShorthandPropertyAssignment(property)) &&
              (ts.isIdentifier(property.name) || ts.isStringLiteral(property.name))) {
            const value = expression(ts.isPropertyAssignment(property) ? property.initializer : property.name);
            members.set(property.name.text, trace(value, property)); unknowns.push(...value.unknowns);
          } else unknowns.push("Computed/accessor projection unresolved");
        }
        return { ...empty(), members, unknowns, evidence: [location(node)] };
      }
      if (ts.isCallExpression(node)) {
        if (ts.isPropertyAccessExpression(node.expression) && !node.questionDotToken &&
            !node.typeArguments?.length && node.arguments.length === 1 && !ts.isSpreadElement(node.arguments[0]!)) {
          const access = node.expression;
          if (arrays.method(access, "includes")) {
            const literal = arrays.literal(access.expression);
            if (literal) {
              const value = trace(expression(node.arguments[0]!), node);
              return { ...value, evidence: [...value.evidence, ...literal.map(location)] };
            }
          }
          if (arrays.method(access, "map")) {
            const base = expression(access.expression);
            const callback = node.arguments[0]!;
            const candidates = ts.isArrowFunction(callback) || ts.isFunctionExpression(callback) ? [callback] : defs(callback);
            if (base.element && !(base.bindings ?? []).some(s => !arrays.bindingIntact(s)) &&
                candidates.length === 1 && (ts.isFunctionDeclaration(candidates[0]!) ||
                ts.isFunctionExpression(candidates[0]!) || ts.isArrowFunction(candidates[0]!)) &&
                candidates[0].parameters.length === 1 && arrays.synchronous(candidates[0]) &&
                arrays.callableIntact(candidates[0])) {
              const mapped = evaluate(candidates[0], [base.element], undefined, depth + 1, next);
              return { ...empty(), element: mapped, evidence: [...base.evidence, location(node)],
                unknowns: [...base.unknowns, ...mapped.unknowns] };
            }
            return unknown("Array receiver or callback unresolved");
          }
        }
        const id = identity(owner(node) ?? fn), where = location(node);
        const seed = id ? queries.get(key(id, where.start_line, where.end_line)) : undefined;
        if (seed) {
          let columns = seed.columns;
          const options = node.arguments[0];
          if (options && ts.isObjectLiteralExpression(options)) {
            if (options.properties.some(p => ts.isSpreadAssignment(p))) return unknown("Dynamic query options unresolved");
            const select = options.properties.find(p => ts.isPropertyAssignment(p) && p.name.getText() === "select");
            if (select && ts.isPropertyAssignment(select)) {
              if (!ts.isObjectLiteralExpression(select.initializer)) return unknown("Query selection unresolved");
              columns = new Map<string, Column>();
              for (const p of select.initializer.properties) {
                if (!ts.isPropertyAssignment(p) || !ts.isIdentifier(p.name) ||
                  ![ts.SyntaxKind.TrueKeyword, ts.SyntaxKind.FalseKeyword].includes(p.initializer.kind)) return unknown("Query selection unresolved");
                if (p.initializer.kind === ts.SyntaxKind.TrueKeyword) columns.set(p.name.text, { field: p.name.text, resource: seed.origin.resource });
              }
            }
          }
          const rows = arrays.rows(node);
          const scalar = seed.sql && !rows ? arrays.scalar(node) : undefined;
          const record = { ...empty(), record: { ...seed.origin, path: where.path }, columns,
            evidence: [where, ...seed.evidence, ...(scalar ?? []).map(location)],
            unknowns: seed.sql && !rows && !scalar ? ["SQL execution source binding unresolved"] : [] };
          return rows ? { ...empty(), element: record, evidence: rows.map(location) } : record;
        }
        const candidates = defs(node.expression);
        if (candidates.length === 1 && (ts.isFunctionDeclaration(candidates[0]!) || ts.isFunctionExpression(candidates[0]!) || ts.isArrowFunction(candidates[0]!))) {
          const helper = candidates[0] as Fn;
          if (!arrays.callableIntact(helper)) return unknown("Helper callable identity unresolved");
          if (node.arguments.length !== helper.parameters.length || node.arguments.some(ts.isSpreadElement)) return unknown("Helper arguments unresolved");
          const binding = arrays.imports(node.expression);
          if (!binding) return unknown("Helper import binding unresolved");
          const value = evaluate(helper, node.arguments.map(expression), undefined, depth + 1, next);
          return trace({ ...value, evidence: [...value.evidence, ...binding.map(location)] }, node);
        }
        return unknown("Indirect transformation unresolved");
      }
      return unknown("Unsupported serialization expression");
    }
    if (!ts.isBlock(fn.body)) return expression(fn.body);
    if (fn.body.statements.length > 256) return unknown("Serialization body budget exceeded");
    for (const stmt of fn.body.statements) {
      if (stop && stmt.getStart() <= stop.getStart() && stop.getEnd() <= stmt.getEnd()) {
        if (!ts.isReturnStatement(stmt) && !ts.isExpressionStatement(stmt)) return unknown("Crossing in conditional or unsupported flow");
        if (ts.isJsxSelfClosingElement(stop) || ts.isJsxOpeningElement(stop)) {
          for (let p: ts.Node | undefined = stop.parent; p && p !== stmt; p = p.parent)
            if (ts.isConditionalExpression(p) || ts.isBinaryExpression(p) || ts.isCallExpression(p)) return unknown("Conditional JSX crossing unresolved");
          const members = new Map<string, Value>(), unknowns: string[] = [];
          for (const prop of stop.attributes.properties) {
            if (ts.isJsxSpreadAttribute(prop)) {
              const value = expression(prop.expression);
              if (value.members) for (const [name, v] of value.members) members.set(name, inherit(v, value));
              else { members.clear(); unknowns.push("Dynamic JSX spread unresolved"); }
              unknowns.push(...value.unknowns);
            } else {
              const value = prop.initializer && ts.isJsxExpression(prop.initializer) && prop.initializer.expression ? expression(prop.initializer.expression) : empty();
              members.set(prop.name.getText(), value); unknowns.push(...value.unknowns);
            }
          }
          return { ...empty(), members, unknowns };
        }
        if (ts.isReturnStatement(stop) && stop.expression) {
          const node = unwrap(stop.expression);
          if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression) &&
              ts.isIdentifier(node.expression.expression) && node.expression.expression.text === "Response" &&
              defs(node.expression.expression).length === 0 && node.expression.name.text === "json" && node.arguments[0]) return trace(expression(node.arguments[0]), node);
          return expression(stop.expression);
        }
        return unknown("Crossing in conditional or unsupported flow");
      }
      if (ts.isVariableStatement(stmt) && stmt.declarationList.flags & ts.NodeFlags.Const) {
        for (const decl of stmt.declarationList.declarations) {
          if (!decl.initializer) return unknown("Binding without initializer");
          if (ts.isIdentifier(decl.name)) {
            const s = symbol(decl.name);
            if (s) {
              const value = trace(expression(decl.initializer), decl);
              env.set(s, value.element ? { ...value, bindings: [...value.bindings ?? [], s] } : value);
            }
          } else if (ts.isObjectBindingPattern(decl.name) && decl.name.elements.every(e => ts.isIdentifier(e.name) && !e.dotDotDotToken && !e.initializer)) {
            const value = expression(decl.initializer);
            for (const item of decl.name.elements) {
              const s = symbol(item.name), name = (item.propertyName ?? item.name).getText();
              if (s) env.set(s, trace(inherit(value.members?.get(name) ?? unknown("Destructured source unresolved"), value), decl));
            }
          } else return unknown("Destructured binding unresolved");
        }
      } else if (ts.isIfStatement(stmt) && denial(stmt)) continue;
      else if (ts.isReturnStatement(stmt) && stmt.expression) return trace(expression(stmt.expression), stmt);
      else if (ts.isExpressionStatement(stmt) && ts.isStringLiteral(stmt.expression)) continue;
      else return unknown("Conditional, mutation or effect before serialization");
    }
    return unknown("Serialization return unavailable");
  }
  for (const source of program.getSourceFiles()) {
    function visit(node: ts.Node): void {
      if (ts.isJsxSelfClosingElement(node) || ts.isJsxOpeningElement(node) || ts.isReturnStatement(node)) {
        if (ts.isReturnStatement(node)) {
          let p = node.parent;
          if (ts.isBlock(p)) p = p.parent;
          if (ts.isIfStatement(p) && denial(p)) return;
        }
        const fn = owner(node), id = fn ? identity(fn) : null;
        if (fn && id) {
          const props = ts.isJsxSelfClosingElement(node) || ts.isJsxOpeningElement(node);
          const value = evaluate(fn, [], node);
          const binding = props ? clientBinding(node.tagName as ts.Expression) : { evidence: [], unknowns: [] };
          output.push({ ...location(node), owner_symbol_id: id, kind: props ? "props" : "return",
            targets: props ? targets(node.tagName as ts.Expression) : [],
            boundary_evidence: binding.evidence,
            fields: flatten(value, ""), unknowns: [...new Set([...value.unknowns, ...binding.unknowns,
              ...(flatten(value, "").some(f => f.field === "*") ? ["Whole-record field schema unresolved"] : [])])] });
        }
      }
      ts.forEachChild(node, visit);
    }
    visit(source);
  }
  return output;
}
