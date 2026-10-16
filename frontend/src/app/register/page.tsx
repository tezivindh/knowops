import type { Metadata } from "next";
import { AuthForm } from "@/components/marketing/auth-form";

export const metadata: Metadata = { title: "Create account" };

export default function Page() {
  return <AuthForm mode="register" />;
}
