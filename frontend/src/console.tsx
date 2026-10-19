import { useEffect, useRef } from "react";
import { AuditSection } from "./audit";
import { DashboardSection } from "./dashboard";
import { ExceptionsSection } from "./exceptions";
import { ExportsSection } from "./exports";

// Operator console (operator-console-contract.md): each ticket owns one section file.
export function AdminConsolePage() {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus({ preventScroll: true });
  }, []);
  return (
    <section className="page-stack">
      <h1 ref={heading} tabIndex={-1}>
        운영 현황
      </h1>
      <DashboardSection />
      <ExceptionsSection />
      <ExportsSection />
      <AuditSection />
    </section>
  );
}
