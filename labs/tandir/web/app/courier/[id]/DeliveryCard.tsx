"use client";

import { useState } from "react";

import type { CustomerRecord, DeliveryOrder } from "@/lib/dal";

export function DeliveryCard({ order, customer }: { order: DeliveryOrder; customer: CustomerRecord }) {
  const [delivered, setDelivered] = useState(false);
  return (
    <section className="card">
      <h1>Delivery for order {order.id}</h1>
      <p>
        <strong>{customer.displayName}</strong>
      </p>
      <p>{order.deliveryAddress}</p>
      <p className="muted">Status: {delivered ? "marked delivered on this device" : order.status}</p>
      <button type="button" onClick={() => setDelivered(true)}>
        Mark delivered
      </button>
      <p className="muted">Need to reach the customer? Call dispatch; they connect you.</p>
    </section>
  );
}
