import { all } from "@/lib/db";

// Spreadsheets run cells that start with = + - @ (or a tab or CR) as formulas; prefix a quote.
function cell(value: string): string {
  const text = /^[=+\-@\t\r]/.test(value) ? `'${value}` : value;
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

export function GET(): Response {
  const customers = all<{ id: number; display_name: string; phone: string }>(
    "SELECT id, display_name, phone FROM users WHERE role = 'customer' ORDER BY id",
  );
  const lines = ["id,name,phone", ...customers.map((c) => `${c.id},${cell(c.display_name)},${cell(c.phone)}`)];
  return new Response(`${lines.join("\n")}\n`, {
    headers: {
      "content-type": "text/csv; charset=utf-8",
      "content-disposition": 'attachment; filename="customers.csv"',
    },
  });
}
