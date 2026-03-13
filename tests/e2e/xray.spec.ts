import { test, expect } from "@playwright/test";

// BND is used as the primary test ETF — it exists in the DB with rich data:
// holdings, fees, performance, fund_health, geographic, concentration.
// VXUS is used for the "different profile" test (international holdings).

test.describe("ETF X-Ray E2E", () => {
  test("search for BND, click result, verify dashboard loads", async ({
    page,
  }) => {
    await page.goto("/");

    // Verify home page renders
    await expect(page.getByText("ETF X-Ray").first()).toBeVisible();

    // Type into search bar
    const input = page.getByPlaceholder(/Search by ticker/i);
    await input.fill("BND");

    // Wait for dropdown suggestion containing BND ticker
    await expect(page.getByRole("listitem").filter({ hasText: "BND" }).first()).toBeVisible({
      timeout: 5000,
    });

    // Click on BND result via mousedown (SearchBar uses onMouseDown)
    await page.getByRole("listitem").filter({ hasText: "BND" }).first().click();

    // Should navigate to /xray/BND
    await expect(page).toHaveURL(/\/xray\/BND/i);

    // Verify fund name appears
    await expect(page.getByText(/Total Bond/i)).toBeVisible({ timeout: 8000 });
  });

  test("navigate directly to /xray/BND and verify cards render", async ({
    page,
  }) => {
    await page.goto("/xray/BND");

    // Wait for data to load — fund name should appear
    await expect(page.getByText(/Total Bond/i)).toBeVisible({ timeout: 8000 });

    // Filing date display
    await expect(page.getByText(/Data as of/i)).toBeVisible();

    // Holdings card present
    await expect(page.getByText(/Holdings/i).first()).toBeVisible();

    // Fee card content (BND has fee data)
    await expect(page.getByText(/Expense Ratio/i).first()).toBeVisible();

    // Performance card
    await expect(page.getByText(/Performance/i).first()).toBeVisible();

    // Fund Health card
    await expect(page.getByText(/Fund Health/i).first()).toBeVisible();

    // Concentration card
    await expect(page.getByText(/Concentration/i).first()).toBeVisible();
  });

  test("navigate to /xray/INVALIDTICKER shows error state", async ({
    page,
  }) => {
    await page.goto("/xray/INVALIDTICKER");

    // Should show error message
    await expect(
      page.getByText(/not found|error/i).first()
    ).toBeVisible({ timeout: 8000 });

    // Back to search link should be available
    await expect(page.getByText(/back to search/i)).toBeVisible();
  });

  test("/xray/VXUS shows different data profile than /xray/BND", async ({
    page,
  }) => {
    // Load BND
    await page.goto("/xray/BND");
    await expect(page.getByText(/Total Bond/i)).toBeVisible({ timeout: 8000 });
    const bndHeading = await page.locator("h1").first().textContent();

    // Load VXUS
    await page.goto("/xray/VXUS");
    await expect(page.getByText(/International/i)).toBeVisible({ timeout: 8000 });
    const vxusHeading = await page.locator("h1").first().textContent();

    // Different tickers in the heading
    expect(bndHeading).toContain("BND");
    expect(vxusHeading).toContain("VXUS");
    expect(bndHeading).not.toEqual(vxusHeading);
  });
});
