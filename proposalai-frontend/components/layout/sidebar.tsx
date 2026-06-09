"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { 
  LayoutDashboard, FileText, Archive, 
  FileCode, Calculator, User, Shield, 
  HelpCircle, LogOut 
} from "lucide-react";

function cn(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

const navItems = [
  { label: "Current", icon: FileText, href: "/dashboard", group: "PROPOSALS" },
  { label: "Archive", icon: Archive, href: "/archive", group: "PROPOSALS" },
  { label: "Templates", icon: FileCode, href: "/templates", group: "PROPOSALS" },
  { label: "Calculators", icon: Calculator, href: "/calculators", group: "PROPOSALS" },
  { label: "Profile", icon: User, href: "/profile", group: "ACCOUNT" },
  { label: "Security", icon: Shield, href: "/security", group: "ACCOUNT" },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-64 border-r border-slate-200 bg-slate-50/50 flex flex-col h-screen sticky top-0">
      <div className="p-6">
        <h1 className="text-xl font-bold text-govcon-blue flex items-center gap-2">
          <Shield className="w-6 h-6" /> ProposalAI
        </h1>
      </div>

      <nav className="flex-1 px-4 space-y-8">
        <div>
          <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest px-2 mb-4">Proposals</p>
          <div className="space-y-1">
            {navItems.filter(i => i.group === "PROPOSALS").map((item) => (
              <NavLink key={item.href} item={item} active={pathname === item.href} />
            ))}
          </div>
        </div>

        <div>
          <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest px-2 mb-4">Account</p>
          <div className="space-y-1">
            {navItems.filter(i => i.group === "ACCOUNT").map((item) => (
              <NavLink key={item.href} item={item} active={pathname === item.href} />
            ))}
          </div>
        </div>
      </nav>

      <div className="p-4 border-t border-slate-200 space-y-1">
        <button className="flex items-center gap-3 px-3 py-2 w-full text-slate-600 hover:bg-white hover:text-govcon-blue rounded-lg transition-colors text-sm font-medium">
          <HelpCircle className="w-4 h-4" /> Help
        </button>
        <button className="flex items-center gap-3 px-3 py-2 w-full text-slate-600 hover:bg-rose-50 hover:text-rose-600 rounded-lg transition-colors text-sm font-medium">
          <LogOut className="w-4 h-4" /> Logout
        </button>
      </div>
    </aside>
  );
}

function NavLink({ item, active }: { item: any, active: boolean }) {
  return (
    <Link
      href={item.href}
      className={cn(
        "flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors",
        active 
          ? "bg-white text-govcon-blue shadow-sm ring-1 ring-slate-200" 
          : "text-slate-600 hover:bg-white hover:text-govcon-blue"
      )}
    >
      <item.icon className={cn("w-4 h-4", active ? "text-govcon-blue" : "text-slate-400")} />
      {item.label}
    </Link>
  );
}