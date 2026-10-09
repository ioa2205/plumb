"use client";

import type { OrderDTO } from "@/lib/dal";
import { sum } from "@/lib/format";

import { cancelOrder } from "../actions";

export function OrderSummary({ order }: { order: OrderDTO }) {
  return (
    <section className="card">
      <h1>Order {order.id}</h1>
      <p>
        {order.branch} · <strong>{order.status}</strong>
      </p>
      <p className="muted">Deliver to {order.deliveryAddress}</p>
      <ul>
        {order.items.map((item, index) => (
          <li key={index}>
            {item.quantity} × {item.name}
            {item.inscription && <span className="muted"> · “{item.inscription}”</span>}
          </li>
        ))}
      </ul>
      <p>Total {sum(order.totalCents)}</p>
      {order.cancellable && (
        <form action={cancelOrder}>
          <input type="hidden" name="orderId" value={order.id} />
          <button type="submit">Cancel order</button>
        </form>
      )}
    </section>
  );
}
