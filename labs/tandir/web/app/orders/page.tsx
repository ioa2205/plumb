import Link from "next/link";

import { getMyOrders } from "@/lib/dal";
import { sum } from "@/lib/format";

export default async function MyOrders() {
  const orders = await getMyOrders();
  return (
    <>
      <h1>My orders</h1>
      {orders.length === 0 && <p className="muted">No orders yet.</p>}
      <table>
        <tbody>
          {orders.map((order) => (
            <tr key={order.id}>
              <td>
                <Link href={`/orders/${order.id}`}>Order {order.id}</Link>
              </td>
              <td>{order.branch}</td>
              <td>{order.status}</td>
              <td>{sum(order.totalCents)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
