import assert from "node:assert/strict";
import { chromium } from "playwright-core";

const base = process.env.DASHBOARD_TEST_URL ?? "http://127.0.0.1:3000";
const browser = await chromium.launch({
  executablePath: process.env.DASHBOARD_BROWSER_PATH,
  ...(process.env.DASHBOARD_BROWSER_PATH ? {} : { channel: "chrome" }),
  headless: true,
});
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
page.on("pageerror", (error) => errors.push(error.stack ?? error.message));
const nav = (name) => page.getByRole("navigation", { name: "Dashboard sections" })
  .getByRole("button", { name, exact: true });
const gateway = (path) => page.request.get(base + "/api/backend/" + path);

try {
  const response = await gateway("system/status");
  assert.ok(response.ok());
  assert.equal((await response.json()).data.status, "ok");
  assert.equal((await (await page.request.get(base + "/api/health")).json()).status, "ok");

  await page.goto(base, { waitUntil: "domcontentloaded" });
  await page.getByRole("heading", { name: "Environmental overview" }).waitFor();
  await page.locator("#point option[value='hai-chau']").waitFor({ state: "attached" });
  await page.getByLabel("Sampling point").selectOption("hai-chau");
  if (process.env.DASHBOARD_EXPECT_RECOVERY === "1") {
    const response = await gateway("rainfall/coverage?location=hai-chau");
    assert.ok(response.ok());
    const [coverage] = (await response.json()).data;
    await page.waitForFunction((expected) => document.querySelector("#end")?.value === expected, coverage.last_date);
    await page.getByRole("img", { name: "daily rainfall", exact: true }).locator("canvas").first().waitFor();
    const selected = await gateway("rainfall/daily?location=hai-chau&start_date=" + coverage.last_date + "&end_date=" + coverage.last_date);
    assert.ok((await selected.json()).data.some((row) => row.rainfall_total_mm !== null));
  }
  await page.getByLabel("From", { exact: true }).fill("2023-10-01");
  await page.getByLabel("To", { exact: true }).fill("2023-10-31");
  await page.getByRole("button", { name: "Apply dates" }).click();
  const historical = page.getByRole("img", { name: "daily rainfall", exact: true });
  await historical.locator("canvas").first().waitFor();
  await page.waitForFunction(() => {
    const canvas = document.querySelector('[aria-label="daily rainfall"] canvas');
    const area = canvas?.getContext("2d");
    return area?.getImageData(0, 0, canvas.width, canvas.height).data.some((value, index) => index % 4 === 3 && value);
  });
  await page.getByRole("button", { name: "weekly", exact: true }).click();
  await page.getByRole("img", { name: "weekly rainfall", exact: true }).locator("canvas").first().waitFor();
  await page.getByRole("button", { name: "monthly", exact: true }).click();
  await page.getByRole("img", { name: "monthly rainfall", exact: true }).locator("canvas").first().waitFor();
  await page.getByRole("button", { name: "daily", exact: true }).click();
  await historical.locator("canvas").first().waitFor();
  if (process.env.DASHBOARD_DESKTOP_SCREENSHOT) {
    await page.screenshot({ path: process.env.DASHBOARD_DESKTOP_SCREENSHOT, fullPage: true });
  }

  await nav("Rainfall Analytics").click();
  await page.getByRole("button", { name: "Generate patterns" }).click();
  for (const label of ["Rainfall vs. humidity", "Rainfall vs. temperature", "Rainfall distribution",
    "Seasonal rainfall", "Weather correlations"]) {
    await page.getByRole("img", { name: label, exact: true }).locator("canvas").first().waitFor();
  }
  await page.getByRole("heading", { name: "Monthly rainfall trend" }).waitFor();
  await page.getByLabel("From", { exact: true }).fill("2023-06-01");
  await page.getByLabel("To", { exact: true }).fill("2024-02-29");
  await page.getByRole("button", { name: "Apply dates" }).click();
  await page.getByRole("button", { name: "Generate patterns" }).click();
  await page.getByRole("img", { name: "Monthly rainfall trend", exact: true }).locator("canvas").first().waitFor();

  await nav("Da Nang Map").click();
  const fullMap = page.locator(".full-map");
  const markers = fullMap.locator("path.leaflet-interactive");
  await markers.first().waitFor();
  assert.ok(await markers.count() >= 2);
  await markers.first().click({ force: true });
  await fullMap.locator(".leaflet-popup-content .popup-name").waitFor();
  const zoomIn = fullMap.locator(".leaflet-control-zoom-in");
  await zoomIn.click();
  await fullMap.getByText("OpenStreetMap", { exact: true }).waitFor();
  await fullMap.locator(".leaflet-tile-loaded, .offline-coastline").first().waitFor();
  await page.getByRole("checkbox", { name: "Selected point only" }).check();
  await page.waitForFunction(() => document.querySelectorAll(".full-map path.leaflet-interactive").length === 1);

  await nav("Machine Learning").click();
  await page.getByRole("heading", { name: "Classification evaluation" }).waitFor();
  if (process.env.DASHBOARD_EXPECT_MODELS === "1") {
    await page.getByLabel("Sampling point").selectOption("hai-chau");

    await page.getByRole("img", { name: "Weather cluster projection" }).locator("canvas").first().waitFor();
    await page.getByRole("img", { name: "Rainfall classification confusion matrix" }).locator("canvas").first().waitFor();
    const persisted = await gateway("predictions/results?location=hai-chau&limit=1");
    assert.ok(persisted.ok());
    const date = (await persisted.json()).data[0].target_date;
    await page.getByLabel("From", { exact: true }).fill(date);
    await page.getByLabel("To", { exact: true }).fill(date);
    await page.getByRole("button", { name: "Apply dates" }).click();
    await page.getByRole("columnheader", { name: "Predicted mm" }).waitFor();
    await page.locator(".classification-list summary").first().click();
    await page.locator(".classification-list progress").first().waitFor();
  }
  await nav("Data Management").click();
  await page.getByRole("heading", { name: "Ingestion history" }).waitFor();
  await page.getByRole("heading", { name: "Data quality" }).waitFor();
  await page.getByRole("columnheader", { name: "Missing timestamps" }).waitFor();

  await page.getByRole("button", { name: "Switch to light theme" }).click();
  assert.equal(await page.locator(".dashboard").getAttribute("data-theme"), "light");
  await page.setViewportSize({ width: 390, height: 844 });
  await nav("Overview").click();
  await page.getByRole("heading", { name: "Environmental overview" }).waitFor();
  const width = await page.evaluate(() => document.documentElement.scrollWidth);
  assert.ok(width <= 390, `Mobile document overflowed to ${width}px`);
  if (process.env.DASHBOARD_EXPECT_MODELS === "1") {
    await page.getByText("No records for this selection", { exact: true }).waitFor();
  }
  await page.getByLabel("From", { exact: true }).fill("2023-10-01");
  await page.getByLabel("To", { exact: true }).fill("2023-10-31");
  await page.getByRole("button", { name: "Apply dates" }).click();
  await historical.locator("canvas").first().waitFor();
  if (process.env.DASHBOARD_MOBILE_SCREENSHOT) {
    await page.screenshot({ path: process.env.DASHBOARD_MOBILE_SCREENSHOT, fullPage: true });
  }
  await nav("Da Nang Map").click();
  await page.locator(".full-map .leaflet-container").waitFor();
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth) <= 390);
  assert.deepEqual(errors, []);

  // A transport failure exercises the UI fallback without substituting weather data.
  await page.route("**/api/backend/locations", (route) => route.abort());
  await page.route("**/api/backend/weather/latest", (route) => route.abort());
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.getByRole("alert").getByText("Could not load data").first().waitFor();
  console.log("Live gateway, rainfall charts, generated patterns, map markers/popups and zoom, ML and data views, theme, mobile layout, and network error recovery UI verified.");
} finally {
  await browser.close();
}

