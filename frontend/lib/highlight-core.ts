import { createHighlighterCore } from "@shikijs/core";
import { createJavaScriptRegexEngine } from "@shikijs/engine-javascript";
import palette from "../tokens.json" with { type: "json" };
import { parseHighlightReply, parseHighlightRequest, type SyntaxToken, type SyntaxTone } from "./highlight-protocol.ts";

const colors=palette.themes.day;
const theme={name:"plumb-listing",type:"light" as const,colors:{"editor.foreground":colors.ink,"editor.background":colors.sheet},settings:[
  {scope:["keyword","storage"],settings:{foreground:colors.ink,fontStyle:"bold"}},
  {scope:["comment"],settings:{foreground:colors.pencil,fontStyle:"italic"}},
  {scope:["string"],settings:{foreground:colors.umber}},
  {scope:["meta.decorator","entity.name.function.decorator","punctuation.definition.annotation"],settings:{foreground:colors.graphite}},
]};
const grammars={python:()=>import("@shikijs/langs/python"),typescript:()=>import("@shikijs/langs/typescript"),tsx:()=>import("@shikijs/langs/tsx"),javascript:()=>import("@shikijs/langs/javascript")};
export async function tokenizeListing(value:unknown):Promise<SyntaxToken[][]|null> {
  const request=parseHighlightRequest(value);if(!request)return null;
  const highlighter=await createHighlighterCore({themes:[theme],langs:[grammars[request.language]()],engine:createJavaScriptRegexEngine()});
  try {
    const tokens=highlighter.codeToTokensBase(request.lines.join("\n"),{lang:request.language,theme:theme.name}).map(line=>line.filter(t=>t.content.length).map(token=>{
      const tone:SyntaxTone=token.color===colors.pencil ? "comment" : token.color===colors.umber ? "string" : token.color===colors.graphite ? "decorator" : (token.fontStyle??0)&2 ? "keyword" : "plain";
      return {text:token.content,tone};
    }));
    return parseHighlightReply({id:request.id,tokens},request.lines,request.id);
  }finally{highlighter.dispose();}
}
