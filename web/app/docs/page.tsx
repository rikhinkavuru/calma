import { redirect } from "next/navigation";

// /docs → the first page (Quickstart), like OpenRouter's docs root.
export default function DocsIndex() {
  redirect("/docs/quickstart");
}
