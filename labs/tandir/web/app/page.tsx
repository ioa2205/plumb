import { getStorefront } from "@/lib/dal";
import { sum } from "@/lib/format";

export const dynamic = "force-dynamic";

export default function Storefront() {
  const branches = getStorefront();
  return (
    <>
      <h1>Fresh from the tandir</h1>
      {branches.map((branch) => (
        <section className="card" key={branch.id}>
          <h2>
            {branch.name} <span className="muted">· {branch.city}</span>
          </h2>
          <p className="muted">
            Open {branch.opensAt}–{branch.closesAt}
          </p>
          <ul>
            {branch.menu.map((item) => (
              <li key={item.id}>
                {item.name} · {sum(item.priceCents)}
              </li>
            ))}
          </ul>
        </section>
      ))}
    </>
  );
}
