import { expect, test } from '@playwright/test'

test('shows the analysis room', async ({ page }) => {
  await page.route('**/api/matches', route => route.fulfill({ json: [] }))
  await page.route('**/api/reports', route => route.fulfill({ json: [] }))
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Soccer Tactics Agent' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Sync Metrica samples' })).toBeVisible()
})

test('shows streamed data preparation progress', async ({ page }) => {
  await page.route('**/api/matches', route => route.fulfill({ json: [] }))
  await page.route('**/api/reports', route => route.fulfill({ json: [] }))
  await page.route('**/api/data/sync/stream', route => route.fulfill({
    contentType: 'application/x-ndjson',
    body: [
      JSON.stringify({ stage: 'source', message: 'Metrica source data is ready', progress: 0.18 }),
      JSON.stringify({ stage: 'game-1', message: 'Normalizing sample game 1 of 3', progress: 0.18 }),
      JSON.stringify({
        stage: 'complete', message: 'All three sample matches are ready', progress: 1,
        matches: [{ match_id: 'sample-game-1', name: 'Metrica Sample Game 1', format: 'metrica_csv', source_attribution: 'Metrica' }],
      }),
    ].join('\n') + '\n',
  }))

  await page.goto('/')
  await page.getByRole('button', { name: 'Sync Metrica samples' }).click()

  await expect(page.locator('.operation-status > p')).toHaveText('1 match ready for analysis')
  await expect(page.getByText('Normalizing sample game 1 of 3')).toBeVisible()
  await expect(page.getByText(/100% · \d+s/)).toBeVisible()
})
