"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Lock, Search, Upload } from "lucide-react";
import { UploadDialog } from "@/components/screens/upload-dialog";
import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/field";
import { Empty, ErrorState, PageHeader, Segmented } from "@/components/ui/misc";
import { Loading } from "@/components/ui/spinner";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { formatRelative, plural } from "@/lib/format";
import { useData, useInterval } from "@/lib/use-data";
import { canContribute, useSession } from "@/stores/session";

type Filter = "" | "ready" | "processing" | "failed" | "archived";
const PER_PAGE = 25;

export function DocumentsScreen() {
  const { org } = useSession();
  const orgId = org!.id;
  const toast = useToast();
  const [filter, setFilter] = useState<Filter>("");
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [uploading, setUploading] = useState(false);

  // Debounce typing into the search box.
  useEffect(() => {
    const id = setTimeout(() => {
      setSearch(query.trim());
      setPage(1);
    }, 250);
    return () => clearTimeout(id);
  }, [query]);

  const { data, error, loading, reload } = useData(
    () => api.documents(orgId, { page, per_page: PER_PAGE, search, status: filter || undefined }),
    [orgId, page, search, filter],
  );

  // Keep statuses fresh while anything is still being processed.
  const busy = data?.items.some((d) => d.status === "uploaded" || d.status === "processing") ?? false;
  useInterval(reload, 4000, busy);

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        title="Documents"
        description="Everything the assistant can answer from. Only documents marked Ready are searched."
        actions={
          canContribute(org) && (
            <Button variant="primary" onClick={() => setUploading(true)}>
              <Upload className="size-4" />
              Upload
            </Button>
          )
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative w-full max-w-xs">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted" />
          <Input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search titles and file names"
            aria-label="Search documents"
            className="pl-8"
          />
        </div>
        <Segmented<Filter>
          label="Filter by status"
          value={filter}
          onChange={(v) => {
            setFilter(v);
            setPage(1);
          }}
          options={[
            { value: "", label: "Active" },
            { value: "ready", label: "Ready" },
            { value: "processing", label: "Processing" },
            { value: "failed", label: "Failed" },
            { value: "archived", label: "Archived" },
          ]}
        />
      </div>

      {error ? (
        <ErrorState message={error} onRetry={reload} />
      ) : loading && !data ? (
        <Loading />
      ) : data && data.items.length === 0 ? (
        search || filter ? (
          <Empty title="No matching documents">Try a different search or filter.</Empty>
        ) : (
          <Empty
            title="No documents yet"
            action={
              canContribute(org) && (
                <Button variant="primary" onClick={() => setUploading(true)}>
                  Upload documents
                </Button>
              )
            }
          >
            Upload policies, handbooks, runbooks or FAQs. The assistant answers only from what&apos;s here.
          </Empty>
        )
      ) : data ? (
        <>
          <div className="border-y border-rule">
            <table className="w-full table-fixed text-left text-[13.5px]">
              <thead>
                <tr className="border-b border-rule text-[12px] text-muted">
                  <th className="py-2 pl-1 pr-3 font-medium">Title</th>
                  <th className="hidden w-16 px-3 py-2 font-medium sm:table-cell">Type</th>
                  <th className="w-28 px-3 py-2 font-medium">Status</th>
                  <th className="hidden w-48 px-3 py-2 font-medium md:table-cell">Category</th>
                  <th className="hidden w-28 py-2 pl-3 pr-1 text-right font-medium sm:table-cell">Updated</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-rule">
                {data.items.map((d) => (
                  <tr key={d.id} className="group hover:bg-surface-2/50">
                    <td className="py-2.5 pl-1 pr-3">
                      <Link href={`/app/documents/${d.id}`} className="flex items-center gap-1.5 truncate font-medium group-hover:text-accent">
                        {d.restricted && <Lock className="size-3.5 shrink-0 text-muted" aria-label="Restricted" />}
                        <span className="truncate">{d.title}</span>
                      </Link>
                      <span className="block truncate text-[12px] text-muted">
                        {d.original_filename}
                        {d.status === "failed" && <span className="text-danger"> · couldn&apos;t be read, open for details</span>}
                      </span>
                    </td>
                    <td className="hidden px-3 py-2.5 font-mono text-[11.5px] uppercase text-muted sm:table-cell">{d.file_type}</td>
                    <td className="px-3 py-2.5">
                      <StatusBadge status={d.status} />
                    </td>
                    <td className="hidden truncate px-3 py-2.5 text-ink-2 md:table-cell">
                      {[d.category, d.department].filter(Boolean).join(" · ") || <span className="text-muted">—</span>}
                    </td>
                    <td className="hidden whitespace-nowrap py-2.5 pl-3 pr-1 text-right text-[12.5px] text-muted sm:table-cell">
                      {formatRelative(d.updated_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-3 flex items-center justify-between text-[12.5px] text-muted">
            <span>{plural(data.total, "document")}</span>
            {data.pages > 1 && (
              <div className="flex items-center gap-2">
                <Button size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                  Previous
                </Button>
                <span className="tabular">
                  Page {data.page} of {data.pages}
                </span>
                <Button size="sm" disabled={page >= data.pages} onClick={() => setPage((p) => p + 1)}>
                  Next
                </Button>
              </div>
            )}
          </div>
        </>
      ) : null}

      <UploadDialog
        orgId={orgId}
        open={uploading}
        onClose={() => setUploading(false)}
        onUploaded={(count) => {
          toast(`${plural(count, "document")} uploaded. Processing has started.`);
          if (filter && filter !== "processing") setFilter("");
          void reload();
        }}
      />
    </div>
  );
}
