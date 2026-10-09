import { Glyph, type GlyphName } from "../../components/Glyph";
import { ThemeSelect } from "../../components/ThemeSelect";
import tokens from "../../tokens.json";
import styles from "./page.module.css";

const marks: { glyph: GlyphName; word: string; meaning: string }[] = [
  { glyph: "dot", word: "Established", meaning: "Supported by executable evidence." },
  { glyph: "ring", word: "Not established", meaning: "Absent from the evidence inspected." },
  { glyph: "half", word: "Inconclusive", meaning: "The evidence does not settle the question." },
  { glyph: "slash", word: "Rejected", meaning: "An executable protection is cited." },
];

export default function Foundation() {
  return <div className={styles.desk}>
    <a className="skip-link" href="#foundation">Skip to content</a>
    <header className={styles.header}>
      <span className={styles.wordmark}><Glyph name="plumb" />plumb</span>
      <ThemeSelect />
    </header>
    <main id="foundation" tabIndex={-1} className={styles.sheet}>
      <p className={styles.meta}>Design foundation · interface samples</p>
      <h1>Clear marks.<br />Readable evidence.</h1>
      <p className={styles.lede}>Ink records what the evidence establishes. Blue pencil marks a proposal. Red pencil shows a deviation. Every mark has a word.</p>
      <p className={styles.notice}>No project or review is loaded. These samples describe the interface, not a security result.</p>

      <section aria-labelledby="meaning-title" className={styles.section}>
        <h2 id="meaning-title">What each mark means</h2>
        <div className={styles.marks}>{marks.map(mark => <div key={mark.glyph}>
          <h3><Glyph name={mark.glyph} />{mark.word}</h3><p>{mark.meaning}</p>
        </div>)}</div>
        <div className={styles.conditions}>
          <p className={styles.proposed}><Glyph name="half" /><strong>Proposed</strong><span>Inferred, awaiting evidence or confirmation.</span></p>
          <p className={styles.deviation}><Glyph name="ring" /><strong>Deviation</strong><span>Out of true with a source-supported peer rule.</span></p>
          <p className={styles.condition}><strong>Attention needed</strong><span>A condition with a reason and a next action.</span></p>
        </div>
      </section>

      <section aria-labelledby="type-title" className={styles.section}>
        <h2 id="type-title">Identifiers you can tell apart</h2>
        <p>Atkinson Hyperlegible Next for reading; Mono for code and locations. Both are served with the app.</p>
        <p className={styles.specimen}>l 1 I · O 0 · rn m</p>
        <pre className={styles.code}><code><b>if</b> order.customer_id != user.id:<br />{"    "}<b>raise</b> AccessDenied()</code></pre>
        <p className={styles.meta}>Typography sample only. No analyzed source or citation.</p>
      </section>

      <section aria-labelledby="surface-title" className={styles.section}>
        <h2 id="surface-title">Surfaces and color roles</h2>
        <p>Space, alignment and tone separate the page. Color carries a meaning.</p>
        <dl className={styles.palette}>{Object.keys(tokens.themes.day).map(name => <div key={name}>
          <dt><span className={`${styles.swatch} token-swatch`} data-token={name} />{name}</dt>
          <dd><code>{tokens.themes.day[name as keyof typeof tokens.themes.day]}</code><span>Day</span><code>{tokens.themes.night[name as keyof typeof tokens.themes.night]}</code><span>Night</span></dd>
        </div>)}</dl>
      </section>
      <footer className={styles.section}><p className={styles.meta}>Foundation only. Project, review, case files and run history are still being built.</p></footer>
    </main>
  </div>;
}
