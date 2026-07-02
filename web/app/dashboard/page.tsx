// The console home: an overview of the account's verification activity + recent scans. The verify action
// itself lives at /dashboard/verify. The layout gates on a WorkOS session (anonymous visitors get the
// sign-in card); the client component reads only the authed /api/jobs proxy.
import { OverviewClient } from "./OverviewClient";

export const dynamic = "force-dynamic";

export default function DashboardHome() {
  return <OverviewClient />;
}
