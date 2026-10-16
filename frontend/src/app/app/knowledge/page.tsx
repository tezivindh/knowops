import type { Metadata } from "next";
import { KnowledgeScreen } from "@/components/screens/knowledge";

export const metadata: Metadata = { title: "Knowledge health" };

export default function Page() {
  return <KnowledgeScreen />;
}
