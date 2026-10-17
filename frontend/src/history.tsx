import { CheckInSection } from "./attendance";
import { FeedbackSection } from "./feedback";
import { ReportSection } from "./safety";

// Participant history page (feedback-contract.md). T4 owns the history list and
// recommendations; each table card composes the T1/T2/T3 sections for that table.
export type HistoryTable = { table_id: string };

export function TableActions({ table }: { table: HistoryTable }) {
  return (
    <>
      <CheckInSection tableId={table.table_id} />
      <FeedbackSection tableId={table.table_id} />
      <ReportSection tableId={table.table_id} />
    </>
  );
}

export function HistoryPage() {
  return (
    <section className="panel">
      <h1>참가 이력</h1>
    </section>
  );
}
