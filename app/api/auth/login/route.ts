import { NextRequest, NextResponse } from "next/server";
import { AUTH_COOKIE_NAME, createSessionToken, getAuthConfig, getSessionMaxAge, isValidPassword } from "@/lib/auth";

export async function POST(request: NextRequest) {
  const { email, password } = await request.json().catch(() => ({ email: "", password: "" }));
  const config = getAuthConfig();

  if (!config.isConfigured) {
    return NextResponse.json(
      { message: "登入尚未設定，請在 Render 環境變數設定 AUTH_SECRET、ADMIN_EMAIL、ADMIN_PASSWORD。" },
      { status: 500 }
    );
  }

  if (!isValidPassword(String(email || ""), String(password || ""))) {
    return NextResponse.json({ message: "帳號或密碼錯誤。" }, { status: 401 });
  }

  const token = await createSessionToken(config.adminEmail);
  const response = NextResponse.json({ ok: true });
  response.cookies.set({
    name: AUTH_COOKIE_NAME,
    value: token,
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: getSessionMaxAge()
  });
  return response;
}
