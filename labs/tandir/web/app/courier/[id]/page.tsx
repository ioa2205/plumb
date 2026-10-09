import { getDelivery } from "@/lib/dal";

import { DeliveryCard } from "./DeliveryCard";

export default async function DeliveryPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const delivery = await getDelivery(Number(id));
  return <DeliveryCard order={delivery.order} customer={delivery.customer} />;
}
