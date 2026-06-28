import { Suspense } from "react";
import { LoginForm } from "@/components/login-form";

export const metadata = {
  title: "登入 AMOS 工作台"
};

export default function LoginPage() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4 py-10">
      <Suspense fallback={<div className="text-sm text-muted-foreground">載入登入頁...</div>}>
        <LoginForm />
      </Suspense>
    </main>
  );
}
