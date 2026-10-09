import "server-only";

import { cookies } from "next/headers";
import { notFound, redirect } from "next/navigation";
import { cache } from "react";

import { all, one, run } from "./db";
import { SESSION_COOKIE, STAFF, type Viewer, viewerForToken } from "./sessions";

// Data Access Layer: reads and mutations that check who is asking.

export const getViewer = cache(async (): Promise<Viewer | null> => {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  return viewerForToken(token);
});

export async function verifySession(): Promise<Viewer> {
  const viewer = await getViewer();
  if (!viewer) redirect("/login");
  return viewer;
}

// Storefront (public)

export type MenuItemDTO = { id: number; name: string; priceCents: number };
export type BranchDTO = {
  id: number;
  name: string;
  city: string;
  opensAt: string;
  closesAt: string;
  menu: MenuItemDTO[];
};

export function getStorefront(): BranchDTO[] {
  const branches = all<{ id: number; name: string; city: string; opens_at: string; closes_at: string }>(
    "SELECT id, name, city, opens_at, closes_at FROM branches ORDER BY id",
  );
  const items = all<{ id: number; branch_id: number; name: string; price_cents: number }>(
    "SELECT id, branch_id, name, price_cents FROM menu_items WHERE available = 1 ORDER BY id",
  );
  return branches.map((b) => ({
    id: b.id,
    name: b.name,
    city: b.city,
    opensAt: b.opens_at,
    closesAt: b.closes_at,
    menu: items
      .filter((i) => i.branch_id === b.id)
      .map((i) => ({ id: i.id, name: i.name, priceCents: i.price_cents })),
  }));
}

// Customer orders

export type OrderLineDTO = {
  name: string;
  quantity: number;
  unitPriceCents: number;
  inscription: string | null;
};

export type OrderDTO = {
  id: number;
  status: string;
  branch: string;
  deliveryAddress: string;
  totalCents: number;
  cancellable: boolean;
  items: OrderLineDTO[];
};

const CANCELLABLE = ["placed", "baking"];

type OrderRow = {
  id: number;
  status: string;
  branch: string;
  delivery_address: string;
  total_cents: number;
};

function orderLines(orderId: number): OrderLineDTO[] {
  return all<{ name: string; quantity: number; unit_price_cents: number; inscription: string | null }>(
    "SELECT name, quantity, unit_price_cents, inscription FROM order_items WHERE order_id = ? ORDER BY id",
    orderId,
  ).map((i) => ({
    name: i.name,
    quantity: i.quantity,
    unitPriceCents: i.unit_price_cents,
    inscription: i.inscription,
  }));
}

function toOrderDTO(row: OrderRow): OrderDTO {
  return {
    id: row.id,
    status: row.status,
    branch: row.branch,
    deliveryAddress: row.delivery_address,
    totalCents: row.total_cents,
    cancellable: CANCELLABLE.includes(row.status),
    items: orderLines(row.id),
  };
}

const ORDER_SELECT = `SELECT orders.id, orders.status, branches.name AS branch,
                             orders.delivery_address, orders.total_cents
                        FROM orders JOIN branches ON branches.id = orders.branch_id`;

export async function getMyOrders(): Promise<OrderDTO[]> {
  const viewer = await verifySession();
  return all<OrderRow>(`${ORDER_SELECT} WHERE orders.customer_id = ? ORDER BY orders.id`, viewer.id).map(
    toOrderDTO,
  );
}

/** The order page's data: only the signed-in customer's own order, as a minimal DTO. */
export async function getOrderDTO(orderId: number): Promise<OrderDTO> {
  const viewer = await verifySession();
  const row = one<OrderRow>(
    `${ORDER_SELECT} WHERE orders.id = ? AND orders.customer_id = ?`,
    orderId,
    viewer.id,
  );
  if (!row) notFound();
  return toOrderDTO(row);
}

export async function cancelOrderFor(orderId: number): Promise<void> {
  const viewer = await verifySession();
  const changed = run(
    `UPDATE orders SET status = 'cancelled'
      WHERE id = ? AND customer_id = ? AND status IN ('placed', 'baking')`,
    orderId,
    viewer.id,
  );
  if (changed === 0) notFound();
}

// Courier

export type DeliveryOrder = { id: number; status: string; deliveryAddress: string };

export type CustomerRecord = {
  id: number;
  username: string;
  displayName: string;
  phone: string;
  avatar: string | null;
  phoneHistory: { phone: string; changedAt: string }[];
};

export async function getMyDeliveries(): Promise<DeliveryOrder[]> {
  const viewer = await verifySession();
  if (!viewer.is("courier")) notFound();
  return all<{ id: number; status: string; delivery_address: string }>(
    "SELECT id, status, delivery_address FROM orders WHERE courier_id = ? ORDER BY id",
    viewer.id,
  ).map((o) => ({ id: o.id, status: o.status, deliveryAddress: o.delivery_address }));
}

function customerRecord(customerId: number): CustomerRecord {
  const user = one<{ id: number; username: string; display_name: string; phone: string; avatar: string | null }>(
    "SELECT id, username, display_name, phone, avatar FROM users WHERE id = ?",
    customerId,
  );
  if (!user) notFound();
  const history = all<{ phone: string; changed_at: string }>(
    "SELECT phone, changed_at FROM phone_changes WHERE user_id = ? ORDER BY changed_at",
    customerId,
  );
  return {
    id: user.id,
    username: user.username,
    displayName: user.display_name,
    phone: user.phone,
    avatar: user.avatar,
    phoneHistory: history.map((h) => ({ phone: h.phone, changedAt: h.changed_at })),
  };
}

/** A delivery assigned to the signed-in courier, with the customer's record. */
export async function getDelivery(
  orderId: number,
): Promise<{ order: DeliveryOrder; customer: CustomerRecord }> {
  const viewer = await verifySession();
  if (!viewer.is("courier")) notFound();
  const order = one<{ id: number; status: string; delivery_address: string; customer_id: number }>(
    "SELECT id, status, delivery_address, customer_id FROM orders WHERE id = ? AND courier_id = ?",
    orderId,
    viewer.id,
  );
  if (!order) notFound();
  return {
    order: { id: order.id, status: order.status, deliveryAddress: order.delivery_address },
    customer: customerRecord(order.customer_id),
  };
}

// Back office

export type StaffOrderDTO = {
  id: number;
  customer: string;
  branch: string;
  status: string;
  totalCents: number;
};

const STAFF_ORDER_SELECT = `SELECT orders.id, users.display_name AS customer,
                                   branches.name AS branch, orders.status, orders.total_cents
                              FROM orders
                              JOIN users ON users.id = orders.customer_id
                              JOIN branches ON branches.id = orders.branch_id`;

type StaffOrderRow = { id: number; customer: string; branch: string; status: string; total_cents: number };

/** Admins see every order; a branch manager sees their own branch's. */
export async function getStaffOrders(): Promise<StaffOrderDTO[]> {
  const viewer = await verifySession();
  if (!viewer.is(...STAFF)) notFound();
  const rows = viewer.is("admin")
    ? all<StaffOrderRow>(`${STAFF_ORDER_SELECT} ORDER BY orders.id`)
    : all<StaffOrderRow>(
        `${STAFF_ORDER_SELECT} WHERE orders.branch_id = ? ORDER BY orders.id`,
        viewer.branchId,
      );
  return rows.map((o) => ({
    id: o.id,
    customer: o.customer,
    branch: o.branch,
    status: o.status,
    totalCents: o.total_cents,
  }));
}
