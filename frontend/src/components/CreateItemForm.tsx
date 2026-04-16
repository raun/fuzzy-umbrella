import { type FormEvent, useState } from "react";
import { createItem } from "../api/items";

interface Props {
  /** Called after a successful item creation to trigger list refresh. */
  onCreated: () => void;
}

export function CreateItemForm({ onCreated }: Props) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await createItem({ name, description: description || null });
      setName("");
      setDescription("");
      onCreated();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to create item");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={(e) => void handleSubmit(e)}>
      <div>
        <label htmlFor="item-name">Name</label>
        <input
          id="item-name"
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
        />
      </div>
      <div>
        <label htmlFor="item-description">Description</label>
        <input
          id="item-description"
          type="text"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>
      {error && <p role="alert">Error: {error}</p>}
      <button type="submit" disabled={submitting}>
        {submitting ? "Creating…" : "Create Item"}
      </button>
    </form>
  );
}
