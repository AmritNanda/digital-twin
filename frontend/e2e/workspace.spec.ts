import { expect, test } from '@playwright/test';

test('document-led case reaches approval, result, and versioned export', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  let signedIn = false;
  const caseId = 'case-e2e';
  const runId = 'run-e2e';
  const caseData: Record<string, any> = {
    id: caseId, question: '', status: 'draft',
    source_snapshot: { version: 0, suggested_questions: [], entities: [], facts: [], unknowns: [], corrections: [] },
    approval: {}, documents: [], runs: [], events: [], messages: [],
  };
  const json = (body: unknown, status = 200) => ({ status, contentType: 'application/json', body: JSON.stringify(body) });
  await page.route('**/api/**', async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path === '/api/auth/me') return route.fulfill(signedIn ? json({ id: 'owner', email: 'owner@example.test' }) : json({ detail: 'Sign in' }, 401));
    if (path === '/api/auth/login') {
      signedIn = true;
      return route.fulfill(json({ id: 'owner', email: 'owner@example.test' }));
    }
    if (path === '/api/cases' && request.method() === 'POST') return route.fulfill(json(caseData, 201));
    if (path === `/api/cases/${caseId}/documents` && request.method() === 'POST') {
      caseData.documents = [{ id: 'document-1', filename: 'nila-home.txt', size: 86, chunks: 1, preview: 'Nila Home launches storage kits.' }];
      caseData.source_snapshot = { ...caseData.source_snapshot, version: 1,
        suggested_questions: ['What channel should Nila Home use for the launch?'] };
      return route.fulfill(json(caseData.documents[0], 201));
    }
    if (path === `/api/cases/${caseId}/start` && request.method() === 'POST') {
      const question = request.postDataJSON().question;
      if (!question) caseData.status = 'awaiting_question';
      else {
        caseData.question = question;
        caseData.status = 'awaiting_approval';
        caseData.approval = { values: { base_demand: 1000, elasticity: -1.2, cac_inr: 300,
          unit_cost_inr: 180, fixed_cost_inr: 45000, pilot_budget_cap_inr: 25000 } };
        caseData.runs = [{ id: runId, version: 1, status: 'awaiting_approval', result: {},
          assumptions: {}, created_at: new Date().toISOString(), twin: { simulations: [
            { id: 'sim-1', hypothesis_id: 'retail', channel: 'Retail', avg_profit: 12000,
              p10_profit: -1000, p90_profit: 28000, p50_profit: 11000, prob_positive: .8 },
          ], challenges: [{ id: 'challenge-1', weakness: 'CAC needs validation',
            severity: 'moderate', assumption_targeted: 'CAC' }] } }];
      }
      return route.fulfill(json(caseData));
    }
    if (path === `/api/cases/${caseId}/approve` && request.method() === 'POST') {
      caseData.status = 'completed';
      caseData.runs[0].status = 'completed';
      caseData.runs[0].assumptions = request.postDataJSON().values;
      caseData.runs[0].result = { recommendation: 'Pilot retail first', rationale: 'The modeled downside is lower.',
        source_version: 1, fixture_data_present: true, selected_hypothesis: 'Retail',
        hypotheses: [{ id: 'retail', title: 'Retail' }], simulations: caseData.runs[0].twin.simulations,
        sensitivity: [], evidence: [{ id: 'E1', source_type: 'fixture', excerpt: 'Illustrative demand' }],
        pilot: { duration_weeks: 4, budget_cap_inr: 25000, measure: ['Observed CAC'],
          stop_condition: 'Stop above approved CAC.', human_action_required: true } };
      return route.fulfill(json(caseData));
    }
    if (path === `/api/cases/${caseId}`) return route.fulfill(json(caseData));
    if (path === `/api/cases/${caseId}/exports/json`) {
      return route.fulfill({ ...json({ run: caseData.runs[0] }), headers: {
        'Content-Disposition': 'attachment; filename="strategy-twin-case-e2e-run-1.json"',
      } });
    }
    return route.fulfill(json({ detail: `Unmocked ${path}` }, 404));
  });

  await page.goto('/');
  await page.getByRole('button', { name: /Upload company documents/ }).click();
  await expect(page.getByRole('heading', { name: 'Sign in before uploading.' })).toBeVisible();
  await page.getByLabel('Email').fill('owner@example.test');
  await page.getByLabel('Password').fill('local-test-password');
  await page.getByRole('button', { name: /Sign in & continue/ }).click();
  await page.locator('input[type=file]').setInputFiles({ name: 'nila-home.txt', mimeType: 'text/plain',
    buffer: Buffer.from('Nila Home sells a kitchen storage starter kit in India. Unit cost INR 180.') });
  await expect(page.getByText('nila-home.txt')).toBeVisible();
  await page.getByRole('button', { name: 'Start decision' }).click();
  await expect(page.getByRole('heading', { name: 'What decision should we test?' })).toBeVisible();
  await page.getByRole('button', { name: /What channel should Nila Home use/ }).click();
  await page.getByRole('button', { name: '↗' }).last().click();
  await expect(page.getByRole('heading', { name: 'Review what the final run will assume.' })).toBeVisible();
  await expect(page.getByText('Provisional findings')).toBeVisible();
  await page.getByRole('button', { name: /Approve & run final simulation/ }).click();
  await expect(page.getByRole('heading', { name: 'Pilot retail first' })).toBeVisible();
  await page.getByRole('button', { name: 'Export ↓' }).click();
  const download = page.waitForEvent('download');
  await page.getByRole('link', { name: /JSON/ }).click();
  expect((await download).suggestedFilename()).toContain('run-1.json');
});
