// The connect → verify flow. The dashboard layout already gates on a WorkOS session (it renders the sign-in
// card for an anonymous visitor), so reaching this page means the user is authenticated; the client
// component talks only to the authed /api/verify proxy.
import { VerifyClient } from "./VerifyClient";

export const dynamic = "force-dynamic";

export default function VerifyPage() {
  return <VerifyClient />;
}
