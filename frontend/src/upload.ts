const MB = 1024 * 1024;
const ALLOWED = new Set(['pdf', 'docx', 'csv', 'txt', 'md']);

type UploadFile = Pick<File, 'name' | 'size'>;

export function planUpload<T extends UploadFile>(files: T[], existing: UploadFile[]) {
  const availableSlots = Math.max(0, 5 - existing.length);
  if (files.length > availableSlots ||
      existing.reduce((sum, file) => sum + file.size, 0) + files.reduce((sum, file) => sum + file.size, 0) > 50 * MB) {
    return { accepted: [] as T[], rejected: [] as { file: T; reason: string }[],
      error: 'A case accepts up to five files and 50 MB total.' };
  }
  const accepted: T[] = [];
  const rejected: { file: T; reason: string }[] = [];
  for (const file of files) {
    const suffix = file.name.split('.').pop()?.toLowerCase() || '';
    if (!ALLOWED.has(suffix) || file.size > 20 * MB) {
      rejected.push({ file, reason: 'Use PDF, DOCX, CSV, TXT or MD; max 20 MB per file.' });
    } else accepted.push(file);
  }
  return { accepted, rejected, error: '' };
}
