import { VerifyClient } from "../VerifyClient";

// The verify action: connect a repo → re-run it → recompute every number → three-way verdict. Lives at
// /dashboard/verify so the console home (/dashboard) can be an overview. force-dynamic: the client component
// owns all data fetching, but keep the route uncached like the rest of the authed dashboard.
export const dynamic = "force-dynamic";

export default function VerifyPage() {
  return <VerifyClient />;
}
