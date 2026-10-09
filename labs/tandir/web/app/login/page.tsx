import { LoginForm } from "./LoginForm";

export default function LoginPage() {
  return (
    <>
      <h1>Sign in</h1>
      <p className="muted">Lab accounts are listed in labs/tandir/api/tandir/seed.py.</p>
      <LoginForm />
    </>
  );
}
