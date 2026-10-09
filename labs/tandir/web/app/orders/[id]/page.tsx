import { getOrderDTO } from "@/lib/dal";

import { OrderSummary } from "./OrderSummary";

export default async function OrderPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const order = await getOrderDTO(Number(id));
  return <OrderSummary order={order} />;
}
