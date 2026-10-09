import type { SnapshotCodePage } from "../generated/contracts";

export type SyntaxTone="plain"|"keyword"|"comment"|"decorator"|"string";
export type SyntaxToken={text:string;tone:SyntaxTone};
export type HighlightRequest={id:number;language:NonNullable<SnapshotCodePage["language"]>;lines:readonly string[]};
export const MAX_HIGHLIGHT_BYTES=64*1024;
export const MAX_HIGHLIGHT_TOKENS=4096;
const languages=new Set(["python","typescript","tsx","javascript"]);
const tones=new Set(["plain","keyword","comment","decorator","string"]);
function record(value:unknown):value is Record<string,unknown> {return value!==null&&typeof value==="object"&&!Array.isArray(value);}
export function parseHighlightRequest(value:unknown):HighlightRequest|null {
  if(!record(value)||Object.keys(value).some(k=>!["id","language","lines"].includes(k))||!Number.isSafeInteger(value.id)||Number(value.id)<1
    ||typeof value.language!=="string"||!languages.has(value.language)||!Array.isArray(value.lines)||value.lines.length<1||value.lines.length>80
    ||value.lines.some(line=>typeof line!=="string"||line.length>4096||line.includes("\n"))
    ||new TextEncoder().encode(value.lines.join("\n")).byteLength>MAX_HIGHLIGHT_BYTES)return null;
  return value as HighlightRequest;
}
/** A worker may supply only bounded classes and the exact text it received. */
export function parseHighlightReply(value:unknown,lines:readonly string[],id:number):SyntaxToken[][]|null {
  if(!record(value)||Object.keys(value).some(k=>!["id","tokens"].includes(k))||value.id!==id||!Array.isArray(value.tokens)||value.tokens.length!==lines.length)return null;
  let count=0;const result:SyntaxToken[][]=[];
  for(let i=0;i<lines.length;i++) {
    const row=value.tokens[i];if(!Array.isArray(row))return null;count+=row.length;if(count>MAX_HIGHLIGHT_TOKENS)return null;
    if(row.some(t=>!record(t)||Object.keys(t).some(k=>!["text","tone"].includes(k))||typeof t.text!=="string"||typeof t.tone!=="string"||!tones.has(t.tone)))return null;
    const tokens=row as SyntaxToken[];if(tokens.map(t=>t.text).join("")!==lines[i])return null;result.push(tokens);
  }
  return result;
}
