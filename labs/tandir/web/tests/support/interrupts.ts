// Stand-ins for Next.js navigation interrupts, so tests can assert on them.
export class Redirect extends Error {
  constructor(readonly url: string) {
    super(`redirect to ${url}`);
  }
}

export class NotFound extends Error {
  constructor() {
    super("not found");
  }
}
