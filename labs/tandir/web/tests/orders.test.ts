import { beforeEach, describe, expect, it } from "vitest";

import { cancelOrder } from "@/app/orders/actions";
import { getMyOrders, getOrderDTO, getStorefront } from "@/lib/dal";

import { NotFound, Redirect } from "./support/interrupts";
import { form, freshLab, orderStatus, signInAs } from "./support/lab";

beforeEach(freshLab);

describe("storefront", () => {
  it("lists both branches with their available menus", () => {
    const branches = getStorefront();
    expect(branches.map((b) => b.name)).toEqual(["Chilonzor", "Yunusobod"]);
    expect(branches[0]?.menu.map((i) => i.name)).toEqual(["Samsa", "Napoleon cake"]);
  });
});

describe("customer orders", () => {
  it("lists only the signed-in customer's orders", async () => {
    signInAs("alice");
    expect((await getMyOrders()).map((o) => o.id)).toEqual([1]);
    signInAs("bob");
    expect((await getMyOrders()).map((o) => o.id)).toEqual([2]);
  });

  it("sends a signed-out visitor to sign in", async () => {
    await expect(getMyOrders()).rejects.toEqual(new Redirect("/login"));
    await expect(getOrderDTO(1)).rejects.toBeInstanceOf(Redirect);
  });

  it("gives the order page a minimal DTO of the owner's order", async () => {
    signInAs("alice");
    const order = await getOrderDTO(1);
    expect(Object.keys(order).sort()).toEqual([
      "branch",
      "cancellable",
      "deliveryAddress",
      "id",
      "items",
      "status",
      "totalCents",
    ]);
    expect(order.deliveryAddress).toContain("ALICE-MARKER");
    expect(order.items.map((i) => i.name)).toEqual(["Samsa", "Napoleon cake"]);
    expect(order.cancellable).toBe(true);
  });

  it("does not show another customer's order", async () => {
    signInAs("bob");
    await expect(getOrderDTO(1)).rejects.toBeInstanceOf(NotFound);
    await expect(getOrderDTO(999)).rejects.toBeInstanceOf(NotFound);
  });
});

describe("cancelOrder (Server Action, checked in the Data Access Layer)", () => {
  it("lets the owner cancel once", async () => {
    signInAs("alice");
    await cancelOrder(form({ orderId: 1 }));
    expect(orderStatus(1)).toBe("cancelled");
    await expect(cancelOrder(form({ orderId: 1 }))).rejects.toBeInstanceOf(NotFound);
  });

  it("refuses another customer and leaves the order alone", async () => {
    signInAs("bob");
    await expect(cancelOrder(form({ orderId: 1 }))).rejects.toBeInstanceOf(NotFound);
    expect(orderStatus(1)).toBe("baking");
  });

  it("refuses a signed-out caller", async () => {
    await expect(cancelOrder(form({ orderId: 2 }))).rejects.toBeInstanceOf(Redirect);
    expect(orderStatus(2)).toBe("placed");
  });
});
