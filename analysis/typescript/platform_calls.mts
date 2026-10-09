/** A tiny, hash-pinned platform declaration subset; reviewed sources stay in memory. */
import ts from "typescript";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";

export type PlatformOperation = "number_conversion" | "form_data_read";
const PLATFORM = "/platform/plumb.d.ts";

export function platformSource(): { source: ts.SourceFile; identity: string } {
  const manifest = readFileSync(new URL("./platform-pin.json", import.meta.url));
  const pin = JSON.parse(manifest.toString("utf8")) as {
    version: string; typescript: string; files: Record<string, string>;
  };
  if (pin.version !== "typescript-platform-2" || pin.typescript !== ts.version) {
    throw new Error("Platform declaration version differs from the compiler");
  }
  const declarations: string[] = [];
  for (const name of ["lib.es5.d.ts", "lib.dom.d.ts", "lib.es2016.array.include.d.ts"]) {
    const bytes = readFileSync(new URL(`./node_modules/typescript/lib/${name}`, import.meta.url));
    if (createHash("sha256").update(bytes).digest("hex") !== pin.files[name]) {
      throw new Error(`Platform declaration hash mismatch: ${name}`);
    }
    const library = ts.createSourceFile(name, bytes.toString("utf8"), ts.ScriptTarget.Latest, true);
    for (const statement of library.statements) {
      if (ts.isInterfaceDeclaration(statement) && ["Array", "ReadonlyArray"].includes(statement.name.text)) {
        const members = statement.members.filter(m => ts.isIndexSignatureDeclaration(m) ||
          (ts.isMethodSignature(m) && ts.isIdentifier(m.name) && ["map", "includes"].includes(m.name.text)));
        if (!members.length) throw new Error("Incomplete platform array signature");
        declarations.push(`interface ${statement.name.text}<T> { ${members.map(m => m.getText(library)).join("\n")} }`);
      } else if (ts.isInterfaceDeclaration(statement) && statement.name.text === "NumberConstructor") {
        const calls = statement.members.filter(ts.isCallSignatureDeclaration);
        if (calls.length !== 1) throw new Error("Ambiguous Number platform signature");
        declarations.push(`interface NumberConstructor { ${calls[0]!.getText(library)} }`);
      } else if (ts.isInterfaceDeclaration(statement) && statement.name.text === "FormData") {
        const getters = statement.members.filter(m => ts.isMethodSignature(m) &&
          ts.isIdentifier(m.name) && m.name.text === "get");
        if (getters.length > 1) throw new Error("Ambiguous FormData platform signature");
        if (getters.length) declarations.push(`interface FormData { ${getters[0]!.getText(library)} }`);
      } else if (ts.isTypeAliasDeclaration(statement) && statement.name.text === "FormDataEntryValue") {
        declarations.push(statement.getText(library));
      } else if (ts.isVariableStatement(statement) && statement.declarationList.declarations.some(
        d => ts.isIdentifier(d.name) && ["Number", "FormData"].includes(d.name.text))) {
        declarations.push(statement.getText(library));
      }
    }
  }
  if (declarations.length !== 9) throw new Error("Incomplete platform declaration subset");
  return {
    source: ts.createSourceFile(PLATFORM, declarations.join("\n"), ts.ScriptTarget.Latest, true),
    identity: createHash("sha256").update(manifest).digest("hex"),
  };
}

