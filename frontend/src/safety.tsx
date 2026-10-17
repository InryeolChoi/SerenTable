import { NoShowSection } from "./attendance";

// T3 owns this file: reports/blocks (SAF-01) and operator review/sanctions (SAF-02).
export function ReportSection(_: { tableId: string }) {
  return null;
}

export function AdminSafetyPage() {
  return (
    <section className="panel">
      <h1>안전·노쇼 관리</h1>
      <NoShowSection />
    </section>
  );
}
