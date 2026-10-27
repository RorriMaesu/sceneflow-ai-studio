export interface DraftRecord<T> {
  version: 1;
  revision: number;
  value: T;
  baseline: T;
}
function content(value: any) {
  if (!value || !Array.isArray(value.clips) || !Array.isArray(value.audio))
    return value;
  const { revision, ...body } = value;
  const { manual_edit, ...settings } = body.settings || {};
  return { ...body, settings };
}
export const changed = (value: unknown, baseline: unknown) =>
  JSON.stringify(content(value)) !== JSON.stringify(content(baseline));
export const draftConflicts = (base: number, server: number) => server > base;
export function readDraft<T>(
  storage: Pick<Storage, "getItem">,
  key: string,
  valid: (v: any) => boolean,
): DraftRecord<T> | null {
  try {
    const value = JSON.parse(
      storage.getItem("sceneflow.safe-draft." + key) || "null",
    );
    return value?.version === 1 &&
      Number.isInteger(value.revision) &&
      valid(value.value) &&
      valid(value.baseline)
      ? value
      : null;
  } catch {
    return null;
  }
}
export function writeDraft<T>(
  storage: Pick<Storage, "setItem" | "removeItem">,
  key: string,
  record: DraftRecord<T>,
) {
  const name = "sceneflow.safe-draft." + key;
  if (changed(record.value, record.baseline))
    storage.setItem(name, JSON.stringify(record));
  else storage.removeItem(name);
}
