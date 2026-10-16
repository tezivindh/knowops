"use client";

import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Field, FormError, Input, Textarea } from "@/components/ui/field";
import { api, errorMessage, type Organization } from "@/lib/api";
import { slugify } from "@/lib/format";

export function CreateOrgForm({ onCreated, submitLabel = "Create workspace" }: { onCreated: (org: Organization) => void; submitLabel?: string }) {
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugEdited, setSlugEdited] = useState(false);
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const effectiveSlug = slugEdited ? slug : slugify(name);
  const slugValid = /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(effectiveSlug) && effectiveSlug.length >= 2;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const org = await api.createOrganization({
        name: name.trim(),
        slug: effectiveSlug,
        description: description.trim() || undefined,
      });
      onCreated(org);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <FormError message={error} />
      <Field label="Organization name">
        {(id) => <Input id={id} value={name} onChange={(e) => setName(e.target.value)} placeholder="Acme Corp" required autoFocus />}
      </Field>
      <Field
        label="URL name"
        hint="Lowercase letters, numbers and dashes."
        error={effectiveSlug && !slugValid ? "Use at least 2 lowercase letters, numbers or single dashes." : null}
      >
        {(id, describedBy) => (
          <Input
            id={id}
            value={effectiveSlug}
            onChange={(e) => {
              setSlugEdited(true);
              setSlug(e.target.value.toLowerCase());
            }}
            aria-describedby={describedBy}
            className="font-mono"
            required
          />
        )}
      </Field>
      <Field label="Description (optional)">
        {(id) => <Textarea id={id} rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />}
      </Field>
      <div>
        <Button type="submit" variant="primary" loading={busy} disabled={!name.trim() || !slugValid}>
          {submitLabel}
        </Button>
      </div>
    </form>
  );
}
