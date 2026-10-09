"""Owned source-only controls for §10.2 forms absent from the legacy templates.

Strings are fixtures, not executable lab endpoints. No attack payloads or runtime
tests are included. Each exact rewrite has a human-declared construction label.
"""

from dataclasses import dataclass
from textwrap import dedent

from backend.contracts.common import Family
from eval.mutation.operators import Label


@dataclass(frozen=True)
class Rewrite:
    name: str
    label: Label
    path: str
    before: str
    after: str
    cwe: int

    def apply(self, sources: dict[str, str]) -> dict[str, str] | None:
        if self.path not in sources or sources[self.path].count(self.before) != 1:
            return None
        changed = sources[self.path].replace(self.before, self.after, 1)
        return {**sources, self.path: changed} if changed != sources[self.path] else None


@dataclass(frozen=True)
class Fixture:
    name: str
    family: Family
    entry: str
    sources: dict[str, str]
    rewrites: tuple[Rewrite, ...]


def source(text: str) -> str:
    return dedent(text).lstrip("\n")


ROLE = source("""
    from fastapi import APIRouter, HTTPException
    router = APIRouter()

    @router.post("/orders/{order_id}/approve")
    def approve(order_id, user, db):
        if user.role != "manager":
            raise HTTPException(status_code=403)
        order = db.get(Order, order_id)
        if order is None:
            raise HTTPException(status_code=404)
        if order.tenant_id != user.tenant_id:
            raise HTTPException(status_code=404)
        order.approved = True
        db.commit()
""")

SORT = source("""
    from fastapi import APIRouter, HTTPException
    from sqlalchemy import text
    router = APIRouter()

    @router.get("/orders")
    def ordered(sort, status, db):
        fields = {"date": "created_at", "amount": "total_cents"}
        column = fields.get(sort)
        if column is None:
            raise HTTPException(status_code=400)
        rows = db.execute(
            text(f"SELECT id FROM orders WHERE status = :status ORDER BY {column}"),
            {"status": status},
        )
        return list(rows)
""")

COMMAND = source("""
    import subprocess
    from fastapi import APIRouter
    router = APIRouter()

    @router.post("/preview")
    def preview(text):
        return subprocess.run(["preview-tool", "--", text], shell=False, check=True).returncode
""")

PATH = source("""
    from pathlib import Path
    from fastapi import APIRouter, HTTPException
    from fastapi.responses import FileResponse
    router = APIRouter()
    ROOT = Path("/srv/owned-documents").resolve()

    @router.get("/documents")
    def download(name):
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT):
            raise HTTPException(status_code=404)
        return FileResponse(path)
""")

ACTION = source("""
    "use server";
    import { db } from "./db";
    import { session } from "./session";

    export async function updateOrder(orderId: number) {
      const user = await session();
      const order = await db.order.findUnique({ where: { id: orderId } });
      if (!order || order.ownerId !== user.id) throw new Error("Not found");
      return db.order.update({ where: { id: orderId }, data: { approved: true } });
    }
""")

PROXY = source("""
    import { session } from "./app/orders/session";
    import { db } from "./app/orders/db";
    export async function proxy(request: Request) {
      const user = await session();
      if (!user || !user.id) return new Response("Denied", { status: 403 });
      const orderId = Number(new URL(request.url).searchParams.get("orderId"));
      const order = await db.order.findUnique({ where: { id: orderId } });
      if (!order || order.ownerId !== user.id) return new Response("Denied", { status: 403 });
      return new Response(null, { status: 200 });
    }
""")

PAGE = source("""
    import { db } from "./db";
    import { Details } from "./Details";
    import { session } from "./session";

    export default async function Page() {
      const user = await session();
      const record = await db.order.findFirst({ where: { ownerId: user.id } });
      if (!record) throw new Error("Not found");
      return <Details record={{ id: record.id, amount: record.amount }} />;
    }
""")

CLIENT = source("""
    "use client";
    export function Details({ record }: { record: { id: number; amount: number } }) {
      return <p>{record.amount}</p>;
    }
""")

