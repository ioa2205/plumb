"use server";

import { revalidatePath } from "next/cache";

import { cancelOrderFor } from "@/lib/dal";

export async function cancelOrder(formData: FormData): Promise<void> {
  const orderId = Number(formData.get("orderId"));
  await cancelOrderFor(orderId);
  revalidatePath(`/orders/${orderId}`);
}
