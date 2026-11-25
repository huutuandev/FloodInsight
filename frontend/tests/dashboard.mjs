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
page.on("pageerror", (error) => errors.push(error.message));
page.on("console", (message) => {
  if (/hydration|hydrated|did not match/i.test(message.text())) errors.push(message.text());
});
const nav = (name) => page.getByRole("navigation", { name: "Dashboard sections" }).getByRole("button", { name, exact: true });
const heading = (name) => page.getByRole("heading", { name, exact: true });
const canvas = (name) => page.getByRole("img", { name, exact: true }).locator("canvas").first();
async function api(path) {
  const response = await page.request.get(base + "/api/backend/" + path);
  assert.ok(response.ok(), path + " failed with " + response.status());
  return (await response.json()).data;
}

try {
  const points = await api("flood-risk/locations");
  assert.deepEqual(points.map((point) => point.code).sort(),
    ["cam-le", "hai-chau", "lien-chieu", "ngu-hanh-son", "thanh-khe"]);
  const focus = points.find((point) => point.code === "hai-chau") ?? points[0];
  const [coverage] = await api("rainfall/coverage?location=" + focus.code);
  assert.ok(coverage);
  const predictions = await api("flood-predictions/results?current=true");
  const [weatherStatus, coverageStatus] = await Promise.all([api("system/status"), api("flood-data/coverage")]);
  assert.equal(weatherStatus.services.postgres.status, "ok");
  assert.equal((await (await page.request.get(base + "/api/health")).json()).status, "ok");

  await page.goto(base, { waitUntil: "domcontentloaded" });
  await heading("Flood Overview").waitFor();
  await heading("Highest current forecast risk").waitFor();
  await page.getByText("Experimental research tool.", { exact: false }).waitFor();
  await page.getByLabel("Sampling point").selectOption(focus.code);
  assert.equal(await page.getByLabel("Sampling point").locator("option").count(), points.length);
  await heading("Current weather").waitFor();
  await page.getByText("Forecast rain · next 6 h", { exact: true }).waitFor();
  if ((await api("weather/latest")).some((row) => row.location_code === focus.code)) {
    await page.getByText("Relative humidity", { exact: true }).waitFor();
  }
  await page.waitForFunction((end) => document.querySelector("#end")?.value === end, coverage.last_date);
  await canvas("daily rainfall").waitFor();
  await page.getByLabel("From", { exact: true }).fill(coverage.last_date);
  await page.getByLabel("To", { exact: true }).fill(coverage.last_date);
  await page.getByRole("button", { name: "Apply dates" }).click();
  await canvas("daily rainfall").waitFor();
  assert.equal(await page.locator("section").filter({ has: heading("Validated flood predictions") }).locator(".risk-value").innerText(),
    String(predictions.length));
  if (process.env.DASHBOARD_DESKTOP_SCREENSHOT) await page.screenshot({ path: process.env.DASHBOARD_DESKTOP_SCREENSHOT, fullPage: true });

  await nav("Flood Risk Forecast").click();
  await heading("Location comparison").waitFor();
  await page.getByRole("columnheader", { name: "Flood Risk Index" }).getByRole("button").click();
  assert.equal(await page.getByRole("columnheader", { name: "Flood Risk Index" }).getAttribute("aria-sort"), "ascending");
  await page.getByRole("button", { name: "Generate assessments" }).click();
  await page.getByText(points.length + " assessment results returned.", { exact: true }).waitFor();
  await page.getByRole("button", { name: "Inspect " + focus.name, exact: true }).click();
  await heading("Contributing factors and evidence").waitFor();
  await page.getByRole("rowheader", { name: "forecast rainfall", exact: true }).waitFor();
  await page.getByText("Sources, valid times and coverage limits", { exact: true }).click();
  await page.getByText("Latest evidence available", { exact: true }).waitFor();

  await nav("Rainfall Analytics").click();
  await canvas("daily rainfall").waitFor();
  await page.getByRole("button", { name: "weekly", exact: true }).click();
  await canvas("weekly rainfall").waitFor();
  await page.getByRole("button", { name: "monthly", exact: true }).click();
  await canvas("monthly rainfall").waitFor();
  await page.getByRole("button", { name: "Generate patterns" }).click();
  await heading("Rainfall distribution").waitFor();
  await canvas("Rainfall distribution").waitFor();

  await nav("Da Nang Flood Map").click();
  const map = page.locator(".full-map");
  const markers = map.locator("path.leaflet-interactive");
  await markers.first().waitFor();
  assert.equal(await markers.count(), points.length);
  await markers.first().click({ force: true });
  await map.locator(".leaflet-popup-content .popup-name").waitFor();
  await map.getByText("Valid until", { exact: false }).waitFor();
  await map.getByText("Street-level conditions are unverified.", { exact: false }).waitFor();
  await map.locator(".leaflet-control-zoom-in").click();
  await map.getByText("OpenStreetMap", { exact: true }).waitFor();

  await nav("Machine Learning").click();
  for (const title of ["Flood probability predictions", "Flood model evaluation", "Confusion matrix", "Calibration curve",
    "Model comparison", "Feature importance", "Flood-related clustering"]) await heading(title).waitFor();
  await canvas("Flood terrain profile groups").waitFor();
  if (!(await api("flood-predictions/metrics")).evaluation) {
    await page.getByText("Evaluation metrics unavailable", { exact: true }).waitFor();
  }
  await page.getByRole("button", { name: "Show legacy rainfall evaluation" }).click();
  await heading("Classification evaluation").waitFor();
  if (process.env.DASHBOARD_EXPECT_MODELS === "1") {
    await canvas("Rainfall classification confusion matrix").waitFor();
    await canvas("Weather cluster projection").waitFor();
  }

  await nav("Data Management").click();
  for (const title of ["Flood dataset coverage", "Weather source coverage", "Flood-event coverage", "Terrain coverage",
    "Hydrological coverage", "Model training readiness", "Assessment history", "Ingestion history", "Data quality"]) await heading(title).waitFor();
  assert.equal(await page.locator(".flood-data-counts > div").filter({ hasText: "Documented events" }).locator("strong").innerText(),
    String(coverageStatus.counts.flood_events));

  await page.getByRole("button", { name: "Switch to light theme" }).click();
  assert.equal(await page.locator(".dashboard").getAttribute("data-theme"), "light");
  await page.setViewportSize({ width: 390, height: 844 });
  for (const section of ["Flood Overview", "Flood Risk Forecast", "Da Nang Flood Map"]) {
    await nav(section).click();
    await heading(section).waitFor();
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth) <= 390, section + " overflows mobile viewport");
  }
  await page.waitForFunction((expected) => {
    const container = document.querySelector(".full-map .leaflet-container");
    if (!container) return false;
    const bounds = container.getBoundingClientRect();
    const markers = [...container.querySelectorAll("path.leaflet-interactive")];
    return markers.length === expected && markers.every((marker) => {
      const box = marker.getBoundingClientRect();
      const x = box.left + box.width / 2, y = box.top + box.height / 2;
      return x >= bounds.left && x <= bounds.right && y >= bounds.top && y <= bounds.bottom;
    });
  }, points.length);
  if (process.env.DASHBOARD_MOBILE_SCREENSHOT) await page.screenshot({ path: process.env.DASHBOARD_MOBILE_SCREENSHOT, fullPage: true });
  assert.deepEqual(errors, []);

  await page.route("**/api/backend/flood-risk/latest", (route) => route.abort());
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.getByRole("alert").getByText("Could not load data").first().waitFor();
  console.log("Live flood and rainfall views, generation, sorting, details, map, model coverage, theme, mobile layout and error state verified.");
} finally {
  await browser.close();
}
