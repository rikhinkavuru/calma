// The dashboard IS the connect → verify flow. The layout already gates on a WorkOS session (anonymous
// visitors get the sign-in card), so reaching here means authenticated; the client component talks only to
// the authed /api/verify proxy. No control-plane dependency on the default view — verify needs identity
// (getUser/withAuth), not a provisioned tenant.
import { VerifyClient } from "./VerifyClient";

export const dynamic = "force-dynamic";

export default function DashboardHome() {
  return <VerifyClient />;
}
