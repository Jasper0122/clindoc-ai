import { useNavigate } from "react-router-dom";
import { CircleUser, HelpCircle, LogOut } from "lucide-react";
import { Button } from "@/components/ui/button";

const Navbar = () => {
  const navigate = useNavigate();

  const handleLogout = () => {
    localStorage.removeItem("cdos_authenticated");
    navigate("/");
  };

  return (
    <header className="border-b border-border bg-card">
      <div className="flex h-16 items-center justify-between px-8">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-md bg-primary">
            <span className="text-xs font-bold tracking-wide text-primary-foreground">CDX</span>
          </div>
          <div className="leading-tight">
            <p className="text-sm font-semibold text-foreground">
              Clinical Documentation Optimization
            </p>
            <p className="text-xs text-muted-foreground">
              ClinDoc AI Demo System
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="icon" className="h-9 w-9 text-muted-foreground">
            <HelpCircle className="h-4 w-4" />
          </Button>
          <div className="flex h-9 w-9 items-center justify-center rounded-full bg-secondary">
            <CircleUser className="h-5 w-5 text-secondary-foreground" />
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={handleLogout}
            className="text-muted-foreground hover:text-foreground"
          >
            <LogOut className="mr-1.5 h-4 w-4" />
            Logout
          </Button>
        </div>
      </div>
    </header>
  );
};

export default Navbar;
