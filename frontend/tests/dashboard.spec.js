import { test, expect } from '@playwright/test';

test.describe('SentiStream Dashboard E2E Tests', () => {
  
  test('Initial Load: renders dashboard elements and connects to WebSocket', async ({ page }) => {
    // Go to local dev site
    await page.goto('/');
    
    // Verify header title
    await expect(page.locator('h1')).toContainText('SENTISTREAM');
    
    // Verify WS connection status is connected
    const wsBadge = page.locator('text=WS STREAM: CONNECTED');
    await expect(wsBadge).toBeVisible({ timeout: 5000 });
    
    // Verify other main sections are visible
    await expect(page.locator('text=QUANTITATIVE PAPER TRADING PORTFOLIO')).toBeVisible();
    await expect(page.locator('text=LIVE HEADLINE TICKER STREAM')).toBeVisible();
    await expect(page.locator('text=SYSTEM LATENCY PROFILE')).toBeVisible();
  });

  test('WebSocket Live Ingestion: displays new headlines pushed to Redis', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('text=WS STREAM: CONNECTED')).toBeVisible({ timeout: 5000 });
    
    // Generate a unique headline text to avoid overlap
    const uniqueHeadline = `Apple reports record breaking Q3 revenue growth: ${Date.now()}`;
    
    // Trigger out-of-band injection via test endpoint on backend
    const response = await page.request.post('http://localhost:8000/api/v1/test/inject', {
      data: {
        ticker: 'AAPL',
        headline_text: uniqueHeadline,
        source: 'playwright_e2e_test'
      }
    });
    expect(response.ok()).toBeTruthy();
    
    // Assert the new headline text is rendered in the live sentiment news feed
    await expect(page.locator(`text=${uniqueHeadline}`)).toBeVisible({ timeout: 10000 });
  });

  test('Capital Warning Alert: shows alert when trade exceeds capital limit', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('text=WS STREAM: CONNECTED')).toBeVisible({ timeout: 5000 });
    
    // Generate a unique buy-triggering headline text with high confidence sentiment cues
    const uniqueHeadline = `Tesla vehicle deliveries beat Wall Street estimates as global demand recovers. Stock surges 15% on massive growth: ${Date.now()}`;
    
    // Inject via test endpoint. Since settings.FORCE_TRADE_COST_USD=100001.0 is set in test environment,
    // this will trigger an insufficient capital warning.
    const response = await page.request.post('http://localhost:8000/api/v1/test/inject', {
      data: {
        ticker: 'TSLA',
        headline_text: uniqueHeadline,
        source: 'playwright_e2e_test'
      }
    });
    expect(response.ok()).toBeTruthy();
    
    // Assert the capital warning alert banner appears in the portfolio section
    await expect(page.locator('text=WARNING: INSUFFICIENT CAPITAL TO BUY TSLA')).toBeVisible({ timeout: 10000 });
  });

  test('WebSocket Disconnection Resiliency: warns user and reconnects when connection is restored', async ({ page, context }) => {
    await page.goto('/');
    await expect(page.locator('text=WS STREAM: CONNECTED')).toBeVisible({ timeout: 5000 });
    
    // Force browser offline to disconnect WebSocket
    await context.setOffline(true);
    
    // Verify status changes to disconnected
    await expect(page.locator('text=WS STREAM: DISCONNECTED')).toBeVisible({ timeout: 5000 });
    
    // Restore browser connection
    await context.setOffline(false);
    
    // Verify it automatically reconnects
    await expect(page.locator('text=WS STREAM: CONNECTED')).toBeVisible({ timeout: 15000 });
  });
});
