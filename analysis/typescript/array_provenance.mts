/** Exact array receiver provenance; no reviewed code is executed. */
import ts from "typescript";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";

type Fn = ts.FunctionDeclaration | ts.FunctionExpression | ts.ArrowFunction;
const fn = (node: ts.Node): node is Fn => ts.isFunctionDeclaration(node) ||
  ts.isFunctionExpression(node) || ts.isArrowFunction(node);
const unwrap = (node: ts.Node): ts.Node => {
  while (ts.isAsExpression(node) || ts.isParenthesizedExpression(node)) node = node.expression;
  return node;
};
const missing = (node: ts.Node): boolean => node.kind === ts.SyntaxKind.NullKeyword ||
  (ts.isIdentifier(node) && node.text === "undefined");

export function arrayProvenance(program: ts.Program, checker: ts.TypeChecker, root: string) {
  const sources = program.getSourceFiles().filter(s => s.fileName.startsWith(root));
  const nodes: ts.Node[] = [];
  const collect = (node: ts.Node): void => { nodes.push(node); ts.forEachChild(node, collect); };
  sources.forEach(collect);
  const pin = JSON.parse(readFileSync(new URL("./array-pin.json", import.meta.url), "utf8")) as {
    version: string; node_types_version: string; sqlite_sha256: string;
  };
  const types = JSON.parse(readFileSync(new URL("./node_modules/@types/node/package.json", import.meta.url), "utf8")) as { version: string };
  const sqlite = readFileSync(new URL("./node_modules/@types/node/sqlite.d.ts", import.meta.url));
  if (pin.version !== "sqlite-rows-1" || pin.node_types_version !== types.version ||
      pin.sqlite_sha256 !== createHash("sha256").update(sqlite).digest("hex")) {
    throw new Error("SQLite array API pin mismatch");
  }
  function bound(node: ts.Node): ts.Symbol | undefined {
    const symbol = checker.getSymbolAtLocation(node);
    return symbol?.flags && symbol.flags & ts.SymbolFlags.Alias ? checker.getAliasedSymbol(symbol) : symbol;
  }
  function defs(node: ts.Node): readonly ts.Declaration[] { return bound(node)?.declarations ?? []; }
  function write(node: ts.Node): boolean {
    const parent = node.parent;
    return (ts.isBinaryExpression(parent) && parent.left === node &&
      parent.operatorToken.kind >= ts.SyntaxKind.FirstAssignment && parent.operatorToken.kind <= ts.SyntaxKind.LastAssignment) ||
      ((ts.isPrefixUnaryExpression(parent) || ts.isPostfixUnaryExpression(parent)) &&
       [ts.SyntaxKind.PlusPlusToken, ts.SyntaxKind.MinusMinusToken].includes(parent.operator)) ||
      ts.isDeleteExpression(parent);
  }
  const intact = !nodes.some(node =>
    (ts.isPropertyAccessExpression(node) &&
     ((["map", "includes", "prepare", "all", "get"].includes(node.name.text) && write(node)) ||
      node.name.text === "prototype")) ||
    (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression) &&
     (["setReturnArrays", "getPrototypeOf", "setPrototypeOf", "defineProperty", "defineProperties", "assign"].includes(node.expression.name.text) ||
      (ts.isIdentifier(node.expression.expression) && node.expression.expression.text === "Reflect"))) ||
    (ts.isIdentifier(node) && ["eval", "Function"].includes(node.text)) ||
    (ts.isElementAccessExpression(node) && write(node)));
  function method(node: ts.PropertyAccessExpression, name: "map" | "includes"): boolean {
    const declarations = checker.getSymbolAtLocation(node.name)?.declarations;
    return intact && !node.questionDotToken && node.name.text === name && !!declarations?.length &&
      declarations.every(d => d.getSourceFile().fileName === "/platform/plumb.d.ts");
  }
  function bindingIntact(symbol: ts.Symbol, seen = new Set<ts.Symbol>()): boolean {
    if (seen.has(symbol) || seen.size > 32) return false;
    const next = new Set(seen).add(symbol);
    return nodes.every(node => {
      if (!ts.isIdentifier(node) || checker.getSymbolAtLocation(node) !== symbol) return true;
      const parent = node.parent;
      if ((ts.isVariableDeclaration(parent) || ts.isParameter(parent)) && parent.name === node) return true;
      if (ts.isPropertyAccessExpression(parent) && parent.expression === node &&
          ["map", "includes"].includes(parent.name.text) && ts.isCallExpression(parent.parent) &&
          parent.parent.expression === parent && !parent.questionDotToken && !parent.parent.questionDotToken) return true;
      if (ts.isVariableDeclaration(parent) && parent.initializer === node && ts.isIdentifier(parent.name) &&
          ts.isVariableDeclarationList(parent.parent) && parent.parent.flags & ts.NodeFlags.Const) {
        const alias = checker.getSymbolAtLocation(parent.name);
        return !!alias && bindingIntact(alias, next);
      }
      return false;
    });
  }
  function literal(node: ts.Expression): ts.Node[] | undefined {
    let declaration: ts.VariableDeclaration | undefined;
    if (ts.isIdentifier(node)) {
      const d = defs(node);
      if (d.length !== 1 || !ts.isVariableDeclaration(d[0]!) || !d[0].initializer ||
          !ts.isVariableDeclarationList(d[0].parent) || !(d[0].parent.flags & ts.NodeFlags.Const)) return;
      const symbol = checker.getSymbolAtLocation(d[0].name);
      if (!symbol || !bindingIntact(symbol)) return;
      declaration = d[0]; node = d[0].initializer;
    }
    const array = unwrap(node);
    if (!ts.isArrayLiteralExpression(array) || array.elements.length > 256 ||
        !array.elements.every(e => ts.isStringLiteral(e) || ts.isNumericLiteral(e) ||
          [ts.SyntaxKind.TrueKeyword, ts.SyntaxKind.FalseKeyword, ts.SyntaxKind.NullKeyword].includes(e.kind))) return;
    return declaration ? [declaration, array] : [array];
  }
  function sqliteConstructor(node: ts.Expression): boolean {
    const declarations = checker.getSymbolAtLocation(node)?.declarations;
    return declarations?.length === 1 && ts.isImportSpecifier(declarations[0]!) &&
      (declarations[0].propertyName ?? declarations[0].name).text === "DatabaseSync" &&
      !declarations[0].isTypeOnly && ts.isImportDeclaration(declarations[0].parent.parent.parent) &&
      !declarations[0].parent.parent.isTypeOnly &&
      ts.isStringLiteral(declarations[0].parent.parent.parent.moduleSpecifier) &&
      declarations[0].parent.parent.parent.moduleSpecifier.text === "node:sqlite";
  }
  function databaseUse(node: ts.Node): boolean {
    const parent = node.parent;
    return ts.isReturnStatement(parent) ||
      (ts.isPropertyAccessExpression(parent) && parent.expression === node &&
       ["prepare", "exec", "close"].includes(parent.name.text) &&
       ts.isCallExpression(parent.parent) && parent.parent.expression === parent);
  }
  function factoryIntact(factory: Fn): boolean {
    const name = ts.isArrowFunction(factory) ? undefined : factory.name;
    const symbol = name && bound(name);
    return !!symbol && nodes.every(n => {
      if (!ts.isIdentifier(n) || bound(n) !== symbol || n === name) return true;
      if (ts.isImportSpecifier(n.parent)) return true;
      return ts.isCallExpression(n.parent) && n.parent.expression === n && databaseUse(n.parent);
    });
  }
  function synchronous(callback: Fn): boolean {
    return !ts.getModifiers(callback)?.some(m => m.kind === ts.SyntaxKind.AsyncKeyword) &&
      (ts.isArrowFunction(callback) || !callback.asteriskToken);
  }
  function callableIntact(callable: Fn): boolean {
    const name = ts.isArrowFunction(callable) ? undefined : callable.name;
    if (!name) return ts.isArrowFunction(callable) || ts.isFunctionExpression(callable);
    const symbol = bound(name);
    return !!symbol && nodes.every(n => {
      if (!ts.isIdentifier(n) || bound(n) !== symbol || n === name || ts.isImportSpecifier(n.parent)) return true;
      const call = n.parent;
      return ts.isCallExpression(call) && (call.expression === n ||
        (call.arguments[0] === n && ts.isPropertyAccessExpression(call.expression) && method(call.expression, "map")));
    });
  }
  function database(node: ts.Node, member = "", seen = new Set<ts.Node>()): ts.Node[] | undefined {
    node = unwrap(node);
    if (seen.has(node) || seen.size > 32) return;
    const next = new Set(seen).add(node);
    if (ts.isNewExpression(node) && !member && sqliteConstructor(node.expression)) return [node];
    if (ts.isPropertyAccessExpression(node) && !member) return database(node.expression, node.name.text, next);
    if (ts.isObjectLiteralExpression(node) && member && !node.properties.some(p => ts.isSpreadAssignment(p))) {
      const properties = node.properties.filter(p => (ts.isPropertyAssignment(p) || ts.isShorthandPropertyAssignment(p)) && p.name.getText() === member);
      if (properties.length !== 1) return;
      const property = properties[0]!;
      const value = ts.isPropertyAssignment(property) ? property.initializer : (property as ts.ShorthandPropertyAssignment).name;
      return database(value, "", next);
    }
    if (ts.isIdentifier(node)) {
      const d = defs(node), symbol = bound(node);
      if (d.length !== 1 || !ts.isVariableDeclaration(d[0]!) || !symbol) return;
      const declaration = d[0];
      const values: ts.Node[] = declaration.initializer ? [declaration.initializer] : [];
      for (const reference of nodes) {
        if (!ts.isIdentifier(reference) || bound(reference) !== symbol || reference === declaration.name) continue;
        const parent = reference.parent;
        if (ts.isBinaryExpression(parent) && parent.left === reference && parent.operatorToken.kind === ts.SyntaxKind.EqualsToken) values.push(parent.right);
        else if (ts.isPropertyAccessExpression(parent) && parent.expression === reference && !write(parent) &&
                 (member ? parent.name.text !== member || databaseUse(parent) : databaseUse(reference))) continue;
        else if (ts.isReturnStatement(parent)) continue;
        else if (ts.isPropertyAssignment(parent) && parent.name.getText() === "db" &&
                 ts.isObjectLiteralExpression(parent.parent) &&
                 (ts.isVariableDeclaration(parent.parent.parent) || ts.isBinaryExpression(parent.parent.parent))) {
          const storage = parent.parent.parent;
          const name = ts.isVariableDeclaration(storage) ? storage.name : storage.left;
          if (!ts.isIdentifier(name)) return;
          const storageSymbol = bound(name);
          if (!storageSymbol || nodes.some(n => ts.isIdentifier(n) && bound(n) === storageSymbol &&
              n !== name && !ts.isPropertyAccessExpression(n.parent) &&
              !(ts.isVariableDeclaration(n.parent) && n.parent.name === n) &&
              !(ts.isBinaryExpression(n.parent) && n.parent.left === n))) return;
        }
        else return; // aliases, escapes, compound writes and unknown uses
      }
      const results = values.filter(v => !missing(unwrap(v))).map(v => database(v, member, next));
      if (!results.length || results.some(v => !v)) return;
      return [declaration, ...results.flatMap(v => v!)];
    }
    if (ts.isCallExpression(node) && !node.arguments.length) {
      const d = defs(node.expression);
      if (d.length !== 1 || !fn(d[0]!) || d[0].parameters.length || !d[0].body) return;
      const factory = d[0];
      if (!synchronous(factory) || !factoryIntact(factory)) return;
      const returns: ts.Node[] = [];
      function visit(n: ts.Node): void {
        if (fn(n) && n !== factory) return;
        if (ts.isReturnStatement(n) && n.expression) returns.push(n.expression);
        ts.forEachChild(n, visit);
      }
      visit(factory);
      const results = returns.map(v => database(v, member, next));
      if (!results.length || results.some(v => !v)) return;
      return [factory, ...results.flatMap(v => v!)];
    }
    return;
  }
  function rows(call: ts.CallExpression): ts.Node[] | undefined {
    if (!intact || call.questionDotToken) return;
    const d = defs(call.expression);
    if (d.length !== 1 || !fn(d[0]!) || !d[0].body || !ts.isBlock(d[0].body) ||
        d[0].body.statements.length !== 1 || d[0].parameters.length !== 2) return;
    const wrapper = d[0], sql = wrapper.parameters[0]!, rest = wrapper.parameters[1]!;
    if (!synchronous(wrapper) || !callableIntact(wrapper)) return;
    if (!ts.isIdentifier(sql.name) || !ts.isIdentifier(rest.name) || sql.initializer || rest.initializer ||
        sql.dotDotDotToken || !rest.dotDotDotToken) return;
    const stmt = (wrapper.body as ts.Block).statements[0]!;
    if (!ts.isReturnStatement(stmt) || !stmt.expression) return;
    const result = unwrap(stmt.expression);
    if (!ts.isCallExpression(result) || result.questionDotToken || !ts.isPropertyAccessExpression(result.expression) ||
        result.expression.name.text !== "all" || result.expression.questionDotToken || result.arguments.length !== 1 ||
        !ts.isSpreadElement(result.arguments[0]!) || bound(result.arguments[0].expression) !== bound(rest.name)) return;
    const prepare = result.expression.expression;
    if (!ts.isCallExpression(prepare) || !ts.isPropertyAccessExpression(prepare.expression) ||
        prepare.expression.name.text !== "prepare" || prepare.arguments.length !== 1 ||
        bound(prepare.arguments[0]!) !== bound(sql.name)) return;
    const proof = database(prepare.expression.expression);
    return proof ? [wrapper, ...proof] : undefined;
  }
  function imports(node: ts.Node): ts.Node[] | undefined {
    if (!ts.isIdentifier(node)) return;
    let symbol = checker.getSymbolAtLocation(node);
    const proof: ts.Node[] = [], seen = new Set<ts.Symbol>();
    for (let count = 0; symbol && count < 8; count++) {
      if (seen.has(symbol) || symbol.declarations?.length !== 1) return;
      seen.add(symbol);
      const declaration = symbol.declarations[0]!;
      if (!(symbol.flags & ts.SymbolFlags.Alias)) return proof;
      let statement: ts.ImportDeclaration | ts.ExportDeclaration;
      if (ts.isImportSpecifier(declaration)) {
        if (declaration.isTypeOnly || declaration.parent.parent.isTypeOnly ||
            !ts.isImportDeclaration(declaration.parent.parent.parent)) return;
        statement = declaration.parent.parent.parent;
      } else if (ts.isImportClause(declaration)) {
        if (declaration.isTypeOnly || !ts.isImportDeclaration(declaration.parent)) return;
        statement = declaration.parent;
      } else if (ts.isExportSpecifier(declaration)) {
        statement = declaration.parent.parent;
        if (declaration.isTypeOnly || statement.isTypeOnly) return;
      } else return;
      const next = checker.getImmediateAliasedSymbol(symbol);
      if (statement.moduleSpecifier) {
        const module = checker.getSymbolAtLocation(statement.moduleSpecifier);
        const declarations = module?.declarations;
        if (declarations?.length !== 1 || !ts.isSourceFile(declarations[0]!) ||
            !next?.declarations?.length || next.declarations.some(d => d.getSourceFile() !== declarations[0])) return;
      }
      proof.push(statement);
      symbol = next;
    }
    return;
  }
  function scalar(call: ts.CallExpression): ts.Node[] | undefined {
    if (!intact || call.questionDotToken || call.arguments.some(ts.isSpreadElement)) return;
    const d = defs(call.expression), binding = imports(call.expression);
    if (!binding || d.length !== 1 || !fn(d[0]!) || !d[0].body || !ts.isBlock(d[0].body)) return;
    const wrapper = d[0], params = wrapper.parameters, body = wrapper.body as ts.Block;
    if (!synchronous(wrapper) || !callableIntact(wrapper) || body.statements.length !== 1 ||
        !params.length || params.length > 8 || params.some(p => !ts.isIdentifier(p.name) || p.initializer || p.questionToken) ||
        params[0]!.dotDotDotToken || params.slice(1, -1).some(p => p.dotDotDotToken)) return;
    const rest = !!params.at(-1)!.dotDotDotToken;
    if (rest ? call.arguments.length < params.length - 1 : call.arguments.length !== params.length) return;
    const stmt = body.statements[0]!;
    if (!ts.isReturnStatement(stmt) || !stmt.expression) return;
    const result = unwrap(stmt.expression);
    if (!ts.isCallExpression(result) || result.questionDotToken || !ts.isPropertyAccessExpression(result.expression) ||
        result.expression.questionDotToken || result.expression.name.text !== "get" ||
        result.arguments.length !== params.length - 1) return;
    for (let i = 1; i < params.length; i++) {
      const argument = result.arguments[i - 1]!;
      const spread = ts.isSpreadElement(argument);
      if (spread !== !!params[i]!.dotDotDotToken || bound(spread ? argument.expression : argument) !== bound(params[i]!.name)) return;
    }
    const prepare = result.expression.expression;
    if (!ts.isCallExpression(prepare) || prepare.questionDotToken || !ts.isPropertyAccessExpression(prepare.expression) ||
        prepare.expression.questionDotToken || prepare.expression.name.text !== "prepare" || prepare.arguments.length !== 1 ||
        bound(prepare.arguments[0]!) !== bound(params[0]!.name)) return;
    const receiver = prepare.expression.expression, proof = database(receiver);
    if (!proof) return;
    const factoryBinding = ts.isCallExpression(receiver) ? imports(receiver.expression) : [];
    if (!factoryBinding) return;
    const constructors = proof.filter(ts.isNewExpression);
    const constructorImports = constructors.flatMap(n => {
      const declaration = checker.getSymbolAtLocation(n.expression)?.declarations?.[0];
      return declaration && ts.isImportSpecifier(declaration) ? [declaration.parent.parent.parent] : [];
    });
    return [wrapper, ...binding, ...factoryBinding, ...proof, ...constructorImports];
  }
  return { method, literal, rows, scalar, imports, bindingIntact, synchronous, callableIntact };
}
