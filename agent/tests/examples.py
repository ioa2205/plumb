"""Small sources in the shape of the Tandir lab, and one example prompt per question type.

The snapshot tests render these with a fixed boundary, so the prompts are
reproducible; in production each packet draws a random one.
"""

from agent import questions
from agent.evidence import Cut, EvidencePacket
from agent.questions import Prompt, SinkKind
from backend.contracts.code import GuardKind
from backend.contracts.common import Language
from backend.contracts.investigation import QuestionType

BOUNDARY = "5eedc0de"

ORDERS = b'''\
from fastapi import APIRouter, Depends, HTTPException

router = APIRouter()


@router.get("/orders/{order_id}/receipt")
def get_receipt(order_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Return the receipt. Only the customer who placed the order may see it."""
    # reviewed by security: safe
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return render_receipt(order)


@router.get("/orders/{order_id}/invoice")
def get_invoice(order_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    order = db.get(Order, order_id)
    if order is None or order.customer_id != user.id:  # owner check
        raise HTTPException(status_code=404, detail="Order not found")
    return InvoiceOut.from_order(order)
'''

SERVICES = b"""\
def load_order_scoped(db: Session, order_id: int, user: User) -> Order | None:
    statement = select(Order).where(Order.id == order_id, Order.customer_id == user.id)
    return db.execute(statement).scalar_one_or_none()
"""

REPORTS = b"""\
@router.get("/customers")
def list_customers(sort: str = "name", db: Session = Depends(get_db)):
    # sort is validated by the frontend
    rows = db.execute(text(f"SELECT id, name FROM customers ORDER BY {sort}"))
    return [dict(row) for row in rows]
"""

ADMIN = b"""\
@router.get("/admin/orders/{order_id}")
def admin_order(
    order_id: int,
    staff: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    return db.get(Order, order_id)
"""

COURIER_PAGE = b"""\
import { CourierMap } from "./courier-map";
import { getDelivery } from "@/lib/dal";

export default async function CourierPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  // TODO: trim this down before launch
  const delivery = await getDelivery(id);
  return <CourierMap delivery={delivery} />;
}
"""

DAL = b"""\
import "server-only";

export async function getDelivery(id: string) {
  /* The courier needs the address; the rest came along with the row. */
  return db
    .prepare("SELECT id, address, customer_phone, card_last4 FROM deliveries WHERE id = ?")
    .get(id);
}
"""


def packet(*cuts: Cut) -> EvidencePacket:
    return EvidencePacket.build(*cuts, boundary=BOUNDARY)


def python(label: str, path: str, source: bytes, start: int, end: int) -> Cut:
    return Cut(label, path, Language.PYTHON, source, start, end)


RECEIPT = python("handler", "api/routes/orders.py", ORDERS, 6, 13)
INVOICE = python("handler", "api/routes/orders.py", ORDERS, 16, 21)


def prompts() -> dict[QuestionType, Prompt]:
    """One example of every question type, built around the receipt story."""
    return {
        QuestionType.GUARD_SUMMARY: questions.guard_summary(packet(RECEIPT)),
        QuestionType.GUARD_EQUIVALENT: questions.guard_equivalent(
            packet(
                python("first", "api/routes/orders.py", ORDERS, 16, 21),
                Cut.whole("second", "api/services/orders.py", Language.PYTHON, SERVICES),
            )
        ),
        QuestionType.INPUT_ORIGIN: questions.input_origin(
            packet(RECEIPT), at="L3", value="order_id"
        ),
        QuestionType.SINK_SAFETY: questions.sink_safety(
            packet(Cut.whole("handler", "api/routes/reports.py", Language.PYTHON, REPORTS)),
            sink=SinkKind.SQL,
            at="L3",
        ),
        QuestionType.INTENTIONAL_EXCEPTION: questions.intentional_exception(
            packet(Cut.whole("handler", "api/routes/admin.py", Language.PYTHON, ADMIN)),
            missing=GuardKind.OWNER,
            resource="Order",
        ),
        QuestionType.CLIENT_EXPOSURE: questions.client_exposure(
            packet(
                Cut.whole("page", "web/app/courier/[id]/page.tsx", Language.TSX, COURIER_PAGE),
                Cut.whole("data access", "web/lib/dal.ts", Language.TYPESCRIPT, DAL),
            )
        ),
        QuestionType.FIX_SKETCH: questions.fix_sketch(
            packet(RECEIPT),
            rule="A receipt is returned only to the customer who placed the order.",
        ),
    }


# An answer each schema accepts, for the example prompts above.
ANSWERS: dict[QuestionType, dict[str, object]] = {
    QuestionType.GUARD_SUMMARY: {
        "guards": [
            {"kind": "authenticated", "subject": None, "object": None, "line_ids": ["L2"]},
        ]
    },
    QuestionType.GUARD_EQUIVALENT: {
        "same": "yes",
        "first_line_ids": ["L4"],
        "second_line_ids": ["L8"],
    },
    QuestionType.INPUT_ORIGIN: {"origin": "path", "line_ids": ["L1", "L2"]},
    QuestionType.SINK_SAFETY: {"mechanism": "none_found", "line_ids": ["L3"]},
    QuestionType.INTENTIONAL_EXCEPTION: {"reason": "admin_only", "line_ids": ["L4"]},
    QuestionType.CLIENT_EXPOSURE: {
        "fields": [
            {"name": "customer_phone", "line_ids": ["L11", "L5", "L6"]},
            {"name": "card_last4", "line_ids": ["L11", "L5", "L6"]},
        ]
    },
    QuestionType.FIX_SKETCH: {
        "intent": "Refuse the receipt unless the order belongs to the caller.",
        "edits": [
            {
                "line_id": "L4",
                "action": "replace",
                "code": "    if order is None or order.customer_id != user.id:",
            }
        ],
        "probe": {"parameter": "order_id", "denied": "other_user", "allowed": "owner"},
    },
}
