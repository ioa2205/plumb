export type GlyphName = "dot" | "ring" | "half" | "slash" | "plumb";

export function GlyphSprite() {
  return <svg width="0" height="0" className="glyph-sprite" aria-hidden="true">
    <symbol id="g-dot" viewBox="0 0 12 12"><circle cx="6" cy="6" r="4.6" fill="currentColor" /></symbol>
    <symbol id="g-ring" viewBox="0 0 12 12"><circle cx="6" cy="6" r="4.1" fill="none" stroke="currentColor" strokeWidth="1.5" /></symbol>
    <symbol id="g-half" viewBox="0 0 12 12"><circle cx="6" cy="6" r="4.1" fill="none" stroke="currentColor" strokeWidth="1.5" /><path d="M6 1.9a4.1 4.1 0 0 1 0 8.2z" fill="currentColor" /></symbol>
    <symbol id="g-slash" viewBox="0 0 12 12"><circle cx="6" cy="6" r="4.1" fill="none" stroke="currentColor" strokeWidth="1.5" /><path d="M2.6 9.4 9.4 2.6" stroke="currentColor" strokeWidth="1.5" /></symbol>
    <symbol id="g-plumb" viewBox="0 0 10 22"><path d="M5 0v12" stroke="currentColor" strokeWidth="1.6" /><path d="M5 11.5 8.6 16 5 21.5 1.4 16z" fill="currentColor" /></symbol>
  </svg>;
}

/** Decorative next to a mandatory visible word; never communicates state alone. */
export function Glyph({ name }: { name: GlyphName }) {
  return <svg className={name === "plumb" ? "plumb-mark" : "glyph"} aria-hidden="true"><use href={`#g-${name}`} /></svg>;
}
