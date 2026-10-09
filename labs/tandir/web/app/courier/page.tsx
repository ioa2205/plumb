import Link from "next/link";

import { getMyDeliveries } from "@/lib/dal";

export default async function Deliveries() {
  const deliveries = await getMyDeliveries();
  return (
    <>
      <h1>My deliveries</h1>
      {deliveries.length === 0 && <p className="muted">Nothing assigned right now.</p>}
      <ul>
        {deliveries.map((d) => (
          <li key={d.id}>
            <Link href={`/courier/${d.id}`}>Order {d.id}</Link> · {d.status} · {d.deliveryAddress}
          </li>
        ))}
      </ul>
    </>
  );
}