FIXTURES = (
    Fixture(
        "v2_tenant_role",
        Family.AUTHORIZATION,
        "approve",
        {"api/role.py": ROLE},
        (
            Rewrite(
                "role_without_tenant",
                "vulnerable",
                "api/role.py",
                "    if order.tenant_id != user.tenant_id:\n        raise HTTP"
                "Exception(status_code=404)\n",
                "",
                863,
            ),
        ),
    ),
    Fixture(
        "v2_identifier_order",
        Family.INJECTION,
        "ordered",
        {"api/sort.py": SORT},
        (
            Rewrite(
                "order_by_input",
                "vulnerable",
                "api/sort.py",
                '    fields = {"date": "created_at", "amount": "total_cents"}'
                "\n    column = fields.get(sort)\n    if column is None:\n      "
                "  raise HTTPException(status_code=400)\n",
                "    column = sort\n",
                89,
            ),
            Rewrite(
                "allowlisted_identifiers",
                "safe",
                "api/sort.py",
                '    fields = {"date": "created_at", "amount": "total_cents"}'
                "\n    column = fields.get(sort)\n    if column is None:\n      "
                "  raise HTTPException(status_code=400)\n",
                '    if sort == "date":\n        column = "created_at"\n    eli'
                'f sort == "amount":\n        column = "total_cents"\n    else:'
                "\n        raise HTTPException(status_code=400)\n",
                89,
            ),
        ),
    ),
    Fixture(
        "v2_command_arguments",
        Family.INJECTION,
        "preview",
        {"api/command.py": COMMAND},
        (
            Rewrite(
                "shell_input",
                "vulnerable",
                "api/command.py",
                '["preview-tool", "--", text], shell=False',
                "text, shell=True",
                78,
            ),
            Rewrite(
                "argument_arrays",
                "safe",
                "api/command.py",
                '    return subprocess.run(["preview-tool", "--", text], shel'
                "l=False, check=True).returncode",
                '    arguments = ["preview-tool", "--", text]\n    return subp'
                "rocess.run(arguments, shell=False, check=True).returncode",
                78,
            ),
        ),
    ),
    Fixture(
        "v2_path_containment",
        Family.PATH_TRAVERSAL,
        "download",
        {"api/path.py": PATH},
        (
            Rewrite(
                "unchecked_path_join",
                "vulnerable",
                "api/path.py",
                "    path = (ROOT / name).resolve()\n    if not path.is_relati"
                "ve_to(ROOT):\n        raise HTTPException(status_code=404)\n",
                "    path = ROOT / name\n",
                22,
            ),
            Rewrite(
                "resolve_and_contain",
                "safe",
                "api/path.py",
                "    if not path.is_relative_to(ROOT):\n        raise HTTPExce"
                "ption(status_code=404)\n",
                "    if path != ROOT and ROOT not in path.parents:\n        ra"
                "ise HTTPException(status_code=404)\n",
                22,
            ),
        ),
    ),
    Fixture(
        "v2_action_policy",
        Family.NEXTJS_EXPOSURE,
        "updateOrder",
        {"app/orders/actions.ts": ACTION},
        (
            Rewrite(
                "action_without_authorization",
                "vulnerable",
                "app/orders/actions.ts",
                '  if (!order || order.ownerId !== user.id) throw new Error("Not found");\n',
                "",
                862,
            ),
            Rewrite(
                "dal_check",
                "safe",
                "app/orders/actions.ts",
                "  const order = await db.order.findUnique({ where: { id: ord"
                "erId } });\n  if (!order || order.ownerId !== user.id) throw "
                'new Error("Not found");',
                "  await loadOwnedOrder(orderId, user.id);",
                862,
            ),
        ),
    ),
    Fixture(
        "v2_proxy_only",
        Family.NEXTJS_EXPOSURE,
        "updateOrder",
        {"app/orders/actions.ts": ACTION, "proxy.ts": PROXY},
        (
            Rewrite(
                "proxy_only_protection",
                "vulnerable",
                "app/orders/actions.ts",
                '  if (!order || order.ownerId !== user.id) throw new Error("Not found");\n',
                "",
                862,
            ),
        ),
    ),
    Fixture(
        "v2_client_projection",
        Family.NEXTJS_EXPOSURE,
        "Page",
        {"app/orders/page.tsx": PAGE, "app/orders/Details.tsx": CLIENT},
        (
            Rewrite(
                "over_shared_props",
                "vulnerable",
                "app/orders/page.tsx",
                "record={{ id: record.id, amount: record.amount }}",
                "record={record}",
                200,
            ),
            Rewrite(
                "dto_projection",
                "safe",
                "app/orders/page.tsx",
                "  return <Details record={{ id: record.id, amount: record.amount }} />;",
                "  const dto = { id: record.id, amount: record.amount };\n  re"
                "turn <Details record={dto} />;",
                200,
            ),
        ),
    ),
)

DAL = source("""

    async function loadOwnedOrder(orderId: number, userId: number) {
      const order = await db.order.findUnique({ where: { id: orderId } });
      if (!order || order.ownerId !== userId) throw new Error("Not found");
      return order;
    }
""")
