import type { Metadata } from "next";
import { DocumentDetailScreen } from "@/components/screens/document-detail";

export const metadata: Metadata = { title: "Document" };

export default function Page() {
  return <DocumentDetailScreen />;
}
