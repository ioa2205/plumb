"use client";

import { useActionState } from "react";

import { signIn, type SignInState } from "./actions";

const initial: SignInState = { error: null };

export function LoginForm() {
  const [state, action, pending] = useActionState(signIn, initial);
  return (
    <form action={action} className="stack">
      <label>
        Username
        <br />
        <input name="username" autoComplete="username" required />
      </label>
      <label>
        Password
        <br />
        <input name="password" type="password" autoComplete="current-password" required />
      </label>
      {state.error && <p className="error">{state.error}</p>}
      <button type="submit" disabled={pending}>
        Sign in
      </button>
    </form>
  );
}
