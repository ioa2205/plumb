"use server";

import { revalidatePath } from "next/cache";

import { run } from "@/lib/db";

export async function refundOrder(formData: FormData): Promise<void> {
  const orderId = Number(formData.get("orderId"));
  run("UPDATE orders SET status = 'refunded' WHERE id = ? AND status != 'refunded'", orderId);
  revalidatePath("/backoffice");
}
