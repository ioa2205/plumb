/** Framework syntax only. No Next.js import, configuration evaluation or target execution. */
import ts from "typescript";
import { serializationFacts, type SerializationFact } from "./serialization_facts.mts";
import type { FunctionFacts } from "./access_facts.mts";

type Location = { start_line: number; end_line: number };
type SourceLocation = Location & { path: string };
type ClientBinding = { evidence: SourceLocation[]; unknowns: string[] };
type ExportFact = { name: string; target_id: string | null };
type ImportFact = { module: string; path: string | null; type_only: boolean };
type RenderFact = Location & { targets: string[]; tag: string; props: Record<string, string>;
  boundary_evidence: SourceLocation[]; boundary_unknowns: string[] };
export type ModuleFact = {
  path: string; exports: ExportFact[]; imports: ImportFact[];
  matcher: string[] | null; matcher_reason: string;
  renders: RenderFact[]; issues: string[];
  serializations: SerializationFact[];
};

export function frameworkFacts(program: ts.Program, checker: ts.TypeChecker,
  declarationId: (declaration: ts.Declaration) => string | null,
  resolve: (specifier: string, importer: string) => string | null,
  targets: (expression: ts.Expression) => string[], root: string, functions: FunctionFacts[]): ModuleFact[] {
  const location = (node: ts.Node): SourceLocation => {
    const source = node.getSourceFile();
    return { path: source.fileName.slice(root.length),
      start_line: source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1,
      end_line: source.getLineAndCharacterOfPosition(node.getEnd() - 1).line + 1 };
  };
  const writes = new Map<ts.Symbol, boolean>();
  function reassigned(bound: ts.Symbol): boolean {
    const prior = writes.get(bound);
    if (prior !== undefined) return prior;
    let found = false;
    function visit(node: ts.Node): void {
      let left: ts.Expression | undefined;
      if (ts.isBinaryExpression(node) && node.operatorToken.kind >= ts.SyntaxKind.FirstAssignment &&
          node.operatorToken.kind <= ts.SyntaxKind.LastAssignment) left = node.left;
      if ((ts.isPrefixUnaryExpression(node) || ts.isPostfixUnaryExpression(node)) &&
          [ts.SyntaxKind.PlusPlusToken, ts.SyntaxKind.MinusMinusToken].includes(node.operator)) left = node.operand;
      if (left) {
        function matches(node: ts.Node): void {
          if (ts.isIdentifier(node)) {
            let candidate = checker.getSymbolAtLocation(node);
            if (candidate && candidate.flags & ts.SymbolFlags.Alias) candidate = checker.getAliasedSymbol(candidate);
            if (candidate === bound) found = true;
          }
          ts.forEachChild(node, matches);
        }
        matches(left);
      }
      ts.forEachChild(node, visit);
    }
    for (const source of program.getSourceFiles().filter(s => s.fileName.startsWith(root))) visit(source);
    writes.set(bound, found);
    return found;
  }
  function clientBinding(expression: ts.Expression): ClientBinding {
    const evidence: SourceLocation[] = [];
    const unknown = (reason: string): ClientBinding => ({ evidence, unknowns: [reason] });
    const expected = targets(expression);
    if (!ts.isIdentifier(expression) || expected.length !== 1) return unknown("Client module binding is unresolved");
    let bound = checker.getSymbolAtLocation(expression);
    const seen = new Set<ts.Symbol>();
    for (let count = 0; bound && count < 8; count++) {
      if (seen.has(bound) || bound.declarations?.length !== 1) return unknown("Client binding is cyclic or merged");
      seen.add(bound);
      const declaration = bound.declarations[0]!;
      if (!declaration.getSourceFile().fileName.startsWith(root)) return unknown("Client binding is outside frozen source");
      if (bound.flags & ts.SymbolFlags.Alias) {
        let statement: ts.ImportDeclaration | ts.ExportDeclaration | ts.ExportAssignment;
        let specifier: ts.StringLiteral | undefined;
        if (ts.isImportSpecifier(declaration)) {
          const clause = declaration.parent.parent;
          if (declaration.isTypeOnly || clause.isTypeOnly) return unknown("Type-only import cannot establish a client crossing");
          if (!ts.isImportDeclaration(clause.parent)) return unknown("Client import is not executable module source");
          statement = clause.parent;
        } else if (ts.isImportClause(declaration)) {
          if (declaration.isTypeOnly) return unknown("Type-only import cannot establish a client crossing");
          if (!ts.isImportDeclaration(declaration.parent)) return unknown("Client import is not executable module source");
          statement = declaration.parent;
        } else if (ts.isExportSpecifier(declaration)) {
          statement = declaration.parent.parent;
          if (declaration.isTypeOnly || statement.isTypeOnly) return unknown("Type-only export cannot establish a client crossing");
        } else if (ts.isExportAssignment(declaration) && ts.isIdentifier(declaration.expression)) {
          statement = declaration;
        } else return unknown("Client import/export binding is unsupported");
        evidence.push(location(statement));
        if (!ts.isExportAssignment(statement)) {
          if (statement.moduleSpecifier && !ts.isStringLiteral(statement.moduleSpecifier)) return unknown("Client module specifier is unsupported");
          specifier = statement.moduleSpecifier as ts.StringLiteral | undefined;
        }
        const next = checker.getImmediateAliasedSymbol(bound);
        if (specifier) {
          const resolved = resolve(specifier.text, statement.getSourceFile().fileName);
          if (!resolved || next?.declarations?.some(d => d.getSourceFile().fileName !== root + resolved)) {
            return unknown("Client re-export lacks an exact source binding");
          }
        }
        bound = next;
        continue;
      }
      if (declarationId(declaration) !== expected[0] ||
          (!ts.isFunctionDeclaration(declaration) && !ts.isVariableDeclaration(declaration))) {
        return unknown("Client declaration does not match the rendered symbol");
      }
      if ((ts.isVariableDeclaration(declaration) &&
          (!ts.isVariableDeclarationList(declaration.parent) || !(declaration.parent.flags & ts.NodeFlags.Const))) ||
          reassigned(bound)) return unknown("Client callable binding may be modified");
      const source = declaration.getSourceFile();
      let directive: ts.ExpressionStatement | undefined;
      for (const statement of source.statements) {
        if (!ts.isExpressionStatement(statement) || !ts.isStringLiteral(statement.expression)) break;
        if (statement.expression.text === "use client") directive = statement;
      }
      if (!directive) return unknown("Rendered module lacks an executable client directive");
      evidence.push(location(directive));
      // The declaration header binds the symbol without copying its unrelated body.
      const header = location(ts.isVariableDeclaration(declaration) &&
        ts.isVariableStatement(declaration.parent.parent) ? declaration.parent.parent : declaration);
      header.end_line = declaration.name ? location(declaration.name).end_line : header.start_line;
      evidence.push(header);
      return { evidence, unknowns: [] };
    }
    return unknown("Client binding exceeded its source-chain limit");
  }
  const serializations = serializationFacts(program, checker, declarationId, targets, functions, root, clientBinding);
  return program.getSourceFiles().filter(source => source.fileName.startsWith(root)).map(source => {
    const fact: ModuleFact = { path: source.fileName.slice(root.length), exports: [], imports: [],
      matcher: ["/:path*"], matcher_reason: "No matcher: applies to all routes", renders: [], issues: [],
      serializations: serializations.filter(s => s.path === source.fileName.slice(root.length)) };
    const module = checker.getSymbolAtLocation(source);
    for (let symbol of module ? checker.getExportsOfModule(module) : []) {
      const name = symbol.name;
      if (symbol.flags & ts.SymbolFlags.Alias) symbol = checker.getAliasedSymbol(symbol);
      const ids = new Set((symbol.declarations ?? []).map(declarationId));
      fact.exports.push({ name, target_id: ids.size === 1 ? [...ids][0] ?? null : null });
    }
    for (const stmt of source.statements) {
      if (ts.isImportDeclaration(stmt) && ts.isStringLiteral(stmt.moduleSpecifier)) {
        const clause = stmt.importClause;
        const bindings = clause?.namedBindings;
        const typeOnly = !!clause?.isTypeOnly || (!!bindings && ts.isNamedImports(bindings) &&
          !clause?.name && bindings.elements.length > 0 && bindings.elements.every(e => e.isTypeOnly));
        const specifier = stmt.moduleSpecifier.text;
        fact.imports.push({ module: specifier, path: resolve(specifier, source.fileName), type_only: typeOnly });
      }
      if (ts.isExportDeclaration(stmt) && stmt.moduleSpecifier && ts.isStringLiteral(stmt.moduleSpecifier)) {
        const clause = stmt.exportClause;
        const typeOnly = stmt.isTypeOnly || (!!clause && ts.isNamedExports(clause) &&
          clause.elements.length > 0 && clause.elements.every(e => e.isTypeOnly));
        fact.imports.push({ module: stmt.moduleSpecifier.text,
          path: resolve(stmt.moduleSpecifier.text, source.fileName), type_only: typeOnly });
      }
      if (ts.isVariableStatement(stmt)) {
        for (const decl of stmt.declarationList.declarations) {
          if (!ts.isIdentifier(decl.name) || decl.name.text !== "config" ||
              !stmt.modifiers?.some(m => m.kind === ts.SyntaxKind.ExportKeyword)) continue;
          fact.matcher = null;
          fact.matcher_reason = "Dynamic or unsupported proxy matcher";
          let value = decl.initializer;
          while (value && (ts.isAsExpression(value) || ts.isSatisfiesExpression(value) || ts.isParenthesizedExpression(value))) value = value.expression;
          if (!value || !ts.isObjectLiteralExpression(value)) continue;
          // Spreads/accessors/computed properties may overwrite matcher; do not guess.
          if (value.properties.some(p => !ts.isPropertyAssignment(p) || ts.isComputedPropertyName(p.name))) continue;
          const properties = value.properties.filter(p => ts.isPropertyAssignment(p) &&
            (ts.isIdentifier(p.name) || ts.isStringLiteral(p.name)) && p.name.text === "matcher") as ts.PropertyAssignment[];
          if (properties.length === 0) {
            fact.matcher = ["/:path*"]; fact.matcher_reason = "No matcher: applies to all routes";
          } else if (properties.length === 1) {
            const matcher = properties[0]!.initializer;
            const items = ts.isArrayLiteralExpression(matcher) ? [...matcher.elements] : [matcher];
            if (items.every(ts.isStringLiteral)) {
              fact.matcher = items.map(item => item.text);
              fact.matcher_reason = "Literal matcher";
            }
          }
        }
      }
    }
    function visit(node: ts.Node): void {
      if (ts.isJsxSelfClosingElement(node) || ts.isJsxOpeningElement(node)) {
        const tag = node.tagName.getText(source);
        if (tag[0] === tag[0]?.toUpperCase()) {
          const props: Record<string, string> = Object.create(null);
          for (const attribute of node.attributes.properties) {
            if (ts.isJsxSpreadAttribute(attribute)) props[`...${Object.keys(props).length}`] = attribute.expression.getText(source);
            else props[attribute.name.getText(source)] = attribute.initializer?.getText(source) ?? "true";
          }
          const binding = clientBinding(node.tagName as ts.Expression);
          fact.renders.push({ targets: targets(node.tagName as ts.Expression), tag, props,
            boundary_evidence: binding.evidence, boundary_unknowns: binding.unknowns,
            start_line: source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1,
            end_line: source.getLineAndCharacterOfPosition(node.getEnd() - 1).line + 1 });
        }
      }
      if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword) {
        fact.issues.push("Dynamic import: component execution boundary unresolved");
      }
      ts.forEachChild(node, visit);
    }
    visit(source);
    return fact;
  });
}
