import type { Metadata } from "next";
import Link from "next/link";
import { Boxes, Building2, CircleHelp, LayoutDashboard, Search, Settings, Sparkles, UserRound } from "lucide-react";
import "./globals.css";

export const metadata: Metadata = {
  title: "廣告素材智能工作台",
  description: "Internal AI workspace for ecommerce ad creative strategy."
};

const navItems = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/help", label: "使用說明", icon: CircleHelp },
  { href: "/brands", label: "品牌中心", icon: Building2 },
  { href: "/competitors", label: "競品情報", icon: Search },
  { href: "/projects/new", label: "產品分析", icon: Boxes },
  { href: "/kols", label: "KOL 工具", icon: UserRound },
  { href: "/settings", label: "設定", icon: Settings }
];

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-Hant">
      <body>
        <div className="min-h-screen bg-background lg:grid lg:grid-cols-[240px_1fr]">
          <aside className="hidden border-r bg-white lg:block">
            <div className="sticky top-0 flex h-screen flex-col">
              <Link href="/" className="flex h-16 items-center gap-2 border-b px-5 text-sm font-semibold">
                <span className="flex h-9 w-9 items-center justify-center rounded-md bg-primary text-primary-foreground">
                  <Sparkles className="h-4 w-4" />
                </span>
                <span>廣告素材智能工作台</span>
              </Link>

              <nav className="grid gap-1 p-3">
                {navItems.map((item) => (
                  <Link
                    key={item.href}
                    href={item.href}
                    className="flex h-10 items-center gap-3 rounded-md px-3 text-sm text-muted-foreground transition hover:bg-muted hover:text-foreground"
                  >
                    <item.icon className="h-4 w-4" />
                    <span>{item.label}</span>
                  </Link>
                ))}
              </nav>

              <div className="mt-auto border-t p-4 text-xs leading-5 text-muted-foreground">
                內部行銷工具。先建立品牌與產品，再生成素材、腳本、KOL 與競品情報。
              </div>
            </div>
          </aside>

          <div className="min-w-0">
            <header className="sticky top-0 z-20 border-b bg-white/92 backdrop-blur lg:hidden">
              <div className="flex h-14 items-center justify-between px-4">
                <Link href="/" className="flex items-center gap-2 text-sm font-semibold">
                  <span className="flex h-8 w-8 items-center justify-center rounded-md bg-primary text-primary-foreground">
                    <Sparkles className="h-4 w-4" />
                  </span>
                  廣告素材智能工作台
                </Link>
              </div>
              <nav className="flex gap-1 overflow-x-auto border-t px-3 py-2">
                {navItems.map((item) => (
                  <Link
                    key={item.href}
                    href={item.href}
                    className="flex h-9 shrink-0 items-center gap-2 rounded-md px-3 text-sm text-muted-foreground transition hover:bg-muted hover:text-foreground"
                  >
                    <item.icon className="h-4 w-4" />
                    <span>{item.label}</span>
                  </Link>
                ))}
              </nav>
            </header>

            <main className="mx-auto max-w-7xl px-4 py-6 lg:px-8">{children}</main>
          </div>
        </div>
      </body>
    </html>
  );
}
