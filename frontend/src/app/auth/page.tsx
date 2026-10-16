import { redirect } from "next/navigation";

// Old URL kept working for existing bookmarks.
export default function Page() {
  redirect("/login");
}
