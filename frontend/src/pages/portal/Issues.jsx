import React from "react";
import { MessageSquareWarning } from "lucide-react";
import { Button, Card, EmptyState, Page } from "../../ui";

// A placeholder, said plainly: reporting problems from the console is the next phase of the work
// (issue reporting). Nothing here pretends to list or count issues before that exists.
export default function IssuesPage({ setPage }) {
  return <Page title="Issues" subtitle="Problems reported by admins.">
    <Card>
      <EmptyState icon={MessageSquareWarning} title="Issue reporting is not built yet"
        message="Admins will report problems from any page of the console and the scanner, with the page and the device attached. They will arrive here as an inbox: filter by status, severity and category, reply, and mark them resolved."
        action={<Button size="sm" variant="outline" onClick={() => setPage("superAdmin")}>Back to the dashboard</Button>} />
    </Card>
  </Page>;
}
