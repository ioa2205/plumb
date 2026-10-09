import { vi } from "vitest";

import { jar } from "./jar";

vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) => (jar.has(name) ? { name, value: jar.get(name) } : undefined),
    set: (name: string, value: string) => void jar.set(name, value),
    delete: (name: string) => void jar.delete(name),
  }),
}));

vi.mock("next/navigation", async () => {
  const { NotFound, Redirect } = await import("./interrupts");
  return {
    redirect: (url: string) => {
      throw new Redirect(url);
    },
    notFound: () => {
      throw new NotFound();
    },
  };
});

vi.mock("next/cache", () => ({ revalidatePath: () => undefined }));
