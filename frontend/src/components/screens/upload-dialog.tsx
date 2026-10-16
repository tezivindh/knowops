"use client";

import { useRef, useState, type DragEvent, type FormEvent } from "react";
import { Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, FormError, Input, Textarea } from "@/components/ui/field";
import { api, errorMessage } from "@/lib/api";
import { formatBytes } from "@/lib/format";

export const ACCEPTED = [".pdf", ".docx", ".txt", ".md", ".csv"];
const MAX_MB = 50;

export function validateFile(file: File): string | null {
  const ext = file.name.includes(".") ? `.${file.name.split(".").pop()!.toLowerCase()}` : "";
  if (!ACCEPTED.includes(ext)) return `${file.name}: only ${ACCEPTED.join(", ")} files are supported.`;
  if (file.size === 0) return `${file.name} is empty.`;
  if (file.size > MAX_MB * 1024 * 1024) return `${file.name} is larger than ${MAX_MB} MB.`;
  return null;
}

export function UploadDialog({
  orgId,
  open,
  onClose,
  onUploaded,
}: {
  orgId: string;
  open: boolean;
  onClose: () => void;
  onUploaded: (count: number) => void;
}) {
  const [files, setFiles] = useState<File[]>([]);
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState("");
  const [department, setDepartment] = useState("");
  const [tags, setTags] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  function reset() {
    setFiles([]);
    setTitle("");
    setCategory("");
    setDepartment("");
    setTags("");
    setDescription("");
    setError(null);
    setProgress(null);
  }

  function close() {
    if (busy) return;
    reset();
    onClose();
  }

  function addFiles(list: FileList | null) {
    if (!list) return;
    const incoming = Array.from(list);
    const problems = incoming.map(validateFile).filter(Boolean) as string[];
    const valid = incoming.filter((f) => !validateFile(f));
    setError(problems.length ? problems.join(" ") : null);
    setFiles((current) => {
      const names = new Set(current.map((f) => f.name + f.size));
      return [...current, ...valid.filter((f) => !names.has(f.name + f.size))];
    });
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    addFiles(e.dataTransfer.files);
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!files.length) return;
    setBusy(true);
    setError(null);
    const tagList = tags
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);
    const failures: string[] = [];
    let done = 0;
    for (const [i, file] of files.entries()) {
      setProgress(`Uploading ${i + 1} of ${files.length}: ${file.name}`);
      try {
        await api.uploadDocument(orgId, file, {
          title: files.length === 1 ? title.trim() || undefined : undefined,
          category: category.trim() || undefined,
          department: department.trim() || undefined,
          description: description.trim() || undefined,
          tags: tagList,
        });
        done++;
      } catch (err) {
        failures.push(`${file.name}: ${errorMessage(err)}`);
      }
    }
    setBusy(false);
    setProgress(null);
    if (done) onUploaded(done);
    if (failures.length) {
      setFiles((current) => current.filter((f) => failures.some((msg) => msg.startsWith(`${f.name}:`))));
      setError(failures.join(" "));
    } else {
      reset();
      onClose();
    }
  }

  return (
    <Dialog
      open={open}
      onClose={close}
      title="Upload documents"
      description="Files are indexed in the background. They become searchable once marked Ready."
      footer={
        <>
          <Button onClick={close} disabled={busy}>
            Cancel
          </Button>
          <Button variant="primary" type="submit" form="upload-form" loading={busy} disabled={!files.length}>
            Upload {files.length > 1 ? `${files.length} files` : ""}
          </Button>
        </>
      }
    >
      <form id="upload-form" onSubmit={submit} className="flex flex-col gap-4">
        <FormError message={error} />
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={`rounded-md border border-dashed px-4 py-6 text-center transition-colors ${
            dragging ? "border-accent bg-accent-soft" : "border-rule-strong"
          }`}
        >
          <Upload className="mx-auto size-5 text-muted" strokeWidth={1.5} aria-hidden="true" />
          <p className="mt-2 text-[13.5px]">
            Drop files here or{" "}
            <button type="button" onClick={() => input.current?.click()} className="font-medium text-accent hover:underline">
              choose files
            </button>
          </p>
          <p className="mt-1 text-[12px] text-muted">
            PDF, DOCX, TXT, MD or CSV · up to {MAX_MB} MB each. Scanned PDFs without a text layer can&apos;t be read.
          </p>
          <input
            ref={input}
            type="file"
            multiple
            accept={ACCEPTED.join(",")}
            className="sr-only"
            onChange={(e) => {
              addFiles(e.target.files);
              e.target.value = "";
            }}
          />
        </div>

        {files.length > 0 && (
          <ul className="divide-y divide-rule rounded-md border border-rule text-[13px]">
            {files.map((f) => (
              <li key={f.name + f.size} className="flex items-center gap-3 px-3 py-2">
                <span className="min-w-0 flex-1 truncate">{f.name}</span>
                <span className="text-muted">{formatBytes(f.size)}</span>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => setFiles((cur) => cur.filter((x) => x !== f))}
                  className="text-[12.5px] text-muted hover:text-danger"
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}

        {progress && <p className="text-[12.5px] text-muted">{progress}</p>}

        {files.length === 1 && (
          <Field label="Title" hint="Defaults to the file name.">
            {(id, d) => <Input id={id} aria-describedby={d} value={title} onChange={(e) => setTitle(e.target.value)} maxLength={500} />}
          </Field>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Category">
            {(id) => <Input id={id} value={category} onChange={(e) => setCategory(e.target.value)} placeholder="Policy" maxLength={100} />}
          </Field>
          <Field label="Department">
            {(id) => <Input id={id} value={department} onChange={(e) => setDepartment(e.target.value)} placeholder="HR" maxLength={100} />}
          </Field>
        </div>
        <Field label="Tags" hint="Separate with commas.">
          {(id, d) => <Input id={id} aria-describedby={d} value={tags} onChange={(e) => setTags(e.target.value)} placeholder="leave, onboarding" />}
        </Field>
        <Field label="Description">
          {(id) => <Textarea id={id} rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />}
        </Field>
      </form>
    </Dialog>
  );
}
