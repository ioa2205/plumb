import { getStaffOrders } from "@/lib/dal";
import { sum } from "@/lib/format";

import { refundOrder } from "./actions";

export default async function BackOffice() {
  const orders = await getStaffOrders();
  return (
    <>
      <h1>Back office</h1>
      <p>
        <a href="/api/admin/reports">Branch report (JSON)</a> ·{" "}
        <a href="/api/admin/export">Customer export (CSV)</a>
      </p>
      <table>
        <thead>
          <tr>
            <th>Order</th>
            <th>Customer</th>
            <th>Branch</th>
            <th>Status</th>
            <th>Total</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {orders.map((order) => (
            <tr key={order.id}>
              <td>{order.id}</td>
              <td>{order.customer}</td>
              <td>{order.branch}</td>
              <td>{order.status}</td>
              <td>{sum(order.totalCents)}</td>
              <td>
                {order.status !== "refunded" && (
                  <form action={refundOrder}>
                    <input type="hidden" name="orderId" value={order.id} />
                    <button type="submit">Refund</button>
                  </form>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
