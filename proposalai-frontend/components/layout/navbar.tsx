import { Bell, User } from "lucide-react";
import Link from "next/link";

export function Navbar() {
  return (
    <header className="h-16 border-b border-slate-200 bg-white px-8 flex items-center justify-between sticky top-0 z-10">
      <div className="flex items-center gap-8">
        <nav className="flex items-center gap-6">
          <Link href="/dashboard" className="text-sm font-semibold text-govcon-blue border-b-2 border-govcon-blue h-16 flex items-center">Dashboard</Link>
          <Link href="/workspace" className="text-sm font-medium text-slate-500 hover:text-govcon-navy">Workspace</Link>
          <Link href="/compliance" className="text-sm font-medium text-slate-500 hover:text-govcon-navy">Compliance</Link>
        </nav>
      </div>

      <div className="flex items-center gap-4">
        <button className="p-2 text-slate-400 hover:bg-slate-50 rounded-full">
          <Bell className="w-5 h-5" />
        </button>
        <div className="flex items-center gap-3 pl-4 border-l">
          <div className="w-8 h-8 rounded-full bg-slate-200 flex items-center justify-center overflow-hidden">
             <User className="w-5 h-5 text-slate-500" />
          </div>
          <Link href="/new" className="bg-govcon-blue text-white px-4 py-2 rounded-lg text-sm font-semibold hover:bg-govcon-navy transition-colors">
            New proposal
          </Link>
        </div>
      </div>
    </header>
  );
}