export function platformCalls(program: ts.Program, checker: ts.TypeChecker,
  platform: ts.SourceFile): (expression: ts.Expression) => PlatformOperation | undefined {
  const sources = program.getSourceFiles().filter(s => s !== platform);
  const intactGlobals = new Map<string, boolean>();

  function trusted(node: ts.Node, name: string): boolean {
    const symbol = checker.getSymbolAtLocation(node);
    return symbol?.name === name && !!symbol.declarations?.length &&
      symbol.declarations.every(d => d.getSourceFile() === platform);
  }
  function globalIntact(name: "Number" | "FormData"): boolean {
    const cached = intactGlobals.get(name);
    if (cached !== undefined) return cached;
    let intact = true;
    function visit(node: ts.Node): void {
      // Computed/dotted global mutation cannot be proven absent from an arbitrary
      // dynamic global object. Refuse these explicit global accesses conservatively.
      const globalObjects = ["globalThis", "window", "self", "global"];
      if (ts.isPropertyAccessExpression(node) && globalObjects.includes(node.expression.getText()) &&
          [name, "eval"].includes(node.name.text)) intact = false;
      if (ts.isElementAccessExpression(node) && globalObjects.includes(node.expression.getText())) intact = false;
      if ((ts.isCallExpression(node) || ts.isNewExpression(node)) && ts.isIdentifier(node.expression) &&
          ["eval", "Function"].includes(node.expression.text)) intact = false;
      if (ts.isIdentifier(node) && trusted(node, name)) {
        const parent = node.parent;
        const direct = ts.isCallExpression(parent) && parent.expression === node;
        const type = ts.isTypeReferenceNode(parent) && parent.typeName === node;
        const construct = name === "FormData" && ts.isNewExpression(parent) && parent.expression === node;
        if (!direct && !type && !construct) intact = false;
      }
      ts.forEachChild(node, visit);
    }
    for (const source of sources) visit(source);
    intactGlobals.set(name, intact);
    return intact;
  }
  function formRead(expression: ts.Expression): boolean {
    if (!ts.isPropertyAccessExpression(expression) || expression.questionDotToken || expression.name.text !== "get" ||
        !ts.isIdentifier(expression.expression) || !trusted(expression.name, "get") ||
        !globalIntact("FormData")) return false;
    const call = expression.parent;
    if (!ts.isCallExpression(call) || call.expression !== expression || call.questionDotToken ||
        call.arguments.length !== 1 || !ts.isStringLiteral(call.arguments[0]!)) return false;
    const receiver = checker.getSymbolAtLocation(expression.expression);
    const declarations = receiver?.declarations ?? [];
    if (declarations.length !== 1 || !ts.isParameter(declarations[0]!)) return false;
    const parameter = declarations[0] as ts.ParameterDeclaration;
    if (!ts.isIdentifier(parameter.name) || parameter.initializer || parameter.dotDotDotToken ||
        parameter.questionToken || !parameter.type || !ts.isTypeReferenceNode(parameter.type) ||
        !ts.isIdentifier(parameter.type.typeName) || !trusted(parameter.type.typeName, "FormData")) return false;
    const owner = parameter.parent;
    if (!ts.isFunctionDeclaration(owner) || !owner.body) return false;
    let intact = true;
    function visit(node: ts.Node): void {
      if (ts.isIdentifier(node) && checker.getSymbolAtLocation(node) === receiver && node !== parameter.name) {
        const access = node.parent;
        const use = access.parent;
        // No aliases, escapes, reassignment, casts, optional/computed calls or other
        // receiver operations. Closure capture is not a proven direct input read.
        if (!ts.isPropertyAccessExpression(access) || access.expression !== node ||
            access.name.text !== "get" || !ts.isCallExpression(use) ||
            use.expression !== access || use.questionDotToken || use.arguments.length !== 1 ||
            !ts.isStringLiteral(use.arguments[0]!)) intact = false;
        for (let parent = node.parent; parent && parent !== owner; parent = parent.parent) {
          if (ts.isFunctionLike(parent)) intact = false;
        }
      }
      ts.forEachChild(node, visit);
    }
    visit(owner.body);
    return intact;
  }
  return expression => {
    if (formRead(expression)) return "form_data_read";
    if (!ts.isIdentifier(expression) || !trusted(expression, "Number") || !globalIntact("Number")) return;
    const call = expression.parent;
    if (!ts.isCallExpression(call) || call.expression !== expression || call.questionDotToken ||
        call.arguments.length !== 1 || call.typeArguments?.length) return;
    const value = call.arguments[0]!;
    if (ts.isStringLiteral(value) || ts.isNumericLiteral(value) ||
        (ts.isCallExpression(value) && formRead(value.expression))) return "number_conversion";
  };
}
