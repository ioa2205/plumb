import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it } from "vitest";

import { GET as exportCustomers } from "@/app/api/admin/export/route";
import { GET as branchReport } from "@/app/api/admin/reports/route";
import { refundOrder } from "@/app/backoffice/actions";
import { getDelivery, getMyDeliveries, getStaffOrders } from "@/lib/dal";
import { config, proxy } from "@/proxy";

import { NotFound, Redirect } from "./support/interrupts";
import { form, freshLab, orderStatus, signInAs, tokenFor } from "./support/lab";

beforeEach(freshLab);

// The fixed snapshot's export handler reads the request; the lab's ignores it.
const exportHandler = exportCustomers as (request: NextRequest) => Response;

const fixedOnly = describe.runIf(process.env.TANDIR_VARIANT === "fixed");

function request(path: string, username?: string): NextRequest {
  const headers = username ? { cookie: `tandir_session=${tokenFor(username)}` } : undefined;
  return new NextRequest(`http://127.0.0.1:8702${path}`, { headers });
}

describe("courier", () => {
  it("sees their assigned deliveries", async () => {
    signInAs("kamol");
    expect((await getMyDeliveries()).map((d) => d.id)).toEqual([1]);
    const delivery = await getDelivery(1);
    expect(delivery.order.deliveryAddress).toContain("ALICE-MARKER");
    expect(delivery.customer.displayName).toBe("Alice Karimova");
  });

  it("cannot open a delivery that is not theirs", async () => {
    signInAs("kamol");
    await expect(getDelivery(2)).rejects.toBeInstanceOf(NotFound);
  });

  it("is the only role with a delivery view", async () => {
    signInAs("alice");
    await expect(getMyDeliveries()).rejects.toBeInstanceOf(NotFound);
    await expect(getDelivery(1)).rejects.toBeInstanceOf(NotFound);
  });
});

describe("back office", () => {
  it.each([
    ["admin", [1, 2]],
    ["farrukh", [1]],
    ["nodira", [2]],
  ])("shows %s the orders in their scope", async (username, ids) => {
    signInAs(username);
    expect((await getStaffOrders()).map((o) => o.id)).toEqual(ids);
  });

  it.each(["alice", "kamol"])("is not shown to %s", async (username) => {
    signInAs(username);
    await expect(getStaffOrders()).rejects.toBeInstanceOf(NotFound);
  });

  it("sends a signed-out visitor to sign in", async () => {
    await expect(getStaffOrders()).rejects.toBeInstanceOf(Redirect);
  });

  it("lets an admin refund an order", async () => {
    signInAs("admin");
    await refundOrder(form({ orderId: 2 }));
    expect(orderStatus(2)).toBe("refunded");
  });
});

describe("admin report (role checked in the handler)", () => {
  it("answers an admin", async () => {
    const response = branchReport(request("/api/admin/reports", "admin"));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual([
      { branch: "Chilonzor", orders: 1, total_cents: 25800 },
      { branch: "Yunusobod", orders: 1, total_cents: 26500 },
    ]);
  });

  it.each([
    ["farrukh", 403],
    ["alice", 403],
    [undefined, 401],
  ])("refuses %s with %i", (username, status) => {
    expect(branchReport(request("/api/admin/reports", username)).status).toBe(status);
  });
});

describe("admin export (gated by proxy.ts)", () => {
  it("is in the proxy matcher", () => {
    expect(config.matcher).toContain("/api/admin/export");
  });

  it("lets an admin through the proxy to the export", async () => {
    const gate = proxy(request("/api/admin/export", "admin"));
    expect(gate.headers.get("x-middleware-next")).toBe("1");
    const csv = await exportHandler(request("/api/admin/export", "admin")).text();
    expect(csv.split("\n").slice(0, 3)).toEqual([
      "id,name,phone",
      "1,Alice Karimova,'+998 90 111 22 33",
      "2,Bob Tursunov,'+998 90 444 55 66",
    ]);
  });

  it.each([
    ["farrukh", 403],
    ["alice", 403],
    [undefined, 401],
  ])("proxy refuses %s with %i", (username, status) => {
    expect(proxy(request("/api/admin/export", username)).status).toBe(status);
  });
});

// Protections that only the fixed snapshot has (M1.3, ADR-0005); each mirrors its lookalike.

fixedOnly("fixed snapshot: refundOrder is checked in the Data Access Layer", () => {
  it("refuses a signed-out caller", async () => {
    await expect(refundOrder(form({ orderId: 1 }))).rejects.toBeInstanceOf(Redirect);
    expect(orderStatus(1)).toBe("baking");
  });

  it.each(["alice", "kamol"])("refuses %s", async (username) => {
    signInAs(username);
    await expect(refundOrder(form({ orderId: 1 }))).rejects.toBeInstanceOf(NotFound);
    expect(orderStatus(1)).toBe("baking");
  });

  it("keeps a branch manager to their own branch", async () => {
    signInAs("farrukh");
    await expect(refundOrder(form({ orderId: 2 }))).rejects.toBeInstanceOf(NotFound);
    expect(orderStatus(2)).toBe("placed");
    await refundOrder(form({ orderId: 1 }));
    expect(orderStatus(1)).toBe("refunded");
  });
});

fixedOnly("fixed snapshot: the courier page gets a minimal DTO", () => {
  it("passes only what the delivery card shows", async () => {
    signInAs("kamol");
    const delivery = await getDelivery(1);
    expect(Object.keys(delivery.customer)).toEqual(["displayName"]);
  });
});

fixedOnly("fixed snapshot: the export checks the role in the handler", () => {
  it.each([
    ["farrukh", 403],
    ["alice", 403],
    [undefined, 401],
  ])("refuses %s with %i", (username, status) => {
    expect(exportHandler(request("/api/admin/export", username)).status).toBe(status);
  });
});
