import { ScanDetailClient } from "../../ScanDetailClient";

export const dynamic = "force-dynamic";

export default async function ScanDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ScanDetailClient id={id} />;
}
