import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import Footer from "@/components/Footer";

const LoginPage = () => {
  const navigate = useNavigate();

  const handleLogin = () => {
    localStorage.setItem("cdos_authenticated", "true");
    navigate("/input");
  };

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <div className="flex flex-1 items-center justify-center px-4">
        <div className="w-full max-w-md">
          <div className="rounded-lg border border-border bg-card p-8 shadow-card">
            {/* Logo */}
            <div className="mb-6 flex flex-col items-center gap-3">
              <div className="flex h-12 w-auto min-w-[3rem] items-center justify-center rounded-lg bg-primary px-3">
                <span className="text-sm font-bold tracking-wide text-primary-foreground">CDX</span>
              </div>
              <div className="text-center">
                <h1 className="text-base font-semibold text-foreground whitespace-nowrap">
                  Clinical Documentation Optimization System
                </h1>
                <p className="mt-1 text-sm text-muted-foreground">
                  Internal Clinical Access
                </p>
              </div>
            </div>

            {/* Form */}
            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="email">Email</Label>
                <Input
                  id="email"
                  type="email"
                  placeholder="name@example.com"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="password">Password</Label>
                <Input
                  id="password"
                  type="password"
                  placeholder="••••••••"
                />
              </div>
              <Button className="w-full" onClick={handleLogin}>
                Login
              </Button>
            </div>

            <div className="mt-4 text-center">
              <button className="text-sm text-muted-foreground hover:text-primary transition-colors">
                Forgot password?
              </button>
            </div>
          </div>

          <p className="mt-6 text-center text-xs text-muted-foreground leading-relaxed">
            Authorized personnel only. All access is logged and monitored.
          </p>
        </div>
      </div>
      <Footer />
    </div>
  );
};

export default LoginPage;
