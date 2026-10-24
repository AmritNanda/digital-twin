import { describe, expect, it } from 'vitest';
import { planUpload } from './upload';

const MB = 1024 * 1024;
const file = (name: string, size: number) => ({ name, size });

describe('document transfer plan', () => {
  it('keeps valid files when another file fails local validation', () => {
    const plan = planUpload([file('brief.pdf', 2 * MB), file('scan.png', MB), file('costs.csv', MB)], []);
    expect(plan.accepted.map(item => item.name)).toEqual(['brief.pdf', 'costs.csv']);
    expect(plan.rejected.map(item => item.file.name)).toEqual(['scan.png']);
  });

  it('rejects a batch that would exceed the case cap before transfer', () => {
    const plan = planUpload([file('new.pdf', 16 * MB)], [
      file('one.pdf', 18 * MB), file('two.pdf', 18 * MB),
    ]);
    expect(plan.accepted).toEqual([]);
    expect(plan.error).toMatch(/50 MB/);
  });

  it('enforces the five-document and per-file limits', () => {
    const tooMany = planUpload([file('sixth.md', 10)], Array.from({ length: 5 }, (_, index) => file(`${index}.txt`, 1)));
    expect(tooMany.error).toMatch(/five files/);
    const oversized = planUpload([file('brief.docx', 20 * MB + 1)], []);
    expect(oversized.rejected).toHaveLength(1);
  });
});
