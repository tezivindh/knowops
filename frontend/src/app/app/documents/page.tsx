import type { Metadata } from "next";
import { DocumentsScreen } from "@/components/screens/documents";

export const metadata: Metadata = { title: "Documents" };

export default function Page() {
  return <DocumentsScreen />;
}
